"""
falsifier.pipeline.contracts.retrieve
========================================
Pydantic contracts for the retrieve pipeline stage.

  RetrievalConfig   — atmospheric retrieval algorithm configuration
  RetrievedSpectrum — model transmission/emission spectrum from the retrieval
  SpotModelResult   — competing unocculted-stellar-spot model result
  BayesFactor       — ln Bayes factor comparing two nested-sampling runs
  PosteriorSummary  — marginalised posterior quantiles for one parameter
  RetrieveInput     — pointer to ClassifyOutput artifact + retrieval config
  RetrieveOutput    — complete retrieval result (synchronous, fully populated)

Policy
------
``RetrieveOutput`` is a **pure synchronous contract**.  It has no ``status``
field and no nullable result fields.  The function either returns a fully
populated ``RetrieveOutput`` or raises.  Job lifecycle management (queuing,
polling, retries, failure handling) belongs entirely in the API layer.

``log_evidence`` and ``log_evidence_uncertainty`` are bare floats because
they are dimensionless scalar log-probabilities, not physical arrays crossing
module boundaries.  The field description states which log base is used.

``JobStatus`` is deliberately absent from this module.  The API layer defines
its own job-state model independently.

Exploratory status
------------------
This stage is exploratory and **not validated against ground truth**.
See README §Exploratory Modules for the explicit disclaimer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .manifest import ArtifactRef, StageManifest, UnitedArray

__all__ = [
    "RetrievalConfig",
    "RetrievedSpectrum",
    "SpotModelResult",
    "BayesFactor",
    "PosteriorSummary",
    "RetrieveInput",
    "RetrieveOutput",
]


# ---------------------------------------------------------------------------
# RetrievalConfig
# ---------------------------------------------------------------------------

class RetrievalConfig(BaseModel):
    """
    Configuration for one atmospheric retrieval run.

    All fields are required so the retrieval is fully reproducible from the
    artifact alone.
    """

    retrieval_code: Literal["petitRADTRANS", "CHIMERA", "POSEIDON"]
    """Retrieval code to use.  Only these three are supported."""

    n_live_points: int
    """
    Number of nested-sampling live points.  Higher values give more accurate
    posteriors at proportionally higher CPU cost.  Strictly positive.
    """

    chemistry_scheme: Literal["equilibrium", "free", "disequilibrium"]
    """
    Chemistry model.  ``"free"`` retrieves individual species abundances
    independently; ``"equilibrium"`` uses FastChem; ``"disequilibrium"`` uses
    the VULCAN/FastChem hybrid implemented in the retrieve stage body.
    """

    pressure_grid_levels: int
    """
    Number of pressure levels in the atmospheric grid.  Strictly positive.
    Typical values: 30–100.
    """

    include_clouds: bool
    """Whether to include a parameterised cloud deck in the retrieval model."""

    @field_validator("n_live_points", "pressure_grid_levels")
    @classmethod
    def _strictly_positive(cls, v: int, info) -> int:
        if v <= 0:
            raise ValueError(
                f"RetrievalConfig.{info.field_name} must be > 0, got {v}"
            )
        return v


# ---------------------------------------------------------------------------
# RetrievedSpectrum
# ---------------------------------------------------------------------------

class SpotModelResult(BaseModel):
    """
    Competing model: unocculted stellar spots producing the observed
    transmission spectrum slope without any atmospheric absorption.

    The spot model is fitted simultaneously with the atmospheric retrieval so
    that the Bayes factor can compare them on equal footing using the same
    nested-sampling budget.

    ``spot_filling_factor`` is dimensionless (fraction of stellar disk covered
    by spots).  ``spot_temperature_contrast`` carries units of Kelvin.
    ``log_evidence`` is in natural-log units (nats), consistent with
    ``RetrieveOutput.log_evidence``.

    This is a screening tool.  A decisive Bayes factor against the spot model
    is necessary but not sufficient for an atmospheric detection claim.
    """

    spot_filling_factor: float
    """
    Fraction of the visible stellar disk covered by unocculted spots.
    Dimensionless; range [0, 1].
    """

    spot_temperature_contrast: UnitedArray
    """
    Temperature difference between the photosphere and the spots (T_phot - T_spot).
    Positive values mean spots are cooler than the photosphere.
    Single-element array; unit ``"K"``.
    """

    log_evidence: float
    """
    Natural-log Bayesian evidence ln Z for the spot-only model (nats).
    Directly comparable to ``RetrieveOutput.log_evidence``.
    """

    log_evidence_uncertainty: float
    """Uncertainty on ``log_evidence`` from the nested sampler (nats)."""

    n_live_points: int
    """Live points used for this competing model's nested-sampling run."""

    @field_validator("spot_filling_factor")
    @classmethod
    def _ff_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(
                f"SpotModelResult.spot_filling_factor must be in [0, 1], got {v}"
            )
        return v

    @field_validator("spot_temperature_contrast")
    @classmethod
    def _tcontrast_unit(cls, v: UnitedArray) -> UnitedArray:
        if len(v.values) != 1:
            raise ValueError(
                "SpotModelResult.spot_temperature_contrast must be single-element"
            )
        if v.unit != "K":
            raise ValueError(
                f"SpotModelResult.spot_temperature_contrast unit must be 'K'; "
                f"got '{v.unit}'"
            )
        return v

    @field_validator("n_live_points")
    @classmethod
    def _nlive_pos(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(
                f"SpotModelResult.n_live_points must be > 0, got {v}"
            )
        return v


class BayesFactor(BaseModel):
    """
    Natural-log Bayes factor comparing two nested-sampling model runs.

    ``ln_bayes_factor = ln_Z_model_a - ln_Z_model_b``

    Jeffreys (1961) scale:
      |ln B| < 1    — not worth mentioning
      1 ≤ |ln B| < 3 — substantial
      3 ≤ |ln B| < 5 — strong
      |ln B| ≥ 5    — decisive

    Positive values favour model_a over model_b.
    All values are in natural-log units (nats) — NOT log base 10.
    """

    model_a_name: str
    """Human-readable label for model A (the preferred/tested model)."""

    model_b_name: str
    """Human-readable label for model B (the null/competing model)."""

    ln_bayes_factor: float
    """
    ln Z_A − ln Z_B in natural-log units (nats).
    Positive: evidence favours model A.
    Negative: evidence favours model B.
    """

    ln_bayes_factor_uncertainty: float
    """
    Propagated uncertainty: sqrt(sigma_A^2 + sigma_B^2).
    Always non-negative.
    """

    jeffreys_strength: str
    """
    Qualitative label derived from |ln_bayes_factor|:
    'not_worth_mentioning', 'substantial', 'strong', or 'decisive'.
    """

    @field_validator("ln_bayes_factor_uncertainty")
    @classmethod
    def _unc_nonneg(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError(
                f"BayesFactor.ln_bayes_factor_uncertainty must be >= 0, got {v}"
            )
        return v

    @field_validator("jeffreys_strength")
    @classmethod
    def _strength_valid(cls, v: str) -> str:
        valid = {
            "not_worth_mentioning", "substantial", "strong", "decisive"
        }
        if v not in valid:
            raise ValueError(
                f"BayesFactor.jeffreys_strength must be one of {sorted(valid)}, "
                f"got '{v}'"
            )
        return v

    @classmethod
    def from_evidences(
        cls,
        model_a_name: str,
        model_b_name: str,
        ln_z_a: float,
        ln_z_a_unc: float,
        ln_z_b: float,
        ln_z_b_unc: float,
    ) -> "BayesFactor":
        """Construct from two log-evidence values and their uncertainties."""
        import math
        lnb = ln_z_a - ln_z_b
        unc = math.sqrt(ln_z_a_unc ** 2 + ln_z_b_unc ** 2)
        abs_lnb = abs(lnb)
        if abs_lnb < 1.0:
            strength = "not_worth_mentioning"
        elif abs_lnb < 3.0:
            strength = "substantial"
        elif abs_lnb < 5.0:
            strength = "strong"
        else:
            strength = "decisive"
        return cls(
            model_a_name=model_a_name,
            model_b_name=model_b_name,
            ln_bayes_factor=lnb,
            ln_bayes_factor_uncertainty=unc,
            jeffreys_strength=strength,
        )


class PosteriorSummary(BaseModel):
    """
    Marginalised posterior quantiles for one retrieval parameter.

    All three quantile values carry the same physical unit as the parameter.
    The median is the point estimate; q16 and q84 give the 1-sigma HPD interval.

    Physical parameters use ``UnitedArray``; dimensionless parameters (e.g.
    log-abundance ratios) use unit ``"dimensionless"``.
    """

    parameter_name: str
    """Canonical name as used by the retrieval code, e.g. ``"log_H2O"``."""

    median: UnitedArray
    """Posterior median.  Single-element array."""

    q16: UnitedArray
    """16th percentile (−1σ equivalent).  Single-element array; same unit."""

    q84: UnitedArray
    """84th percentile (+1σ equivalent).  Single-element array; same unit."""

    @model_validator(mode="after")
    def _quantiles_consistent(self) -> "PosteriorSummary":
        med = self.median.values[0]
        lo = self.q16.values[0]
        hi = self.q84.values[0]
        if not (lo <= med <= hi):
            raise ValueError(
                f"PosteriorSummary for {self.parameter_name!r}: "
                f"quantiles must satisfy q16 <= median <= q84, "
                f"got q16={lo}, median={med}, q84={hi}"
            )
        if self.median.unit != self.q16.unit or self.median.unit != self.q84.unit:
            raise ValueError(
                f"PosteriorSummary for {self.parameter_name!r}: "
                "median, q16, q84 must have the same unit"
            )
        return self


class RetrievedSpectrum(BaseModel):
    """
    Best-fit model transmission or emission spectrum from the retrieval.

    All three arrays must have equal length.  ``transit_depth_uncertainty``
    is non-optional — explicit uncertainty over point estimates (AGENTS.md).
    """

    wavelength: UnitedArray
    """
    Wavelength grid.  Unit must be ``"micron"`` or ``"um"``.
    """

    transit_depth: UnitedArray
    """Model transit depth at each wavelength.  Unit is ``"ppm"``."""

    transit_depth_uncertainty: UnitedArray
    """
    1-sigma uncertainty on ``transit_depth`` at each wavelength.
    Unit is ``"ppm"``.  Non-optional.
    """

    @field_validator("wavelength")
    @classmethod
    def _wavelength_unit(cls, v: UnitedArray) -> UnitedArray:
        if v.unit not in ("micron", "um"):
            raise ValueError(
                f"RetrievedSpectrum.wavelength unit must be 'micron' or 'um'; "
                f"got '{v.unit}'"
            )
        return v

    @field_validator("transit_depth", "transit_depth_uncertainty")
    @classmethod
    def _depth_ppm_unit(cls, v: UnitedArray) -> UnitedArray:
        if v.unit != "ppm":
            raise ValueError(
                f"RetrievedSpectrum depth arrays must have unit 'ppm'; "
                f"got '{v.unit}'"
            )
        return v

    @model_validator(mode="after")
    def _arrays_equal_length(self) -> "RetrievedSpectrum":
        n = len(self.wavelength.values)
        errors: list[str] = []
        if len(self.transit_depth.values) != n:
            errors.append(
                f"transit_depth has {len(self.transit_depth.values)} elements, "
                f"wavelength has {n}"
            )
        if len(self.transit_depth_uncertainty.values) != n:
            errors.append(
                f"transit_depth_uncertainty has "
                f"{len(self.transit_depth_uncertainty.values)} elements, "
                f"wavelength has {n}"
            )
        if errors:
            raise ValueError(
                "RetrievedSpectrum array length mismatch:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )
        return self


# ---------------------------------------------------------------------------
# RetrieveInput
# ---------------------------------------------------------------------------

class RetrieveInput(BaseModel):
    """
    Request parameters for one atmospheric retrieval run.

    The orchestrator is responsible for only submitting TCEs whose
    ``VetOutput.disposition`` is ``"candidate"`` or ``"candidate_with_caveats"``
    to this stage.  The pipeline contract does not enforce this gate — it is an
    orchestration policy, not a data invariant.
    """

    classify_artifact: ArtifactRef
    """Pointer to the serialised ClassifyOutput produced by run_classify."""

    retrieval_config: RetrievalConfig
    """Full configuration for this retrieval run."""

    pipeline_run_id: str
    """UUID shared across all stages in one pipeline execution."""


# ---------------------------------------------------------------------------
# RetrieveOutput — synchronous, fully populated, no status field
# ---------------------------------------------------------------------------

class RetrieveOutput(BaseModel):
    """
    Complete artifact produced by ``run_retrieve``.

    This model is **always fully populated** when returned.  There is no
    ``status`` field because the pipeline function either completes
    successfully and returns this model, or raises an exception.

    ``log_evidence`` is the natural-log Bayesian evidence (ln Z, nats)
    for the **atmospheric model** (petitRADTRANS).
    It is NOT log base 10.  Do not convert without updating the description.

    ``wall_time_cpu_hours`` is metadata, not a physical quantity — bare float
    is acceptable.

    **Exploratory**: this stage is not validated against ground truth.
    See README §Exploratory Modules.
    """

    input: RetrieveInput
    """Echo of the retrieval request."""

    tce_id: str
    """TCE identifier propagated from the upstream ClassifyOutput."""

    host_star_id: str
    """Canonical target identifier propagated from upstream stages."""

    spectrum: RetrievedSpectrum
    """Best-fit model spectrum.  Always populated; never None."""

    posterior_summaries: list[PosteriorSummary] = Field(default_factory=list)
    """
    Marginalised posterior quantiles for each free parameter.
    One entry per parameter fitted by the nested sampler.
    Empty list if posterior was not marginalised (fast-inference path).
    """

    posterior_artifact: ArtifactRef
    """
    Reference to the nested-sampling posterior file on disk (dynesty
    output directory or .npz).  Always present.
    """

    log_evidence: float
    """
    Bayesian log-evidence ln Z for the atmospheric model, natural-log
    units (nats).  NOT log base 10.  Dimensionless scalar.
    """

    log_evidence_uncertainty: float
    """
    Uncertainty on ``log_evidence`` from the nested sampler.  Non-optional.
    Dimensionless scalar (nats).
    """

    spot_model: SpotModelResult
    """
    Competing unocculted-stellar-spot model, fitted with the same nested-
    sampling budget.  Used to compute ``bayes_factor_atm_vs_spot``.
    """

    bayes_factor_atm_vs_spot: BayesFactor
    """
    ln Bayes factor comparing the atmospheric model (model A) against the
    stellar-spot model (model B).  Positive: atmosphere preferred.
    Computed from ``log_evidence`` and ``spot_model.log_evidence``.
    """

    sampler: str = "dynesty"
    """
    Nested-sampling backend used.  Recorded for reproducibility.
    Supported values: ``"dynesty"``, ``"multinest"``.
    """

    wall_time_cpu_hours: float
    """
    Elapsed CPU time for this retrieval run in hours.  Metadata; bare float
    is acceptable (not a physical quantity).
    """

    manifest: StageManifest
    """
    Stage execution record.  Must include ``DatasetProvenance`` entries for
    any atmospheric opacity database or stellar model grid used.
    """

    artifact: ArtifactRef
    """Reference to this output's own serialised form on disk."""

    @field_validator("sampler")
    @classmethod
    def _sampler_valid(cls, v: str) -> str:
        allowed = {"dynesty", "multinest"}
        if v not in allowed:
            raise ValueError(
                f"RetrieveOutput.sampler must be one of {sorted(allowed)}, got '{v}'"
            )
        return v

    @model_validator(mode="after")
    def _bayes_factor_consistent(self) -> "RetrieveOutput":
        """Verify the Bayes factor matches the stored evidence values."""
        expected_lnb = self.log_evidence - self.spot_model.log_evidence
        actual_lnb = self.bayes_factor_atm_vs_spot.ln_bayes_factor
        if abs(expected_lnb - actual_lnb) > 1e-6:
            raise ValueError(
                f"RetrieveOutput.bayes_factor_atm_vs_spot.ln_bayes_factor "
                f"({actual_lnb:.6f}) does not match "
                f"log_evidence - spot_model.log_evidence "
                f"({expected_lnb:.6f}).  Recompute with BayesFactor.from_evidences()."
            )
        return self
