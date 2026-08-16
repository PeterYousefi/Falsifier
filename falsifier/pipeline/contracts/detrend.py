"""
falsifier.pipeline.contracts.detrend
======================================
Pydantic contracts for the detrend pipeline stage.

  DetrendInput     — pointer to a serialised IngestOutput + detrending config
  DetrendedSegment — one systematics-corrected light curve sector/quarter
  DetrendOutput    — the complete artifact emitted by run_detrend

Policy
------
``DetrendInput`` holds an ``ArtifactRef`` to the upstream ``IngestOutput``,
not the object itself.  This means any stage can be re-run in isolation by
pointing at the committed artifact on disk.

``time_scale`` and ``time_format`` are propagated from ``LightCurveSegment``
with the same *required, no defaults* contract: construction raises
``ValidationError`` if either is absent.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from .manifest import ArtifactRef, StageManifest, UnitedArray

__all__ = [
    "DetrendInput",
    "DetrendedSegment",
    "DetrendOutput",
]


# ---------------------------------------------------------------------------
# DetrendInput
# ---------------------------------------------------------------------------

class DetrendInput(BaseModel):
    """
    Request parameters for a single detrend run.

    ``ingest_artifact`` points to a committed ``IngestOutput`` on disk.
    The stage body reads that artifact, not an in-memory object.
    """

    ingest_artifact: ArtifactRef
    """Pointer to the serialised IngestOutput produced by run_ingest."""

    method: Literal["biweight", "lowess", "gp", "cofiam"]
    """
    Detrending algorithm.  ``"biweight"`` is the wotan default and the
    recommended starting point for Kepler/TESS long-cadence data.
    """

    window_length: UnitedArray
    """
    Smoothing window length.  Single-element array; unit must be ``"d"`` or
    ``"day"``.  Passed verbatim to wotan's ``window_length`` parameter.
    """

    break_tolerance: UnitedArray
    """
    Maximum gap (in same units as ``window_length``) before the detrending
    is restarted.  Single-element array; unit must be ``"d"`` or ``"day"``.
    """

    pipeline_run_id: str
    """UUID shared across all stages in one pipeline execution."""

    @field_validator("window_length", "break_tolerance")
    @classmethod
    def _single_element_day_unit(cls, v: UnitedArray) -> UnitedArray:
        if len(v.values) != 1:
            raise ValueError(
                f"DetrendInput time arrays must be single-element; "
                f"got {len(v.values)} elements"
            )
        if v.unit not in ("d", "day"):
            raise ValueError(
                f"DetrendInput time arrays must have unit 'd' or 'day'; "
                f"got '{v.unit}'"
            )
        return v


# ---------------------------------------------------------------------------
# DetrendedSegment
# ---------------------------------------------------------------------------

class DetrendedSegment(BaseModel):
    """
    One sector/quarter of systematics-corrected light curve data.

    ``time_scale`` and ``time_format`` are propagated unchanged from the
    upstream ``LightCurveSegment``.  They are **required fields with no
    defaults** — construction raises ``ValidationError`` if absent.

    ``flux`` is normalised relative flux (dimensionless).
    ``trend_flux`` is the fitted systematics trend in original flux units.
    """

    sector: int
    """Sector (TESS/K2) or quarter (Kepler) number."""

    time: UnitedArray
    """
    Barycentric time array propagated from ``LightCurveSegment``.
    ``unit`` is the time reference string, e.g. ``"btjd"`` or ``"bkjd"``.
    """

    time_scale: str
    """
    Astropy time scale, e.g. ``"tdb"``.  Propagated from upstream segment.
    Required; no default.
    """

    time_format: str
    """
    Astropy time format, e.g. ``"btjd"`` or ``"bkjd"``.  Propagated from
    upstream segment.  Required; no default.
    """

    flux: UnitedArray
    """
    Normalised relative flux after systematics removal.  Unit is
    ``"dimensionless"``.
    """

    flux_err: UnitedArray
    """Uncertainty on ``flux``.  Same unit as ``flux``."""

    trend_flux: UnitedArray
    """
    Fitted systematics trend in the original flux units before normalisation
    (e.g. ``"electron / s"`` for SAP).  Used for quality diagnostics.
    """

    quality_flags: list[int]
    """Integer quality bitmask per cadence, propagated from ingest."""

    @field_validator("time_scale")
    @classmethod
    def _time_scale_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "DetrendedSegment.time_scale must be non-empty.  "
                "Propagate it from the upstream LightCurveSegment; "
                "never assume a value."
            )
        return v.lower().strip()

    @field_validator("time_format")
    @classmethod
    def _time_format_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "DetrendedSegment.time_format must be non-empty.  "
                "Propagate it from the upstream LightCurveSegment; "
                "never assume a value."
            )
        return v.lower().strip()

    @model_validator(mode="after")
    def _arrays_equal_length(self) -> "DetrendedSegment":
        n = len(self.time.values)
        errors: list[str] = []
        for name, arr in [
            ("flux", self.flux),
            ("flux_err", self.flux_err),
            ("trend_flux", self.trend_flux),
        ]:
            if len(arr.values) != n:
                errors.append(
                    f"{name} has {len(arr.values)} elements, time has {n}"
                )
        if len(self.quality_flags) != n:
            errors.append(
                f"quality_flags has {len(self.quality_flags)} elements, time has {n}"
            )
        if errors:
            raise ValueError(
                "DetrendedSegment array length mismatch:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )
        return self


# ---------------------------------------------------------------------------
# DetrendOutput
# ---------------------------------------------------------------------------

class DetrendOutput(BaseModel):
    """
    Complete artifact produced by ``run_detrend``.

    ``detrending_method`` echoes ``input.method`` so downstream stages can
    assert which algorithm was used without re-reading the full input.
    """

    input: DetrendInput
    """Echo of the detrend request."""

    segments: list[DetrendedSegment]
    """
    Detrended light curve segments, one per sector/quarter.  Must be
    non-empty.
    """

    host_star_id: str
    """
    Canonical target identifier propagated from ``IngestOutput``.
    Used as the ML split group key (AGENTS.md Rule 4).
    """

    detrending_method: str
    """Echoes ``input.method`` for quick inspection without unpacking input."""

    manifest: StageManifest
    """Stage execution record."""

    artifact: ArtifactRef
    """Reference to this output's own serialised form on disk."""

    @field_validator("segments")
    @classmethod
    def _segments_nonempty(cls, v: list[DetrendedSegment]) -> list[DetrendedSegment]:
        if not v:
            raise ValueError("DetrendOutput.segments must contain at least one segment")
        return v
