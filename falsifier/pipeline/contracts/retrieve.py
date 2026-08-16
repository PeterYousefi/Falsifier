"""
falsifier.pipeline.contracts.retrieve
========================================
Pydantic contracts for the retrieve pipeline stage.

  RetrievalConfig   — atmospheric retrieval algorithm configuration
  RetrievedSpectrum — model transmission/emission spectrum from the retrieval
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
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from .manifest import ArtifactRef, StageManifest, UnitedArray

__all__ = [
    "RetrievalConfig",
    "RetrievedSpectrum",
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

    ``log_evidence`` is the natural-log Bayesian evidence (ln Z, nats).
    It is NOT log base 10.  Do not convert without updating the description.

    ``wall_time_cpu_hours`` is metadata, not a physical quantity — bare float
    is acceptable.
    """

    input: RetrieveInput
    """Echo of the retrieval request."""

    tce_id: str
    """TCE identifier propagated from the upstream ClassifyOutput."""

    host_star_id: str
    """Canonical target identifier propagated from upstream stages."""

    spectrum: RetrievedSpectrum
    """Best-fit model spectrum.  Always populated; never None."""

    posterior_artifact: ArtifactRef
    """
    Reference to the nested-sampling posterior file on disk (e.g. a
    MultiNest or dynesty output directory).  Always present.
    """

    log_evidence: float
    """
    Bayesian log-evidence ln Z in natural log units (nats).
    NOT log base 10.  Dimensionless scalar.
    """

    log_evidence_uncertainty: float
    """
    Uncertainty on ``log_evidence`` from the nested sampler.  Non-optional.
    Dimensionless scalar.
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
