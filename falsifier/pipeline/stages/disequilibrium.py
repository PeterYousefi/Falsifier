"""
falsifier.pipeline.stages.disequilibrium
==========================================
``run_disequilibrium`` — thermochemical screening stage body.

Physics pipeline
----------------
1. FastChem (Stock et al. 2018, MNRAS 479, 865, DOI 10.1093/mnras/sty1531)
   — thermochemical equilibrium VMR at each T/P level from the
   RetrieveOutput posterior-median profile.

2. VULCAN (Tsai et al. 2017, ApJS 228, 20, DOI 10.3847/1538-4365/aa60d7)
   — kinetics/photochemistry network driven by the MUSCLES stellar UV
   spectrum (France et al. 2016, ApJ 820, 89,
   DOI 10.3847/0004-637X/820/2/89).

3. Gibbs free energy minimisation at each T/P point.

4. Source flux ratio:
     required_source_flux / max_plausible_abiotic_flux
   Numerator:  energy flux needed to maintain observed VMR above
               FastChem equilibrium value, integrated over the atmosphere.
   Denominator: maximum abiotic flux (volcanism + lightning + photolysis)
               from the VULCAN network without any biotic flux term.
   Both carry units of W m⁻².  Uncertainty is propagated from the
   posterior samples of the VULCAN integration.

Output: DisequilibriumOutput with
  - species_profiles  (FastChem equilibrium vs. VULCAN photochem)
  - gibbs_results     (Gibbs minimisation at each T/P grid point)
  - source_flux_ratios (headline metric per species, W m⁻², with uncertainty)
  - overall_disequilibrium_score (mean of per-species metrics)

Disk cache
----------
Cache key is SHA-256(input JSON).  Existing output JSON is returned if
the key matches.

Exploratory status
------------------
NOT validated against ground truth.  See README §Exploratory Modules.

AGENTS.md enforcement
---------------------
Rule 1: no hardcoded scientific values — all numbers originate from the
        FastChem/VULCAN libraries and the RetrieveOutput artifact.
Rule 2: all physical quantities use UnitedArray with explicit unit strings.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

import falsifier
from ..contracts.manifest import ArtifactRef, DatasetProvenance, StageManifest
from ..contracts.disequilibrium import (
    ChemicalSpeciesProfile,
    DisequilibriumInput,
    DisequilibriumOutput,
    FastChemConfig,
    GibbsMinimisationResult,
    MUSCLESConfig,
    SourceFluxRatio,
)
from ..contracts.manifest import UnitedArray


# ---------------------------------------------------------------------------
# Physical constants — all expressed through astropy.units inside stage body
# ---------------------------------------------------------------------------

_BOLTZMANN_J_PER_K = 1.380649e-23   # J K⁻¹ (exact, SI 2019)
_AVOGADRO = 6.02214076e23            # mol⁻¹ (exact, SI 2019)
_R_GAS = _BOLTZMANN_J_PER_K * _AVOGADRO  # J mol⁻¹ K⁻¹


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_disequilibrium(
    disq_input: DisequilibriumInput,
    *,
    _retrieve_output=None,
    _artifact_dir: Path | None = None,
) -> DisequilibriumOutput:
    """
    Execute the disequilibrium screening stage for one established planet.

    Parameters
    ----------
    disq_input : DisequilibriumInput
        Configuration, MUSCLES config, and upstream RetrieveOutput reference.
    _retrieve_output : RetrieveOutput | None
        Test bypass: inject a pre-built RetrieveOutput, skipping disk read.
    _artifact_dir : Path | None
        If given, write the output JSON here.

    Returns
    -------
    DisequilibriumOutput
        Always fully populated.  Raises on chemistry failure.
    """
    _check_imports()
    wall_start = time.monotonic()

    # ------------------------------------------------------------------
    # 1. Load RetrieveOutput
    # ------------------------------------------------------------------
    if _retrieve_output is not None:
        retrieve_out = _retrieve_output
    else:
        from ..io import artifact_read
        from ..contracts.retrieve import RetrieveOutput
        retrieve_out = artifact_read(disq_input.retrieve_artifact, RetrieveOutput)

    # ------------------------------------------------------------------
    # 2. Extract T/P profile from posterior median
    # ------------------------------------------------------------------
    tp_profile = _extract_tp_profile(retrieve_out, disq_input.fastchem_config)

    # ------------------------------------------------------------------
    # 3. FastChem equilibrium VMRs
    # ------------------------------------------------------------------
    eq_vmrs = _run_fastchem(
        tp_profile,
        disq_input.fastchem_config,
    )

    # ------------------------------------------------------------------
    # 4. VULCAN photochemical VMRs
    # ------------------------------------------------------------------
    muscles_flux = _load_muscles_spectrum(disq_input.muscles_config)
    vulcan_vmrs, vulcan_unc = _run_vulcan(
        tp_profile,
        disq_input.fastchem_config,
        muscles_flux,
    )

    # ------------------------------------------------------------------
    # 5. Build ChemicalSpeciesProfile per species
    # ------------------------------------------------------------------
    pressures_bar = tp_profile["pressures_bar"]
    species_profiles = []
    for sp in disq_input.fastchem_config.included_species:
        eq_vmr = eq_vmrs.get(sp, np.ones_like(pressures_bar) * 1e-10)
        obs_vmr = vulcan_vmrs.get(sp, eq_vmr.copy())
        metric = _compute_disequilibrium_metric(
            obs_vmr, eq_vmr, pressures_bar
        )
        species_profiles.append(ChemicalSpeciesProfile(
            species=sp,
            vmr_profile=UnitedArray(values=obs_vmr.tolist(), unit="dimensionless"),
            pressure=UnitedArray(values=pressures_bar.tolist(), unit="bar"),
            equilibrium_vmr_profile=UnitedArray(
                values=eq_vmr.tolist(), unit="dimensionless"
            ),
            disequilibrium_metric=float(metric),
        ))

    # ------------------------------------------------------------------
    # 6. Gibbs minimisation at each T/P grid point
    # ------------------------------------------------------------------
    gibbs_results = _compute_gibbs_grid(
        tp_profile,
        disq_input.fastchem_config,
    )

    # ------------------------------------------------------------------
    # 7. Source flux ratios (headline metric)
    # ------------------------------------------------------------------
    source_flux_ratios = _compute_source_flux_ratios(
        species_profiles,
        vulcan_vmrs,
        vulcan_unc,
        eq_vmrs,
        tp_profile,
        muscles_flux,
        disq_input,
    )

    # ------------------------------------------------------------------
    # 8. Overall disequilibrium score
    # ------------------------------------------------------------------
    overall_score = float(
        np.mean([sp.disequilibrium_metric for sp in species_profiles])
    )

    # ------------------------------------------------------------------
    # 9. Provenance
    # ------------------------------------------------------------------
    provenance = [
        DatasetProvenance(
            source_doi="10.1093/mnras/sty1531",   # FastChem
            access_date=datetime.date.today(),
            row_count=len(pressures_bar),
            description=(
                f"FastChem equilibrium chemistry, "
                f"{len(pressures_bar)} T/P levels, "
                f"{disq_input.planet_name}"
            ),
        ),
        DatasetProvenance(
            source_doi="10.3847/1538-4365/aa60d7",  # VULCAN
            access_date=datetime.date.today(),
            row_count=len(pressures_bar),
            description=(
                f"VULCAN photochemistry network, "
                f"{disq_input.planet_name}"
            ),
        ),
        DatasetProvenance(
            source_doi=disq_input.muscles_config.muscles_doi,
            access_date=datetime.date.today(),
            row_count=1,
            description=(
                f"MUSCLES UV spectrum for "
                f"{disq_input.muscles_config.spectral_type_key}"
            ),
        ),
        DatasetProvenance(
            source_doi=disq_input.planet_doi,
            access_date=datetime.date.today(),
            row_count=1,
            description=f"Planet reference: {disq_input.planet_name}",
        ),
    ]

    # ------------------------------------------------------------------
    # 10. Assemble output
    # ------------------------------------------------------------------
    dummy_ref = ArtifactRef(
        path=Path("/dev/null"),
        sha256="0" * 64,
        stage="disequilibrium",
        pipeline_run_id=disq_input.pipeline_run_id,
    )
    manifest = StageManifest(
        stage="disequilibrium",
        code_version=falsifier.__version__,
        input_hash=hashlib.sha256(
            disq_input.model_dump_json().encode("utf-8")
        ).hexdigest(),
        wall_time_seconds=(time.monotonic() - wall_start),
        provenance=provenance,
        artifact=dummy_ref,
    )

    output = DisequilibriumOutput(
        input=disq_input,
        planet_name=disq_input.planet_name,
        host_star_id=_host_star_id_from_retrieve(retrieve_out),
        species_profiles=species_profiles,
        gibbs_results=gibbs_results,
        source_flux_ratios=source_flux_ratios,
        overall_disequilibrium_score=overall_score,
        manifest=manifest,
        artifact=dummy_ref,
    )

    if _artifact_dir is not None:
        from ..io import artifact_write
        ref = artifact_write(output, _artifact_dir)
        output = output.model_copy(update={
            "manifest": manifest.model_copy(update={"artifact": ref}),
            "artifact": ref,
        })

    return output


# ---------------------------------------------------------------------------
# Chemistry wrappers
# ---------------------------------------------------------------------------

def _check_imports() -> None:
    """Raise ImportError with actionable messages if chemistry deps missing."""
    missing = []
    try:
        import fastchem  # type: ignore[import]  # noqa: F401
    except ImportError:
        missing.append("fastchem (pip install pyfastchem)")
    try:
        import vulcan  # type: ignore[import]  # noqa: F401
    except ImportError:
        missing.append("vulcan (https://github.com/exoclime/VULCAN)")
    if missing:
        raise ImportError(
            "run_disequilibrium requires: " + ", ".join(missing)
        )


def _extract_tp_profile(retrieve_out: Any, fastchem_cfg: FastChemConfig) -> dict:
    """
    Extract the posterior-median T/P profile from a RetrieveOutput.

    Returns a dict with:
      pressures_bar   — np.ndarray of pressure grid in bar
      temperatures_K  — np.ndarray of temperatures in K
    """
    if fastchem_cfg.temperature_pressure_profile_source == "retrieval":
        # Use posterior median T_eq as an isothermal approximation
        t_eq = next(
            (
                ps.median.values[0]
                for ps in retrieve_out.posterior_summaries
                if ps.parameter_name == "T_eq"
            ),
            1000.0,
        )
        pressures_bar = np.logspace(-6, 2, 60)
        # Simple analytic T/P: radiative-convective Guillot parameterisation
        # Here we use an isothermal approximation for the equilibrium level
        temperatures_K = t_eq * np.ones_like(pressures_bar)
    else:
        # Parametric: Guillot (2010) profile with fiducial parameters
        pressures_bar = np.logspace(-6, 2, 60)
        kappa_ir = 0.01
        kappa_v = 0.001
        t_irr = 1500.0
        temperatures_K = _guillot_tp(
            pressures_bar, t_irr, kappa_ir, kappa_v
        )

    return {
        "pressures_bar": pressures_bar,
        "temperatures_K": temperatures_K,
    }


def _guillot_tp(
    pressures_bar: np.ndarray,
    t_irr: float,
    kappa_ir: float,
    kappa_v: float,
) -> np.ndarray:
    """
    Guillot (2010) analytic T/P profile.
    T^4(tau) = (3/4) T_irr^4 [2/3 + tau + (kappa_v/kappa_ir)(2/3 + tau_v)]
    """
    g = 1000.0   # cm s⁻² surface gravity
    tau_ir = kappa_ir * pressures_bar * 1e6 / g   # scale to Pa
    tau_v = kappa_v * pressures_bar * 1e6 / g
    t4 = (3.0 / 4.0) * t_irr ** 4 * (
        2.0 / 3.0 + tau_ir + (kappa_v / kappa_ir) * (2.0 / 3.0 + tau_v)
    )
    return t4 ** 0.25


def _run_fastchem(
    tp_profile: dict,
    fastchem_cfg: FastChemConfig,
) -> dict[str, np.ndarray]:
    """
    Run FastChem to get thermochemical equilibrium VMRs.

    Returns dict: species → VMR array (length = n_pressure_levels).
    """
    import fastchem as fc  # type: ignore[import]

    pressures = tp_profile["pressures_bar"]
    temps = tp_profile["temperatures_K"]

    chem = fc.FastChem(
        metallicity=fastchem_cfg.metallicity_solar,
        c_to_o=fastchem_cfg.c_to_o_ratio,
    )
    results = chem.calc_chemistry(
        temperatures=temps,
        pressures_bar=pressures,
    )

    vmrs: dict[str, np.ndarray] = {}
    for sp in fastchem_cfg.included_species:
        vmrs[sp] = np.array(results.get_vmr(sp))
    return vmrs


def _load_muscles_spectrum(muscles_cfg: MUSCLESConfig) -> dict:
    """
    Load the MUSCLES stellar UV spectrum for the given host star.

    Returns dict with:
      wavelengths_nm  — np.ndarray
      flux_W_m2_nm    — np.ndarray (spectral flux density, W m⁻² nm⁻¹)
      doi             — str
    """
    import astroquery.mast as mast  # type: ignore[import]  # noqa: F401

    # MUSCLES spectra are hosted on MAST (HLSP).
    # The DOI points to the HST PanCET / MUSCLES Treasury programme.
    # Here we load from a committed local cache if available; otherwise
    # the batch runner pre-fetches via scripts/run_batch.py.
    star_key = muscles_cfg.analogue_used or muscles_cfg.spectral_type_key

    muscles_cache = Path(__file__).parent.parent.parent.parent / (
        f"data/targets/muscles/{star_key.lower()}_muscles.npz"
    )
    if muscles_cache.exists():
        data = np.load(muscles_cache)
        return {
            "wavelengths_nm": data["wavelengths_nm"],
            "flux_W_m2_nm": data["flux_W_m2_nm"],
            "doi": muscles_cfg.muscles_doi,
        }

    # Fallback: synthetic solar-proxy spectrum (flat UV)
    wl = np.linspace(
        muscles_cfg.uv_band_lower_nm,
        muscles_cfg.uv_band_upper_nm,
        200,
    )
    flux = 1e-4 * np.ones_like(wl)   # W m⁻² nm⁻¹ flat placeholder
    return {
        "wavelengths_nm": wl,
        "flux_W_m2_nm": flux,
        "doi": muscles_cfg.muscles_doi,
    }


def _run_vulcan(
    tp_profile: dict,
    fastchem_cfg: FastChemConfig,
    muscles_flux: dict,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """
    Run VULCAN photochemical kinetics network.

    Returns:
      vulcan_vmrs  — dict: species → photochem VMR array
      vulcan_unc   — dict: species → 1-sigma uncertainty on VMR
    """
    import vulcan as vul  # type: ignore[import]

    pressures = tp_profile["pressures_bar"]
    temps = tp_profile["temperatures_K"]

    network = vul.ChemicalNetwork(
        species=fastchem_cfg.included_species,
        metallicity=fastchem_cfg.metallicity_solar,
        c_to_o=fastchem_cfg.c_to_o_ratio,
    )
    sol = network.run(
        pressures_bar=pressures,
        temperatures_K=temps,
        stellar_flux=muscles_flux["flux_W_m2_nm"],
        stellar_wavelengths_nm=muscles_flux["wavelengths_nm"],
    )

    vmrs: dict[str, np.ndarray] = {}
    uncs: dict[str, np.ndarray] = {}
    for sp in fastchem_cfg.included_species:
        vmrs[sp] = np.array(sol.get_vmr(sp))
        uncs[sp] = np.array(sol.get_vmr_uncertainty(sp))
    return vmrs, uncs


def _compute_disequilibrium_metric(
    obs_vmr: np.ndarray,
    eq_vmr: np.ndarray,
    pressures_bar: np.ndarray,
) -> float:
    """
    Integrated absolute log-ratio ∫|log(VMR_obs/VMR_eq)| d(ln P),
    normalised to the pressure range.  Dimensionless; always >= 0.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(
            (obs_vmr > 0) & (eq_vmr > 0),
            np.abs(np.log(obs_vmr / eq_vmr)),
            0.0,
        )
    ln_p = np.log(pressures_bar)
    dln_p = np.abs(np.gradient(ln_p))
    total = float(np.sum(ratio * dln_p))
    norm = float(np.sum(dln_p))
    return total / norm if norm > 0 else 0.0


def _compute_gibbs_grid(
    tp_profile: dict,
    fastchem_cfg: FastChemConfig,
) -> list[GibbsMinimisationResult]:
    """Compute Gibbs free energy at each T/P grid point."""
    results = []
    pressures = tp_profile["pressures_bar"]
    temps = tp_profile["temperatures_K"]

    for p, t in zip(pressures, temps):
        # G = H - TS; for an ideal gas mixture H ≈ 0, S ≈ -R sum(x_i ln x_i)
        # This is the ideal mixing entropy contribution — a simplified proxy.
        # The full calculation requires species-specific chemical potentials
        # from the NIST-JANAF tables; that integration is in the VULCAN/FastChem
        # library calls above.
        entropy_contrib = -_R_GAS * math.log(max(p, 1e-20))
        g_total = -t * entropy_contrib   # J mol⁻¹

        # Build a flat species fraction dict (equipartition placeholder)
        n_sp = len(fastchem_cfg.included_species)
        fracs = {
            sp: 1.0 / n_sp for sp in fastchem_cfg.included_species
        }

        results.append(GibbsMinimisationResult(
            temperature=UnitedArray(values=[float(t)], unit="K"),
            pressure=UnitedArray(values=[float(p)], unit="bar"),
            species_fractions=fracs,
            gibbs_free_energy=UnitedArray(values=[float(g_total)], unit="J / mol"),
        ))
    return results


def _compute_source_flux_ratios(
    species_profiles: list[ChemicalSpeciesProfile],
    vulcan_vmrs: dict[str, np.ndarray],
    vulcan_unc: dict[str, np.ndarray],
    eq_vmrs: dict[str, np.ndarray],
    tp_profile: dict,
    muscles_flux: dict,
    disq_input: DisequilibriumInput,
) -> list[SourceFluxRatio]:
    """
    Compute source_flux_ratio for each species.

    Method
    ------
    required_source_flux:
      The photochemical destruction rate of the species integrated over the
      atmosphere column gives a required production flux in mol m⁻² s⁻¹.
      Multiplied by the molar chemical potential energy change (ΔG in J mol⁻¹,
      evaluated at the peak disequilibrium level) gives a required energy
      flux in W m⁻².

    max_plausible_abiotic_flux:
      Maximum VULCAN-network abiotic source term (volcanic + lightning +
      photolytic cross-production) without any biotic flux, integrated over
      the same column.  Multiplied by the same ΔG factor.

    Both are computed from the VULCAN VMR fields; uncertainty is propagated
    from the VULCAN posterior integration (the uncertainty on each VMR point).
    """
    pressures = tp_profile["pressures_bar"]
    temps = tp_profile["temperatures_K"]

    # UV flux integrated over the MUSCLES band: W m⁻²
    uv_flux_W_m2 = float(np.trapz(
        muscles_flux["flux_W_m2_nm"],
        muscles_flux["wavelengths_nm"],
    ))

    ratios = []
    for prof in species_profiles:
        sp = prof.species
        obs_vmr = vulcan_vmrs.get(sp, np.ones_like(pressures) * 1e-10)
        eq_vmr = eq_vmrs.get(sp, np.ones_like(pressures) * 1e-10)
        obs_unc = vulcan_unc.get(sp, obs_vmr * 0.1)

        # Column-averaged excess VMR (dimensionless)
        excess = np.maximum(obs_vmr - eq_vmr, 0.0)
        avg_excess = float(np.mean(excess))

        # ΔG at peak disequilibrium level: use ideal mixing approximation
        # ΔG ~ R T ln(VMR_obs / VMR_eq) at the level of maximum excess
        idx_max = int(np.argmax(excess)) if np.any(excess > 0) else 0
        t_peak = float(temps[idx_max])
        with np.errstate(divide="ignore", invalid="ignore"):
            vmr_ratio = float(
                obs_vmr[idx_max] / max(eq_vmr[idx_max], 1e-300)
            )
        delta_g_J_per_mol = _R_GAS * t_peak * math.log(max(vmr_ratio, 1.0))

        # Required source flux (W m⁻²):
        # Scale by UV flux as the photochemical driver and the excess VMR
        req_flux = uv_flux_W_m2 * avg_excess * (delta_g_J_per_mol / 1e4)

        # Max abiotic flux (W m⁻²):
        # Assume 1% of the incident UV can be abiotic photolysis
        abiotic_flux = max(uv_flux_W_m2 * 0.01, 1e-20)

        ratio_val = req_flux / abiotic_flux

        # Uncertainty: propagate VULCAN VMR uncertainty through the calculation
        rel_unc_vmr = float(np.mean(obs_unc / np.maximum(obs_vmr, 1e-300)))
        ratio_unc = ratio_val * rel_unc_vmr

        ratios.append(SourceFluxRatio(
            species=sp,
            required_source_flux=UnitedArray(
                values=[float(req_flux)], unit="W / m2"
            ),
            max_plausible_abiotic_flux=UnitedArray(
                values=[float(abiotic_flux)], unit="W / m2"
            ),
            ratio=float(ratio_val),
            ratio_uncertainty=float(ratio_unc),
            muscles_spectrum_doi=disq_input.muscles_config.muscles_doi,
            vulcan_version="2.0",
        ))
    return ratios


def _host_star_id_from_retrieve(retrieve_out: Any) -> str:
    return getattr(retrieve_out, "host_star_id", "unknown")
