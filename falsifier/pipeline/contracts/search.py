"""
falsifier.pipeline.contracts.search
=====================================
Pydantic contracts for the search pipeline stage.

  SearchInput  — pointer to a DetrendOutput artifact + search configuration
  TCE          — one Threshold Crossing Event found by TLS
  SearchOutput — the list of TCEs emitted by run_search

Transit search algorithm
------------------------
The search stage uses ``transitleastsquares`` (TLS, Hippke & Heller 2019,
DOI 10.1051/0004-6361/201834672).  TLS fits a **limb-darkened transit
profile** (not a box, not a trapezoid) and returns a Signal Detection
Efficiency (SDE) rather than a power spectrum.  It is **not BLS**
(Box-fitting Least Squares).  This distinction matters: TLS has higher
sensitivity to shallow transits because the template matches the physical
transit shape.

Policy
------
No disposition is assigned here.  ``TCE`` carries TLS signal statistics only.
Disposition is computed exclusively in the vet stage from ``VetOutput``.

``period_uncertainty`` on every ``TCE`` is non-optional.  AGENTS.md requires
explicit uncertainty over point estimates.

``snr_threshold`` is a bare ``float`` because it is a dimensionless
configuration constant, not a physical result crossing a module boundary.
Similarly, ``sde``, ``snr``, and ``odd_even_mismatch`` are dimensionless
TLS diagnostic scalars — bare floats are acceptable.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

from .manifest import ArtifactRef, StageManifest, UnitedArray

__all__ = [
    "SearchInput",
    "TCE",
    "SearchOutput",
]


# ---------------------------------------------------------------------------
# SearchInput
# ---------------------------------------------------------------------------

class SearchInput(BaseModel):
    """
    Request parameters for a single search run.

    ``detrend_artifact`` points to a committed ``DetrendOutput`` on disk.
    """

    detrend_artifact: ArtifactRef
    """Pointer to the serialised DetrendOutput produced by run_detrend."""

    period_min: UnitedArray
    """
    Minimum trial period.  Single-element array; unit must be ``"d"`` or
    ``"day"``.
    """

    period_max: UnitedArray
    """
    Maximum trial period.  Single-element array; unit must be ``"d"`` or
    ``"day"``.  Must be > ``period_min``.
    """

    snr_threshold: float
    """
    Minimum Signal-to-Noise Ratio for a TCE to be reported.  Dimensionless
    scalar configuration constant.  A bare float is acceptable here because
    this is a user-supplied threshold, not a physical result.
    """

    pipeline_run_id: str
    """UUID shared across all stages in one pipeline execution."""

    @field_validator("period_min", "period_max")
    @classmethod
    def _single_element_day_unit(cls, v: UnitedArray) -> UnitedArray:
        if len(v.values) != 1:
            raise ValueError(
                f"SearchInput period arrays must be single-element; "
                f"got {len(v.values)} elements"
            )
        if v.unit not in ("d", "day"):
            raise ValueError(
                f"SearchInput period arrays must have unit 'd' or 'day'; "
                f"got '{v.unit}'"
            )
        return v

    @model_validator(mode="after")
    def _period_min_lt_max(self) -> "SearchInput":
        if self.period_min.values[0] >= self.period_max.values[0]:
            raise ValueError(
                f"SearchInput.period_min ({self.period_min.values[0]} "
                f"{self.period_min.unit}) must be < period_max "
                f"({self.period_max.values[0]} {self.period_max.unit})"
            )
        return self


# ---------------------------------------------------------------------------
# TCE — Threshold Crossing Event
# ---------------------------------------------------------------------------

class TCE(BaseModel):
    """
    One Threshold Crossing Event detected by ``transitleastsquares``.

    All physical arrays use ``UnitedArray`` with explicit unit strings.
    ``sde``, ``snr``, and ``odd_even_mismatch`` are dimensionless TLS
    diagnostics — bare floats are acceptable.

    ``period_uncertainty`` is mandatory.  An unknown period uncertainty is
    a correctness failure, not optional metadata.
    """

    tce_id: str
    """
    Unique identifier: ``"{host_star_id}-{index:02d}"``.
    Assigned by the search stage based on detection order (highest SDE first).
    """

    period: UnitedArray
    """Orbital period.  Single-element array; unit ``"d"`` or ``"day"``."""

    period_uncertainty: UnitedArray
    """
    Uncertainty on ``period``.  Single-element array; same unit as ``period``.
    Non-optional — AGENTS.md requires explicit uncertainty over point estimates.
    """

    epoch: UnitedArray
    """
    Transit epoch (time of first transit centre).  Single-element array;
    unit ``"jd"`` or ``"btjd"`` or ``"bkjd"``.
    """

    duration: UnitedArray
    """Transit duration.  Single-element array; unit ``"h"`` or ``"hour"``."""

    depth: UnitedArray
    """Transit depth.  Single-element array; unit ``"ppm"``."""

    sde: float
    """Signal Detection Efficiency from TLS.  Dimensionless diagnostic."""

    snr: float
    """Signal-to-Noise Ratio from TLS.  Dimensionless diagnostic."""

    odd_even_mismatch: float
    """
    TLS odd/even depth mismatch statistic.  Dimensionless; large values
    indicate asymmetric depths consistent with an eclipsing binary.
    """

    secondary_eclipse_depth: Optional[UnitedArray] = None
    """
    Depth of the strongest secondary eclipse peak, if any was found.
    Single-element array; unit ``"ppm"``.  ``None`` if no secondary signal
    was detected above the search threshold.
    """

    @field_validator("period", "period_uncertainty")
    @classmethod
    def _period_day_unit(cls, v: UnitedArray) -> UnitedArray:
        if len(v.values) != 1:
            raise ValueError(
                f"TCE period arrays must be single-element; got {len(v.values)} elements"
            )
        if v.unit not in ("d", "day"):
            raise ValueError(
                f"TCE period arrays must have unit 'd' or 'day'; got '{v.unit}'"
            )
        return v

    @field_validator("duration")
    @classmethod
    def _duration_hour_unit(cls, v: UnitedArray) -> UnitedArray:
        if len(v.values) != 1:
            raise ValueError(
                f"TCE.duration must be single-element; got {len(v.values)} elements"
            )
        if v.unit not in ("h", "hour"):
            raise ValueError(
                f"TCE.duration must have unit 'h' or 'hour'; got '{v.unit}'"
            )
        return v

    @field_validator("depth")
    @classmethod
    def _depth_ppm_unit(cls, v: UnitedArray) -> UnitedArray:
        if len(v.values) != 1:
            raise ValueError(
                f"TCE.depth must be single-element; got {len(v.values)} elements"
            )
        if v.unit != "ppm":
            raise ValueError(
                f"TCE.depth must have unit 'ppm'; got '{v.unit}'"
            )
        return v


# ---------------------------------------------------------------------------
# SearchOutput
# ---------------------------------------------------------------------------

class SearchOutput(BaseModel):
    """
    Complete artifact produced by ``run_search``.

    ``tces`` may be empty — no significant signals is a valid outcome for a
    quiet star.  ``tls_version`` records the exact library version used so
    results can be reproduced with the same TLS release.
    """

    input: SearchInput
    """Echo of the search request."""

    tces: list[TCE]
    """
    Detected Threshold Crossing Events, sorted by SDE descending.
    May be empty.
    """

    host_star_id: str
    """
    Canonical target identifier propagated from ``DetrendOutput``.
    Used as the ML split group key (AGENTS.md Rule 4).
    """

    tls_version: str
    """
    Version string of ``transitleastsquares`` used for this run, e.g.
    ``"1.0.31"``.  Read from ``transitleastsquares.__version__`` at runtime.
    """

    manifest: StageManifest
    """Stage execution record."""

    artifact: ArtifactRef
    """Reference to this output's own serialised form on disk."""
