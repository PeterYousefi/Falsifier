"""
falsifier.pipeline.contracts.manifest
======================================
Shared foundational models used by every stage contract.

  UnitedArray     — physical array + unit string as data (AGENTS.md Rule 2)
  DatasetProvenance — DOI + access date + row count (AGENTS.md Rule 3)
  ArtifactRef     — on-disk artifact pointer with SHA-256
  StageManifest   — per-stage execution record embedded in every *Output
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel, field_validator, model_validator

if TYPE_CHECKING:
    import astropy.units as u

# Register "ppm" as a custom astropy unit (1e-6, dimensionless) so that
# ``astropy.units.Unit("ppm")`` resolves correctly everywhere in the
# pipeline.  We do this at import time, and guard against double-registration.
try:
    import astropy.units as _au_init

    _ppm_unit = _au_init.def_unit(
        "ppm",
        represents=1e-6 * _au_init.dimensionless_unscaled,
        doc="Parts per million (1e-6)",
        prefixes=False,
    )
    _au_init.add_enabled_units([_ppm_unit])
    del _ppm_unit
except ValueError:
    # Already registered — safe to ignore.
    pass
finally:
    del _au_init

__all__ = [
    "UnitedArray",
    "DatasetProvenance",
    "ArtifactRef",
    "StageManifest",
]


# ---------------------------------------------------------------------------
# UnitedArray
# ---------------------------------------------------------------------------

class UnitedArray(BaseModel):
    """
    A physical array whose unit is stored as data, not metadata.

    ``unit`` is passed verbatim to ``astropy.units.Unit()``.  It must be a
    non-empty string that astropy can parse.  It is *not* a free-text
    description field.

    Examples of valid ``unit`` strings::

        "electron / s"   "day"   "ppm"   "dimensionless"   "btjd"   "K"

    Use ``to_quantity()`` as the only approved path from a ``UnitedArray``
    to an ``astropy.units.Quantity`` inside stage bodies.
    """

    values: list[float]
    unit: str

    @field_validator("values")
    @classmethod
    def _values_nonempty(cls, v: list[float]) -> list[float]:
        if len(v) < 1:
            raise ValueError("UnitedArray.values must contain at least one element")
        return v

    @field_validator("unit")
    @classmethod
    def _unit_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("UnitedArray.unit must be a non-empty string")
        return v

    def to_quantity(self):  # -> astropy.units.Quantity
        """
        Return ``np.array(self.values) * astropy.units.Unit(self.unit)``.

        Time-reference frame strings (``"bkjd"``, ``"btjd"``, ``"jd"``,
        ``"mjd"``, ``"bjd"``) and ``"dimensionless"`` are not SI units that
        astropy can parse.  For those the values are returned as a dimensionless
        ``Quantity``; callers extract ``q.value`` and then construct
        ``astropy.time.Time(q.value, format=…, scale=…)`` themselves.
        """
        import astropy.units as _u

        # Units that are time-reference frame identifiers or pipeline-internal
        # labels rather than physical SI units parseable by astropy.
        _TIME_REF_UNITS = frozenset({
            "bkjd", "btjd", "bjd", "jd", "mjd", "hjd",
        })
        _DIMENSIONLESS_LABELS = frozenset({
            "dimensionless", "dimensionless_unscaled", "",
        })

        unit_lower = self.unit.lower().strip()
        if unit_lower in _TIME_REF_UNITS or unit_lower in _DIMENSIONLESS_LABELS:
            return np.array(self.values, dtype=np.float64) * _u.dimensionless_unscaled
        try:
            return np.array(self.values, dtype=np.float64) * _u.Unit(self.unit)
        except ValueError:
            # Unknown unit string — fall back to dimensionless so callers
            # can still extract .value without crashing.
            return np.array(self.values, dtype=np.float64) * _u.dimensionless_unscaled

    @classmethod
    def from_quantity(cls, q) -> "UnitedArray":  # q: astropy.units.Quantity
        """Construct from an ``astropy.units.Quantity``."""
        return cls(values=np.asarray(q.value).tolist(), unit=str(q.unit))


# ---------------------------------------------------------------------------
# DatasetProvenance
# ---------------------------------------------------------------------------

class DatasetProvenance(BaseModel):
    """
    Provenance record for one external dataset consumed by a pipeline stage.

    Required by AGENTS.md Rule 3: every ingested dataset records source DOI,
    access date, and row count in its manifest.
    """

    source_doi: str
    """Citable DOI of the originating dataset or paper, e.g. ``"10.26133/NEA12"``."""

    access_date: datetime.date
    """ISO-8601 date on which the data was fetched from the remote service."""

    row_count: int
    """Number of rows (cadences / rows / records) in the artifact as ingested."""

    description: str
    """Human-readable one-line label, e.g. ``"Kepler Q3 long-cadence, KIC 11904151"``."""

    source_url: str = ""
    """
    Full URL or MAST URI of the retrieved resource.
    Empty string is permitted for catalog tables where no single URL applies,
    but the provenance-completeness test will flag absent URLs on FITS files.
    """

    @field_validator("source_doi")
    @classmethod
    def _doi_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("DatasetProvenance.source_doi must be non-empty")
        return v

    @field_validator("row_count")
    @classmethod
    def _row_count_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"DatasetProvenance.row_count must be >= 1, got {v}")
        return v


# ---------------------------------------------------------------------------
# ArtifactRef
# ---------------------------------------------------------------------------

class ArtifactRef(BaseModel):
    """
    Pointer to a pipeline artifact serialised on disk.

    ``sha256`` is the hex digest of the file at write time.  Readers must
    verify it before deserialising (see ``falsifier.pipeline.io``).
    """

    path: Path
    """Absolute path to the serialised artifact file."""

    sha256: str
    """SHA-256 hex digest of the file bytes at write time."""

    stage: str
    """Name of the pipeline stage that produced this artifact, e.g. ``"ingest"``."""

    pipeline_run_id: str
    """UUID shared across all stages in a single pipeline execution."""


# ---------------------------------------------------------------------------
# StageManifest
# ---------------------------------------------------------------------------

class StageManifest(BaseModel):
    """
    Per-stage execution record, embedded in every ``*Output`` model.

    ``input_hash`` is the SHA-256 of the serialised upstream output JSON.
    A cache hit is detected by comparing this hash against stored artifacts —
    if they match, the stage body can be skipped.
    """

    stage: str
    """Name of this stage, e.g. ``"ingest"``."""

    code_version: str
    """Value of ``falsifier.__version__`` at execution time."""

    input_hash: str
    """SHA-256 hex digest of the serialised upstream *Output JSON."""

    wall_time_seconds: float
    """Elapsed wall-clock time for the stage body, in seconds."""

    provenance: list[DatasetProvenance]
    """
    One entry per external dataset consumed by this stage.
    Empty list is permitted only for pure-compute stages that touch no
    external data.
    """

    artifact: ArtifactRef
    """Reference to this stage's own serialised output on disk."""
