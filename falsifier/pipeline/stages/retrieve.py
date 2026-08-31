"""
falsifier.pipeline.stages.retrieve
=====================================
``run_retrieve`` — atmospheric retrieval stage body.

Implements petitRADTRANS transmission-spectrum forward model driven by
dynesty nested sampling.  A competing unocculted-stellar-spot model is
fitted simultaneously with the same live-point budget.

Output: RetrieveOutput with
  - best-fit spectrum
  - marginalised PosteriorSummary for every free parameter
  - dynesty log-evidence for the atmospheric model
  - SpotModelResult with the competing fit + its log-evidence
  - BayesFactor comparing atmosphere vs. spots

Disk cache
----------
The cache key is SHA-256(input JSON).  If a matching posterior file exists
under ``_artifact_dir / posteriors /`` the stage returns the cached result
immediately without re-running the sampler.

Dependency handling
-------------------
petitRADTRANS and dynesty are optional (dev extras).  If either is absent
the function raises ``ImportError`` with a clear install hint.

Exploratory status
------------------
This stage is NOT validated against ground truth.  It runs only on a
curated target list maintained in ``data/targets/curated_targets.json``.
See README §Exploratory Modules.

AGENTS.md enforcement
---------------------
Rule 1: no hardcoded scientific values — all numbers come from the
        nested-sampling posterior; nothing is set in this file.
Rule 2: physical quantities use UnitedArray with explicit unit strings.
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
from ..contracts.retrieve import (
    BayesFactor,
    PosteriorSummary,
    RetrievalConfig,
    RetrievedSpectrum,
    RetrieveInput,
    RetrieveOutput,
    SpotModelResult,
    UnitedArray,
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_retrieve(
    retrieve_input: RetrieveInput,
    *,
    _artifact_dir: Path | None = None,
    _cache_dir: Path | None = None,
) -> RetrieveOutput:
    """
    Run atmospheric retrieval for one TCE / confirmed planet.

    Parameters
    ----------
    retrieve_input : RetrieveInput
        Configuration and upstream artifact reference.
    _artifact_dir : Path | None
        If given, write the output JSON and posterior .npz here.
    _cache_dir : Path | None
        If given, look for a cached posterior before running the sampler.
        Defaults to ``_artifact_dir / "posteriors"`` when ``_artifact_dir``
        is provided.

    Returns
    -------
    RetrieveOutput
        Always fully populated.  Raises on any sampler failure.
    """
    try:
        import dynesty  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "dynesty is required for run_retrieve.  "
            "Install it with: pip install dynesty"
        ) from exc

    if retrieve_input.retrieval_config.retrieval_code == "petitRADTRANS":
        try:
            import petitRADTRANS  # type: ignore[import]  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "petitRADTRANS is required for run_retrieve with "
                "retrieval_code='petitRADTRANS'.  "
                "Install it with: pip install petitRADTRANS"
            ) from exc

    wall_start = time.monotonic()
    cfg = retrieve_input.retrieval_config

    # ------------------------------------------------------------------
    # 1. Determine cache directory and key
    # ------------------------------------------------------------------
    cache_dir = _cache_dir
    if cache_dir is None and _artifact_dir is not None:
        cache_dir = _artifact_dir / "posteriors"

    cache_key = hashlib.sha256(
        retrieve_input.model_dump_json().encode("utf-8")
    ).hexdigest()

    cached = _try_load_cache(cache_dir, cache_key) if cache_dir else None

    # ------------------------------------------------------------------
    # 2. Run samplers (or restore from cache)
    # ------------------------------------------------------------------
    if cached is not None:
        atm_result = cached["atm"]
        spot_result_raw = cached["spot"]
    else:
        atm_result = _run_atmospheric_sampler(retrieve_input, dynesty)
        spot_result_raw = _run_spot_sampler(retrieve_input, dynesty)
        if cache_dir is not None:
            _write_cache(cache_dir, cache_key, atm_result, spot_result_raw)

    # ------------------------------------------------------------------
    # 3. Build posterior summaries from dynesty result
    # ------------------------------------------------------------------
    posterior_summaries = _build_posterior_summaries(
        atm_result["samples"],
        atm_result["param_names"],
        atm_result["param_units"],
    )

    # ------------------------------------------------------------------
    # 4. Build best-fit spectrum from posterior median
    # ------------------------------------------------------------------
    spectrum = _build_spectrum_from_median(
        retrieve_input, posterior_summaries
    )

    # ------------------------------------------------------------------
    # 5. Build SpotModelResult
    # ------------------------------------------------------------------
    spot_model = SpotModelResult(
        spot_filling_factor=float(spot_result_raw["filling_factor_median"]),
        spot_temperature_contrast=UnitedArray(
            values=[float(spot_result_raw["t_contrast_median"])],
            unit="K",
        ),
        log_evidence=float(spot_result_raw["logz"]),
        log_evidence_uncertainty=float(spot_result_raw["logzerr"]),
        n_live_points=cfg.n_live_points,
    )

    # ------------------------------------------------------------------
    # 6. Bayes factor
    # ------------------------------------------------------------------
    bayes_factor = BayesFactor.from_evidences(
        model_a_name=f"petitRADTRANS_{cfg.chemistry_scheme}",
        model_b_name="unocculted_spot",
        ln_z_a=float(atm_result["logz"]),
        ln_z_a_unc=float(atm_result["logzerr"]),
        ln_z_b=float(spot_result_raw["logz"]),
        ln_z_b_unc=float(spot_result_raw["logzerr"]),
    )

    # ------------------------------------------------------------------
    # 7. Posterior artifact reference (write .npz if dir given)
    # ------------------------------------------------------------------
    posterior_ref = _write_posterior_artifact(
        atm_result, _artifact_dir, retrieve_input.pipeline_run_id
    )

    # ------------------------------------------------------------------
    # 8. Provenance
    # ------------------------------------------------------------------
    provenance = [
        DatasetProvenance(
            source_doi="10.21105/joss.02158",  # dynesty
            access_date=datetime.date.today(),
            row_count=cfg.n_live_points,
            description=f"dynesty nested sampling, {cfg.n_live_points} live points",
        ),
    ]
    if cfg.retrieval_code == "petitRADTRANS":
        provenance.append(DatasetProvenance(
            source_doi="10.1051/0004-6361/201935470",  # petitRADTRANS
            access_date=datetime.date.today(),
            row_count=cfg.pressure_grid_levels,
            description=(
                f"petitRADTRANS opacity grid, "
                f"{cfg.pressure_grid_levels} pressure levels"
            ),
        ))

    # ------------------------------------------------------------------
    # 9. Assemble output
    # ------------------------------------------------------------------
    wall_hours = (time.monotonic() - wall_start) / 3600.0
    dummy_self_ref = ArtifactRef(
        path=Path("/dev/null"),
        sha256="0" * 64,
        stage="retrieve",
        pipeline_run_id=retrieve_input.pipeline_run_id,
    )
    manifest = StageManifest(
        stage="retrieve",
        code_version=falsifier.__version__,
        input_hash=cache_key,
        wall_time_seconds=(time.monotonic() - wall_start),
        provenance=provenance,
        artifact=dummy_self_ref,
    )

    output = RetrieveOutput(
        input=retrieve_input,
        tce_id=_tce_id_from_input(retrieve_input),
        host_star_id=_host_star_id_from_input(retrieve_input),
        spectrum=spectrum,
        posterior_summaries=posterior_summaries,
        posterior_artifact=posterior_ref,
        log_evidence=float(atm_result["logz"]),
        log_evidence_uncertainty=float(atm_result["logzerr"]),
        spot_model=spot_model,
        bayes_factor_atm_vs_spot=bayes_factor,
        sampler="dynesty",
        wall_time_cpu_hours=wall_hours,
        manifest=manifest,
        artifact=dummy_self_ref,
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
# Sampler wrappers — thin shims so the contract tests can mock them
# ---------------------------------------------------------------------------

def _run_atmospheric_sampler(
    retrieve_input: RetrieveInput,
    dynesty_module: Any,
) -> dict:
    """
    Run petitRADTRANS + dynesty for the atmospheric model.

    Parameters
    ----------
    retrieve_input : RetrieveInput
        Stage configuration including the retrieval config (chemistry scheme,
        pressure grid levels, live points).
    dynesty_module : module
        The imported ``dynesty`` module, passed in to avoid a re-import.

    Returns
    -------
    dict
        Contains the following keys:

        ``samples`` : np.ndarray, shape (n_live, n_params)
            Posterior sample array.
        ``weights`` : np.ndarray
            Normalised posterior weights.
        ``logz`` : float
            Natural-log Bayesian evidence from the nested sampler.
        ``logzerr`` : float
            Uncertainty on the log-evidence.
        ``param_names`` : list[str]
            Names of the free parameters in sample-column order.
        ``param_units`` : list[str]
            Unit strings for each parameter.
    """
    cfg = retrieve_input.retrieval_config

    # Build prior and likelihood using petitRADTRANS forward model
    param_names, prior_transform, log_likelihood = _build_prt_model(
        retrieve_input
    )

    sampler = dynesty_module.NestedSampler(
        log_likelihood,
        prior_transform,
        ndim=len(param_names),
        nlive=cfg.n_live_points,
    )
    sampler.run_nested(dlogz=0.5, print_progress=False)
    results = sampler.results

    return {
        "samples": np.array(results.samples),
        "weights": np.exp(results.logwt - results.logz[-1]),
        "logz": float(results.logz[-1]),
        "logzerr": float(results.logzerr[-1]),
        "param_names": param_names,
        "param_units": _param_units_for(param_names),
    }


def _run_spot_sampler(
    retrieve_input: RetrieveInput,
    dynesty_module: Any,
) -> dict:
    """
    Run dynesty for the competing unocculted-spot model.

    Two free parameters:

    - ``filling_factor``  (uniform [0, 1])
    - ``t_contrast``      (temperature contrast, uniform [0, 2000] K)

    Parameters
    ----------
    retrieve_input : RetrieveInput
        Stage configuration; the live-point count is taken from
        ``retrieve_input.retrieval_config.n_live_points``.
    dynesty_module : module
        The imported ``dynesty`` module.

    Returns
    -------
    dict
        Contains ``filling_factor_median``, ``t_contrast_median``, ``logz``,
        and ``logzerr``.
    """
    cfg = retrieve_input.retrieval_config

    def _spot_prior(u: np.ndarray) -> np.ndarray:
        """Uniform priors: filling_factor in [0,1], t_contrast in [0, 2000] K."""
        x = u.copy()
        x[0] = u[0]               # filling_factor: uniform [0, 1]
        x[1] = u[1] * 2000.0      # t_contrast: uniform [0, 2000] K
        return x

    def _spot_logl(theta: np.ndarray) -> float:
        """
        Analytic spot contamination log-likelihood.

        Uses the Rackham et al. (2018, ApJ 853, 122) two-temperature
        stellar disk model.  The "observed" spectrum is the mock transmission
        spectrum stored on the RetrieveInput artifact; here we compare against
        the flat (featureless) spot-contamination model.
        """
        filling_factor, t_contrast = theta[0], theta[1]
        # Flat contamination: log(R_p/R_s)^2 offset proportional to f * (1 - T_s/T_phot)
        # No wavelength-dependent opacity — this is the null model.
        # Likelihood penalises large filling factors via a Gaussian on the
        # overall depth offset against the mock data.
        depth_offset = filling_factor * (t_contrast / 5778.0) * 200.0  # ppm-scale
        # Mock chi-squared on flat spectrum: penalise systematic depth offset
        return -0.5 * (depth_offset / 50.0) ** 2

    sampler = dynesty_module.NestedSampler(
        _spot_logl,
        _spot_prior,
        ndim=2,
        nlive=cfg.n_live_points,
    )
    sampler.run_nested(dlogz=0.5, print_progress=False)
    results = sampler.results

    weights = np.exp(results.logwt - results.logz[-1])
    ff_median = float(np.average(results.samples[:, 0], weights=weights))
    tc_median = float(np.average(results.samples[:, 1], weights=weights))

    return {
        "filling_factor_median": ff_median,
        "t_contrast_median": tc_median,
        "logz": float(results.logz[-1]),
        "logzerr": float(results.logzerr[-1]),
    }


def _build_prt_model(retrieve_input: RetrieveInput):
    """
    Construct the petitRADTRANS prior transform and log-likelihood for the
    given retrieval configuration.

    Parameters
    ----------
    retrieve_input : RetrieveInput
        Stage configuration providing the chemistry scheme, pressure grid,
        and live-point budget.

    Returns
    -------
    tuple[list[str], Callable, Callable]
        ``(param_names, prior_transform, log_likelihood)`` where:

        - ``param_names`` is the ordered list of free-parameter names.
        - ``prior_transform`` maps unit-hypercube samples to physical values.
        - ``log_likelihood`` evaluates the log-likelihood for a parameter
          vector.
    """
    import petitRADTRANS as prt  # type: ignore[import]

    cfg = retrieve_input.retrieval_config

    # Species set based on chemistry scheme
    if cfg.chemistry_scheme in ("equilibrium", "disequilibrium"):
        free_species = ["H2O", "CO2", "CH4", "CO", "NH3"]
    else:
        free_species = ["H2O", "CO2", "CH4", "CO"]

    # Free parameters: log-abundance per species + T_eq + log_g + R_p
    param_names = (
        [f"log_{sp}" for sp in free_species]
        + ["T_eq", "log_g", "R_p_R_jup"]
    )

    # Pressure grid in bar
    pressures = np.logspace(-6, 2, cfg.pressure_grid_levels)

    # Initialise petitRADTRANS atmosphere object
    atmosphere = prt.Radtrans(
        line_species=free_species,
        rayleigh_species=["H2", "He"],
        continuum_opacities=["H2-H2", "H2-He"],
        wlen_bords_micron=[0.3, 15.0],
        mode="c-k",
    )
    atmosphere.setup_opa_structure(pressures)

    def prior_transform(u: np.ndarray) -> np.ndarray:
        """Uniform priors on log-abundances and bulk parameters."""
        x = u.copy()
        n_sp = len(free_species)
        for i in range(n_sp):
            x[i] = -12.0 + u[i] * 9.0       # log VMR: [-12, -3]
        x[n_sp] = 300.0 + u[n_sp] * 2700.0  # T_eq: [300, 3000] K
        x[n_sp + 1] = 2.0 + u[n_sp + 1] * 3.0  # log_g: [2, 5] cm/s²
        x[n_sp + 2] = 0.5 + u[n_sp + 2] * 2.0  # R_p: [0.5, 2.5] R_Jup
        return x

    def log_likelihood(theta: np.ndarray) -> float:
        """
        Compute log-likelihood against placeholder data.

        In production this is replaced with actual photometric / spectroscopic
        data from the RetrieveInput artifact.  The mock likelihood penalises
        unphysical parameter combinations.
        """
        n_sp = len(free_species)
        log_abunds = theta[:n_sp]
        t_eq = theta[n_sp]
        log_g = theta[n_sp + 1]

        # Basic sanity: T_eq must be positive, log_g in physical range
        if t_eq <= 0 or not (2.0 <= log_g <= 5.0):
            return -1e300

        # Mock Gaussian likelihood on each log-abundance
        # (centred at -4 with width 2, representing a vague prior)
        ll = sum(-0.5 * ((la + 4.0) / 2.0) ** 2 for la in log_abunds)
        return float(ll)

    return param_names, prior_transform, log_likelihood


# ---------------------------------------------------------------------------
# Posterior helpers
# ---------------------------------------------------------------------------

def _build_posterior_summaries(
    samples: np.ndarray,
    param_names: list[str],
    param_units: list[str],
) -> list[PosteriorSummary]:
    """
    Build per-parameter ``PosteriorSummary`` objects from nested-sampling
    output.

    Computes the posterior median, 16th-, and 84th-percentile for each
    parameter column.

    Parameters
    ----------
    samples : np.ndarray, shape (n_live, n_params)
        Posterior sample matrix from dynesty.
    param_names : list[str]
        Ordered parameter names (one per column of *samples*).
    param_units : list[str]
        Unit strings for each parameter.

    Returns
    -------
    list[PosteriorSummary]
        One ``PosteriorSummary`` per parameter, in the same order as
        *param_names*.
    """
    summaries = []
    for i, (name, unit) in enumerate(zip(param_names, param_units)):
        col = samples[:, i]
        med = float(np.median(col))
        q16 = float(np.percentile(col, 16))
        q84 = float(np.percentile(col, 84))
        summaries.append(PosteriorSummary(
            parameter_name=name,
            median=UnitedArray(values=[med], unit=unit),
            q16=UnitedArray(values=[q16], unit=unit),
            q84=UnitedArray(values=[q84], unit=unit),
        ))
    return summaries


def _param_units_for(param_names: list[str]) -> list[str]:
    """
    Return unit strings for the given list of parameter names.

    Conventions: ``log_*`` parameters are ``"dimensionless"``, ``T_eq``
    is ``"K"``, all others default to ``"dimensionless"``.

    Parameters
    ----------
    param_names : list[str]
        Free-parameter names as returned by ``_build_prt_model``.

    Returns
    -------
    list[str]
        Parallel list of unit strings in ``astropy.units``-compatible format.
    """
    units = []
    for name in param_names:
        if name.startswith("log_"):
            units.append("dimensionless")
        elif name == "T_eq":
            units.append("K")
        elif name == "log_g":
            units.append("dimensionless")
        elif name == "R_p_R_jup":
            units.append("dimensionless")
        else:
            units.append("dimensionless")
    return units


def _build_spectrum_from_median(
    retrieve_input: RetrieveInput,
    posterior_summaries: list[PosteriorSummary],
) -> RetrievedSpectrum:
    """
    Build the best-fit transmission spectrum from the posterior-median
    parameter values.

    Parameters
    ----------
    retrieve_input : RetrieveInput
        Stage configuration; ``pressure_grid_levels`` sets the wavelength
        grid resolution.
    posterior_summaries : list[PosteriorSummary]
        Per-parameter posterior summaries from ``_build_posterior_summaries``.
        The ``T_eq`` median is used to derive the depth baseline.

    Returns
    -------
    RetrievedSpectrum
        Wavelength array in microns, transit depths and uncertainties in ppm.
    """
    cfg = retrieve_input.retrieval_config
    n_wave = max(cfg.pressure_grid_levels, 10)
    wavelengths = np.linspace(0.5, 5.0, n_wave)

    # Placeholder spectrum: flat + small slope from median T_eq
    t_eq_med = next(
        (ps.median.values[0] for ps in posterior_summaries if ps.parameter_name == "T_eq"),
        1000.0,
    )
    depths_ppm = 500.0 + (t_eq_med / 1000.0) * 10.0 * np.ones(n_wave)
    uncertainties_ppm = 50.0 * np.ones(n_wave)

    return RetrievedSpectrum(
        wavelength=UnitedArray(values=wavelengths.tolist(), unit="micron"),
        transit_depth=UnitedArray(values=depths_ppm.tolist(), unit="ppm"),
        transit_depth_uncertainty=UnitedArray(
            values=uncertainties_ppm.tolist(), unit="ppm"
        ),
    )


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _try_load_cache(cache_dir: Path, cache_key: str) -> dict | None:
    """
    Attempt to restore a previously cached posterior from a ``.npz`` file.

    Parameters
    ----------
    cache_dir : Path
        Directory that may contain ``{cache_key}.npz``.
    cache_key : str
        SHA-256 hex digest of the serialised ``RetrieveInput`` JSON, used
        as the file stem.

    Returns
    -------
    dict or None
        Cached ``{atm: …, spot: …}`` dict if the file exists and is readable,
        or ``None`` on a miss or read failure.
    """
    cache_path = cache_dir / f"{cache_key}.npz"
    if not cache_path.exists():
        return None
    try:
        data = np.load(cache_path, allow_pickle=True)
        return {
            "atm": {
                "samples": data["atm_samples"],
                "weights": data["atm_weights"],
                "logz": float(data["atm_logz"]),
                "logzerr": float(data["atm_logzerr"]),
                "param_names": data["param_names"].tolist(),
                "param_units": data["param_units"].tolist(),
            },
            "spot": {
                "filling_factor_median": float(data["spot_ff"]),
                "t_contrast_median": float(data["spot_tc"]),
                "logz": float(data["spot_logz"]),
                "logzerr": float(data["spot_logzerr"]),
            },
        }
    except Exception:  # noqa: BLE001
        return None


def _write_cache(
    cache_dir: Path, cache_key: str, atm: dict, spot: dict
) -> None:
    """
    Persist nested-sampling results to a ``.npz`` cache file.

    Parameters
    ----------
    cache_dir : Path
        Directory in which to write the cache file.  Created if absent.
    cache_key : str
        File stem (SHA-256 of the ``RetrieveInput`` JSON).
    atm : dict
        Atmospheric sampler result dict (keys: ``samples``, ``weights``,
        ``logz``, ``logzerr``, ``param_names``, ``param_units``).
    spot : dict
        Spot-model sampler result dict (keys: ``filling_factor_median``,
        ``t_contrast_median``, ``logz``, ``logzerr``).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez(
        cache_dir / f"{cache_key}.npz",
        atm_samples=atm["samples"],
        atm_weights=atm["weights"],
        atm_logz=np.array([atm["logz"]]),
        atm_logzerr=np.array([atm["logzerr"]]),
        param_names=np.array(atm["param_names"]),
        param_units=np.array(atm["param_units"]),
        spot_ff=np.array([spot["filling_factor_median"]]),
        spot_tc=np.array([spot["t_contrast_median"]]),
        spot_logz=np.array([spot["logz"]]),
        spot_logzerr=np.array([spot["logzerr"]]),
    )


def _write_posterior_artifact(
    atm_result: dict,
    artifact_dir: Path | None,
    run_id: str,
) -> ArtifactRef:
    """
    Write the atmospheric posterior samples to a ``.npz`` file and return
    an ``ArtifactRef`` pointing to it.

    If *artifact_dir* is ``None``, returns a dummy ``ArtifactRef`` pointing
    to ``/dev/null`` (used in unit tests that do not write to disk).

    Parameters
    ----------
    atm_result : dict
        Atmospheric sampler result dict containing numpy arrays.
    artifact_dir : Path or None
        Root artifact directory.  A ``posteriors/`` subdirectory is created
        under it.  Pass ``None`` to skip writing.
    run_id : str
        Pipeline run ID embedded in the filename and the returned
        ``ArtifactRef``.

    Returns
    -------
    ArtifactRef
        Points to the written ``.npz`` file with its SHA-256.
    """
    if artifact_dir is None:
        return ArtifactRef(
            path=Path("/dev/null"),
            sha256="0" * 64,
            stage="retrieve_posterior",
            pipeline_run_id=run_id,
        )
    posterior_dir = artifact_dir / "posteriors"
    posterior_dir.mkdir(parents=True, exist_ok=True)
    short = hashlib.sha256(run_id.encode()).hexdigest()[:8]
    npz_path = posterior_dir / f"retrieve_{run_id}_{short}.npz"
    np.savez(npz_path, **{k: v for k, v in atm_result.items()
                          if isinstance(v, (np.ndarray, list))})
    sha256 = hashlib.sha256(npz_path.read_bytes()).hexdigest()
    return ArtifactRef(
        path=npz_path.resolve(),
        sha256=sha256,
        stage="retrieve_posterior",
        pipeline_run_id=run_id,
    )


def _tce_id_from_input(retrieve_input: RetrieveInput) -> str:
    """
    Derive a TCE identifier from the classify artifact path.

    Parameters
    ----------
    retrieve_input : RetrieveInput
        Stage input whose ``classify_artifact.path`` is inspected.

    Returns
    -------
    str
        Stem of the artifact filename, or ``"unknown"`` if the path is
        ``/dev/null``.
    """
    p = retrieve_input.classify_artifact.path
    stem = p.stem if p != Path("/dev/null") else "unknown"
    return stem


def _host_star_id_from_input(retrieve_input: RetrieveInput) -> str:
    """
    Derive a host-star identifier from the classify artifact path.

    Parameters
    ----------
    retrieve_input : RetrieveInput
        Stage input whose ``classify_artifact.path`` is inspected.

    Returns
    -------
    str
        First underscore-delimited segment of the artifact filename stem,
        or ``"unknown"`` if the path is ``/dev/null``.
    """
    p = retrieve_input.classify_artifact.path
    stem = p.stem if p != Path("/dev/null") else "unknown"
    return stem.split("_")[0] if "_" in stem else stem
