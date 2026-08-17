"""
falsifier.pipeline.contracts.disequilibrium
=============================================
Pydantic contracts for the disequilibrium pipeline stage.

  FastChemConfig           — FastChem/VULCAN configuration
  MUSCLESConfig            — MUSCLES stellar UV spectrum configuration
  ChemicalSpeciesProfile   — VMR profile + equilibrium benchmark per species
  GibbsMinimisationResult  — Gibbs free energy result at one T/P point
  SourceFluxRatio          — required source flux / max plausible abiotic flux
  DisequilibriumInput      — pointer to RetrieveOutput + chemistry config
  DisequilibriumOutput     — thermochemical screening results

Policy
------
This stage runs on a **curated subset of established planets only** — not
on candidates.  It emits no disposition.

``overall_disequilibrium_score`` is a screening metric only.  It does **not**
constitute a biosignature claim.  AGENTS.md Locked Claim: this project is not
a biosignature detector.  No exoplanet biosignature has ever been confirmed.

``DisequilibriumOutput`` deliberately has no ``disposition`` field.

``source_flux_ratio`` is the headline disequilibrium metric:
  required_source_flux / max_plausible_abiotic_flux
Both numerator and denominator carry units of W/m², propagated from
the VULCAN photochemical network and the MUSCLES stellar UV spectrum.

Exploratory status
------------------
This stage is exploratory and **not validated against ground truth**.
See README §Exploratory Modules for the explicit disclaimer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from .manifest import ArtifactRef, StageManifest, UnitedArray

__all__ = [
    "FastChemConfig",
    "MUSCLESConfig",
    "ChemicalSpeciesProfile",
    "GibbsMinimisationResult",
    "SourceFluxRatio",
    "DisequilibriumInput",
    "DisequilibriumOutput",
]


# ---------------------------------------------------------------------------
# MUSCLESConfig
# ---------------------------------------------------------------------------

class MUSCLESConfig(BaseModel):
    """
    Configuration for the MUSCLES stellar UV spectrum used as photochemical
    driver in the VULCAN network.

    MUSCLES (Measurements of the Ultraviolet Spectral Characteristics of
    Low-mass Exoplanetary Systems, France et al. 2016, ApJ 820, 89,
    DOI 10.3847/0004-637X/820/2/89) provides panchromatic UV-to-IR spectra
    for a sample of M- and K-dwarf host stars.

    ``spectral_type_key`` is the MUSCLES archive key, e.g. ``"GJ1132"``.
    If no exact match is available the nearest analogue in the MUSCLES survey
    is used and recorded in ``analogue_used``.
    """

    spectral_type_key: str
    """MUSCLES archive identifier for the host star, e.g. ``"GJ1132"``."""

    muscles_doi: str
    """
    DOI of the MUSCLES HST programme paper the spectrum was drawn from.
    Minimum: ``"10.3847/0004-637X/820/2/89"`` (France et al. 2016).
    """

    analogue_used: str | None = None
    """
    If no exact match exists in the MUSCLES survey, the identifier of the
    spectral analogue used instead.  ``None`` if the target star itself has a
    committed MUSCLES spectrum.
    """

    uv_band_lower_nm: float
    """Lower wavelength boundary of the UV band used in photolysis, in nm."""

    uv_band_upper_nm: float
    """Upper wavelength boundary of the UV band used in photolysis, in nm."""

    @field_validator("muscles_doi")
    @classmethod
    def _doi_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("MUSCLESConfig.muscles_doi must be non-empty")
        return v

    @field_validator("spectral_type_key")
    @classmethod
    def _key_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("MUSCLESConfig.spectral_type_key must be non-empty")
        return v


# ---------------------------------------------------------------------------
# FastChemConfig
# ---------------------------------------------------------------------------

class FastChemConfig(BaseModel):
    """
    Configuration for the FastChem / VULCAN chemistry calculation.

    ``metallicity_solar`` and ``c_to_o_ratio`` are dimensionless scalar
    configuration parameters — bare floats are acceptable.
    """

    temperature_pressure_profile_source: str
    """
    Source of the T/P profile.  Must be one of ``"retrieval"``,
    ``"parametric"``, or ``"gcm"``.  ``"retrieval"`` uses the posterior
    median T/P profile from the ``RetrieveOutput``; ``"parametric"`` uses the
    analytic Guillot (2010) profile; ``"gcm"`` reads from an external file.
    """

    included_species: list[str]
    """
    Chemical formula strings for the species to compute, e.g.
    ``["H2O", "CO2", "CH4"]``.  Non-empty.
    """

    metallicity_solar: float
    """
    Metallicity as a multiple of solar metallicity [M/H].  Dimensionless.
    Bare float acceptable — scalar configuration parameter, not a physical
    array crossing module boundaries.
    """

    c_to_o_ratio: float
    """
    Carbon-to-oxygen ratio.  Dimensionless; must be > 0.0.
    Solar value ≈ 0.55.
    """

    @model_validator(mode="after")
    def _species_nonempty(self) -> "FastChemConfig":
        if len(self.included_species) == 0:
            raise ValueError(
                "FastChemConfig.included_species must contain at least one species"
            )
        return self

    @field_validator("c_to_o_ratio")
    @classmethod
    def _cto_positive(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(
                f"FastChemConfig.c_to_o_ratio must be > 0.0, got {v}"
            )
        return v

    @field_validator("temperature_pressure_profile_source")
    @classmethod
    def _tp_source_valid(cls, v: str) -> str:
        allowed = {"retrieval", "parametric", "gcm"}
        if v not in allowed:
            raise ValueError(
                f"FastChemConfig.temperature_pressure_profile_source must be one of "
                f"{sorted(allowed)}, got '{v}'"
            )
        return v


# ---------------------------------------------------------------------------
# ChemicalSpeciesProfile
# ---------------------------------------------------------------------------

class ChemicalSpeciesProfile(BaseModel):
    """
    Volume mixing ratio profile for one chemical species, compared against
    the FastChem thermochemical equilibrium prediction.

    All three VMR/pressure arrays must have equal length.
    ``disequilibrium_metric`` is the integrated absolute log-ratio between
    the observed and equilibrium profiles — a dimensionless screening scalar.
    """

    species: str
    """Chemical formula, e.g. ``"H2O"`` or ``"CH4"``."""

    vmr_profile: UnitedArray
    """
    Retrieved volume mixing ratio vs pressure.  Unit is ``"dimensionless"``.
    """

    pressure: UnitedArray
    """Pressure grid.  Unit is ``"bar"``."""

    equilibrium_vmr_profile: UnitedArray
    """
    FastChem thermochemical equilibrium prediction at the same pressure grid.
    Unit is ``"dimensionless"``.
    """

    disequilibrium_metric: float
    """
    Integrated absolute log-ratio ∫ |log(VMR_obs / VMR_eq)| dP,
    normalised to the pressure range.  Dimensionless; always >= 0.0.
    Larger values indicate stronger departure from equilibrium.
    """

    @field_validator("pressure")
    @classmethod
    def _pressure_bar_unit(cls, v: UnitedArray) -> UnitedArray:
        if v.unit != "bar":
            raise ValueError(
                f"ChemicalSpeciesProfile.pressure unit must be 'bar'; got '{v.unit}'"
            )
        return v

    @field_validator("vmr_profile", "equilibrium_vmr_profile")
    @classmethod
    def _vmr_dimensionless_unit(cls, v: UnitedArray) -> UnitedArray:
        if v.unit != "dimensionless":
            raise ValueError(
                f"ChemicalSpeciesProfile VMR arrays must have unit 'dimensionless'; "
                f"got '{v.unit}'"
            )
        return v

    @field_validator("disequilibrium_metric")
    @classmethod
    def _metric_nonneg(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError(
                f"ChemicalSpeciesProfile.disequilibrium_metric must be >= 0.0, got {v}"
            )
        return v

    @model_validator(mode="after")
    def _arrays_equal_length(self) -> "ChemicalSpeciesProfile":
        n = len(self.pressure.values)
        errors: list[str] = []
        if len(self.vmr_profile.values) != n:
            errors.append(
                f"vmr_profile has {len(self.vmr_profile.values)} elements, "
                f"pressure has {n}"
            )
        if len(self.equilibrium_vmr_profile.values) != n:
            errors.append(
                f"equilibrium_vmr_profile has "
                f"{len(self.equilibrium_vmr_profile.values)} elements, "
                f"pressure has {n}"
            )
        if errors:
            raise ValueError(
                "ChemicalSpeciesProfile array length mismatch:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )
        return self


# ---------------------------------------------------------------------------
# GibbsMinimisationResult
# ---------------------------------------------------------------------------

class GibbsMinimisationResult(BaseModel):
    """
    Result of a Gibbs free energy minimisation at one temperature/pressure
    grid point.

    ``species_fractions`` maps species formula to mole fraction.  These are
    dimensionless ratios summing to 1 — bare floats are acceptable.
    """

    temperature: UnitedArray
    """Temperature at this grid point.  Single-element array; unit ``"K"``."""

    pressure: UnitedArray
    """Pressure at this grid point.  Single-element array; unit ``"bar"``."""

    species_fractions: dict[str, float]
    """
    Species formula → equilibrium mole fraction.  Dimensionless ratios.
    Should sum to approximately 1.0.
    """

    gibbs_free_energy: UnitedArray
    """
    Total Gibbs free energy at this T/P point.  Single-element array;
    unit ``"J / mol"``.
    """

    @field_validator("temperature")
    @classmethod
    def _temperature_unit(cls, v: UnitedArray) -> UnitedArray:
        if len(v.values) != 1:
            raise ValueError(
                f"GibbsMinimisationResult.temperature must be single-element; "
                f"got {len(v.values)} elements"
            )
        if v.unit != "K":
            raise ValueError(
                f"GibbsMinimisationResult.temperature unit must be 'K'; got '{v.unit}'"
            )
        return v

    @field_validator("pressure")
    @classmethod
    def _pressure_unit(cls, v: UnitedArray) -> UnitedArray:
        if len(v.values) != 1:
            raise ValueError(
                f"GibbsMinimisationResult.pressure must be single-element; "
                f"got {len(v.values)} elements"
            )
        if v.unit != "bar":
            raise ValueError(
                f"GibbsMinimisationResult.pressure unit must be 'bar'; got '{v.unit}'"
            )
        return v

    @field_validator("gibbs_free_energy")
    @classmethod
    def _gibbs_unit(cls, v: UnitedArray) -> UnitedArray:
        if len(v.values) != 1:
            raise ValueError(
                f"GibbsMinimisationResult.gibbs_free_energy must be single-element; "
                f"got {len(v.values)} elements"
            )
        if v.unit != "J / mol":
            raise ValueError(
                f"GibbsMinimisationResult.gibbs_free_energy unit must be 'J / mol'; "
                f"got '{v.unit}'"
            )
        return v


# ---------------------------------------------------------------------------
# SourceFluxRatio
# ---------------------------------------------------------------------------

class SourceFluxRatio(BaseModel):
    """
    Headline disequilibrium metric:
        required_source_flux / max_plausible_abiotic_flux

    ``required_source_flux`` is the photon/chemical energy flux needed to
    sustain the observed disequilibrium abundance of a target species above
    its FastChem thermochemical equilibrium value, computed from the VULCAN
    photochemical network driven by the MUSCLES stellar UV spectrum.

    ``max_plausible_abiotic_flux`` is the maximum flux the same species could
    receive from known abiotic processes (volcanism, lightning, UV
    photolysis of other species) as computed from the VULCAN network without
    any biotic flux term.

    A ratio >> 1 means an unaccounted-for source is required.  A ratio ≈ 1
    means the abiotic budget is sufficient.

    **This is a screening metric.  It does NOT constitute a biosignature
    claim.  No exoplanet biosignature has ever been confirmed.**

    All flux quantities carry units of W m⁻².  Uncertainty is propagated
    from the posterior samples of the VULCAN photochemical integration.
    """

    species: str
    """Chemical formula of the species this ratio describes, e.g. ``"CH4"``."""

    required_source_flux: UnitedArray
    """
    Required source flux to sustain observed abundance above equilibrium.
    Single-element array; unit ``"W / m2"``.
    """

    max_plausible_abiotic_flux: UnitedArray
    """
    Maximum abiotic source flux from the VULCAN network (no biotic term).
    Single-element array; unit ``"W / m2"``.  Always > 0.
    """

    ratio: float
    """
    required_source_flux / max_plausible_abiotic_flux.
    Dimensionless; always >= 0.
    Computed at construction time; must be consistent with the flux fields.
    """

    ratio_uncertainty: float
    """
    1-sigma uncertainty on ``ratio``, propagated from VULCAN posterior
    integration samples.  Always >= 0.
    """

    muscles_spectrum_doi: str
    """DOI of the MUSCLES spectrum used as photochemical driver."""

    vulcan_version: str
    """Version string of VULCAN used, e.g. ``"2.0"``."""

    @field_validator("required_source_flux", "max_plausible_abiotic_flux")
    @classmethod
    def _flux_unit(cls, v: UnitedArray) -> UnitedArray:
        if len(v.values) != 1:
            raise ValueError(
                "SourceFluxRatio flux fields must be single-element"
            )
        if v.unit != "W / m2":
            raise ValueError(
                f"SourceFluxRatio flux fields must have unit 'W / m2'; "
                f"got '{v.unit}'"
            )
        return v

    @field_validator("ratio", "ratio_uncertainty")
    @classmethod
    def _nonneg(cls, v: float, info) -> float:
        if v < 0.0:
            raise ValueError(
                f"SourceFluxRatio.{info.field_name} must be >= 0, got {v}"
            )
        return v

    @model_validator(mode="after")
    def _ratio_consistent(self) -> "SourceFluxRatio":
        abiotic = self.max_plausible_abiotic_flux.values[0]
        if abiotic <= 0.0:
            raise ValueError(
                "SourceFluxRatio.max_plausible_abiotic_flux must be > 0"
            )
        expected = self.required_source_flux.values[0] / abiotic
        if abs(expected - self.ratio) > 1e-6 * max(1.0, abs(expected)):
            raise ValueError(
                f"SourceFluxRatio.ratio ({self.ratio:.6g}) does not match "
                f"required_source_flux / max_plausible_abiotic_flux "
                f"({expected:.6g}).  Recompute."
            )
        return self


# ---------------------------------------------------------------------------
# DisequilibriumInput
# ---------------------------------------------------------------------------

class DisequilibriumInput(BaseModel):
    """
    Request parameters for one disequilibrium analysis run.

    This stage operates on **established planets only**.  The orchestrator is
    responsible for ensuring only confirmed planets are submitted here.
    """

    retrieve_artifact: ArtifactRef
    """Pointer to the serialised RetrieveOutput for this planet."""

    planet_name: str
    """
    Canonical planet name from the NASA Exoplanet Archive,
    e.g. ``"TRAPPIST-1 b"``.
    """

    planet_doi: str
    """
    DOI of the reference paper for this planet's bulk parameters,
    e.g. ``"10.1038/s41586-021-03394-8"``.  Non-empty.
    """

    fastchem_config: FastChemConfig
    """Full configuration for the FastChem/VULCAN chemistry calculation."""

    muscles_config: MUSCLESConfig
    """MUSCLES stellar UV spectrum configuration for VULCAN photochemistry."""

    pipeline_run_id: str
    """UUID shared across all stages in one pipeline execution."""

    @field_validator("planet_doi", "planet_name")
    @classmethod
    def _nonempty(cls, v: str, info) -> str:
        if not v.strip():
            raise ValueError(
                f"DisequilibriumInput.{info.field_name} must be non-empty"
            )
        return v.strip()


# ---------------------------------------------------------------------------
# DisequilibriumOutput — no disposition field
# ---------------------------------------------------------------------------

class DisequilibriumOutput(BaseModel):
    """
    Complete artifact produced by ``run_disequilibrium``.

    This model deliberately has **no** ``disposition`` field.  This stage
    performs thermochemical screening on established planets; it does not
    assign candidate status.

    ``overall_disequilibrium_score`` is a **screening metric only**.
    It does NOT constitute a biosignature claim.  No exoplanet biosignature
    has ever been confirmed.  (AGENTS.md Locked Claim)

    ``source_flux_ratios`` contains the headline metric per species:
    required_source_flux / max_plausible_abiotic_flux.  Values >> 1 flag
    species whose abundance cannot be explained by the known abiotic budget.

    **Exploratory**: this stage is not validated against ground truth.
    See README §Exploratory Modules.
    """

    input: DisequilibriumInput
    """Echo of the disequilibrium request."""

    planet_name: str
    """Canonical planet name propagated from ``input.planet_name``."""

    host_star_id: str
    """Canonical host star identifier."""

    species_profiles: list[ChemicalSpeciesProfile]
    """
    One ``ChemicalSpeciesProfile`` per species listed in
    ``input.fastchem_config.included_species``.  Length must equal
    ``len(input.fastchem_config.included_species)``.
    """

    gibbs_results: list[GibbsMinimisationResult]
    """
    Gibbs free energy minimisation results, one per T/P grid point used in
    the FastChem calculation.
    """

    source_flux_ratios: list[SourceFluxRatio]
    """
    One ``SourceFluxRatio`` per species in ``species_profiles``.
    Headline metric: required_source_flux / max_plausible_abiotic_flux.
    Carries explicit flux units (W m⁻²) and propagated uncertainty.
    Length must equal ``len(species_profiles)``.
    """

    overall_disequilibrium_score: float = Field(
        description=(
            "Screening metric only. Does not constitute a biosignature claim. "
            "Mean of disequilibrium_metric across all species in species_profiles. "
            "Dimensionless; always >= 0.0."
        )
    )

    manifest: StageManifest
    """
    Stage execution record.  Must include ``DatasetProvenance`` entries for
    the planet reference paper, the MUSCLES spectrum DOI, and any atmospheric
    model grid used.
    """

    artifact: ArtifactRef
    """Reference to this output's own serialised form on disk."""

    @model_validator(mode="after")
    def _species_count_matches_config(self) -> "DisequilibriumOutput":
        expected = len(self.input.fastchem_config.included_species)
        actual = len(self.species_profiles)
        if actual != expected:
            raise ValueError(
                f"DisequilibriumOutput.species_profiles has {actual} entries but "
                f"fastchem_config.included_species has {expected}.  "
                f"One ChemicalSpeciesProfile is required per included species."
            )
        if len(self.source_flux_ratios) != actual:
            raise ValueError(
                f"DisequilibriumOutput.source_flux_ratios has "
                f"{len(self.source_flux_ratios)} entries but species_profiles "
                f"has {actual}.  One SourceFluxRatio is required per species."
            )
        return self

    @model_validator(mode="after")
    def _all_metrics_nonneg(self) -> "DisequilibriumOutput":
        bad = [
            (p.species, p.disequilibrium_metric)
            for p in self.species_profiles
            if p.disequilibrium_metric < 0.0
        ]
        if bad:
            raise ValueError(
                f"DisequilibriumOutput: negative disequilibrium_metric found for "
                f"species: {bad}"
            )
        return self

    @field_validator("overall_disequilibrium_score")
    @classmethod
    def _score_nonneg(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError(
                f"DisequilibriumOutput.overall_disequilibrium_score must be >= 0.0, "
                f"got {v}"
            )
        return v
