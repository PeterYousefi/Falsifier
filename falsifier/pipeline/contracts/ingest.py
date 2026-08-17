"""
falsifier.pipeline.contracts.ingest
=====================================
Pydantic contracts for the ingest pipeline stage.

  IngestInput      — what the caller requests
  StellarParams    — Gaia DR3 stellar parameters for the host star
  LightCurveSegment — one sector/quarter of light curve data
  IngestOutput     — the complete artifact emitted by run_ingest
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .manifest import ArtifactRef, DatasetProvenance, StageManifest, UnitedArray

__all__ = [
    "IngestInput",
    "StellarParams",
    "LightCurveSegment",
    "IngestOutput",
]

# ---------------------------------------------------------------------------
# IngestInput
# ---------------------------------------------------------------------------

class IngestInput(BaseModel):
    """
    Request parameters for a single ingest run.

    ``target_id`` accepts both KIC and TIC identifiers — the stage body
    resolves which archive to query.  Use canonical forms:

      - Kepler : ``"KIC 11904151"``
      - TESS   : ``"TIC 261136679"``

    ``tic_id`` is accepted as an alias for ``target_id`` for backwards
    compatibility with golden test fixtures.

    ``pipeline_run_id`` is a UUID assigned by the orchestrator and propagated
    unchanged through every downstream stage so all artifacts from one run
    share a common identifier.
    """

    target_id: str = ""
    """
    Target identifier in canonical form, e.g. ``"KIC 11904151"`` or
    ``"TIC 261136679"``.  May be set via the ``tic_id`` alias.
    """

    tic_id: Optional[str] = Field(default=None, exclude=True)
    """
    Alias for ``target_id``.  Accepted for backwards compatibility with
    golden test fixtures that predate the ``target_id`` rename.
    """

    mission: Optional[Literal["Kepler", "K2", "TESS"]] = None
    """Mission whose archive to query.  Inferred from target_id prefix if absent."""

    author: Optional[str] = None
    """
    MAST pipeline author string, e.g. ``"Kepler"`` or ``"SPOC"``.
    Inferred from mission if absent.
    """

    cadence: Literal["short", "long", "fast"] = "long"
    """Cadence type: ``"long"`` (30-min), ``"short"`` (1-min), or ``"fast"`` (20-sec)."""

    sectors: list[int] | None = None
    """
    Explicit sector or quarter numbers.  ``None`` fetches all available.
    For Kepler, these are quarter numbers; for TESS/K2, sector numbers.
    """

    pipeline_run_id: str
    """UUID assigned at pipeline-run start; propagated to all downstream stages."""

    @model_validator(mode="before")
    @classmethod
    def _resolve_tic_id_alias(cls, values: dict) -> dict:
        """Accept ``tic_id`` as a synonym for ``target_id``."""
        if isinstance(values, dict):
            tic = values.get("tic_id")
            tid = values.get("target_id", "")
            if tic and not tid:
                values = dict(values)
                values["target_id"] = tic
        return values

    @field_validator("target_id")
    @classmethod
    def _target_id_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("IngestInput.target_id must be non-empty")
        return v.strip()


# ---------------------------------------------------------------------------
# StellarParams — Gaia DR3 host star parameters
# ---------------------------------------------------------------------------

class StellarParams(BaseModel):
    """
    Host star parameters from Gaia DR3.

    All physical quantities use ``UnitedArray`` (single-element arrays) so
    the unit string is always explicit and ``to_quantity()`` works uniformly.
    ``ruwe`` and ``parallax_over_error`` are dimensionless diagnostics and
    use bare floats; they are not physical quantities crossing module
    boundaries.
    """

    gaia_source_id: str
    """Gaia DR3 source identifier string."""

    ra_deg: float
    """Right ascension in degrees (J2000), read from Gaia DR3."""

    dec_deg: float
    """Declination in degrees (J2000), read from Gaia DR3."""

    ruwe: float
    """
    Renormalised Unit Weight Error.  Dimensionless.  Values > 1.4 indicate
    a possible unresolved binary or astrometric excess noise (``gaia_ruwe``
    vetting gate).
    """

    parallax_over_error: float
    """Parallax significance: parallax / parallax_error.  Dimensionless."""

    teff: UnitedArray
    """Effective temperature; expected unit ``"K"``."""

    teff_uncertainty: UnitedArray
    """Uncertainty on ``teff``; same unit as ``teff``."""

    radius: UnitedArray
    """Stellar radius; expected unit ``"solRad"``."""

    radius_uncertainty: UnitedArray
    """Uncertainty on ``radius``; same unit as ``radius``."""

    provenance: DatasetProvenance
    """
    Provenance of this record.  ``source_doi`` must be the Gaia DR3 catalog
    DOI: ``"10.1051/0004-6361/202243940"``.
    """


# ---------------------------------------------------------------------------
# LightCurveSegment
# ---------------------------------------------------------------------------

class LightCurveSegment(BaseModel):
    """
    One sector or quarter of calibrated light curve data.

    ``time_scale`` and ``time_format`` are **required fields with no defaults**.
    They are read from the FITS header (TIMESYS and TIMEUNIT / TIME_FMT) and
    must never be assumed.  Construction raises ``ValidationError`` if either
    is absent.

    Kepler headers: ``TIMESYS = 'TDB'``, ``TIMEUNIT = 'd'``, time column in
    BKJD (BJD − 2454833.0).

    TESS headers  : ``TIMESYS = 'TDB'``, ``TIMEUNIT = 'd'``, time column in
    BTJD (BJD − 2457000.0).

    The ``time.unit`` field on the ``UnitedArray`` carries the numeric time
    reference frame (``"btjd"`` or ``"bkjd"`` or ``"jd"``); ``time_scale``
    and ``time_format`` carry the astropy ``Time`` constructor keywords.
    """

    sector: int
    """Sector (TESS/K2) or quarter (Kepler) number."""

    time: UnitedArray
    """
    Barycentric time array.  ``unit`` is the time reference string read
    from the header, e.g. ``"btjd"`` or ``"bkjd"``.
    """

    time_scale: str
    """
    Astropy time scale, e.g. ``"tdb"``.  Read from FITS header TIMESYS.
    Required; no default.
    """

    time_format: str
    """
    Astropy time format, e.g. ``"btjd"`` or ``"bkjd"``.  Read from FITS
    header TIMEUNIT or TIME_FMT.  Required; no default.
    """

    flux: UnitedArray
    """
    Calibrated flux array.  Unit is ``"electron / s"`` for SAP,
    ``"dimensionless"`` for PDCSAP.  Read from FITS column TUNIT.
    """

    flux_err: UnitedArray
    """Flux uncertainty.  Same unit as ``flux``."""

    quality_flags: list[int]
    """
    Integer quality bitmask per cadence.  Not a physical quantity; raw
    ``list[int]`` is acceptable.
    """

    cadence_type: str
    """
    Human-readable cadence label, e.g. ``"long"``, ``"short"``.
    """

    centroid_col: UnitedArray | None = None
    """
    Column centroid per cadence.  Unit ``"pixel"`` or ``"pix"``.
    Present when the FITS file includes a CENTROID_COL column.
    """

    centroid_row: UnitedArray | None = None
    """Row centroid per cadence.  Same unit as ``centroid_col``."""

    @field_validator("time_scale")
    @classmethod
    def _time_scale_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "LightCurveSegment.time_scale must be non-empty.  "
                "Read it from the FITS header TIMESYS keyword; "
                "never assume a value."
            )
        return v.lower().strip()

    @field_validator("time_format")
    @classmethod
    def _time_format_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "LightCurveSegment.time_format must be non-empty.  "
                "Read it from the FITS header TIMEUNIT or TIME_FMT keyword; "
                "never assume a value."
            )
        return v.lower().strip()

    @model_validator(mode="after")
    def _arrays_equal_length(self) -> "LightCurveSegment":
        n = len(self.time.values)
        errors: list[str] = []
        if len(self.flux.values) != n:
            errors.append(
                f"flux has {len(self.flux.values)} elements, time has {n}"
            )
        if len(self.flux_err.values) != n:
            errors.append(
                f"flux_err has {len(self.flux_err.values)} elements, time has {n}"
            )
        if len(self.quality_flags) != n:
            errors.append(
                f"quality_flags has {len(self.quality_flags)} elements, time has {n}"
            )
        if self.centroid_col is not None and len(self.centroid_col.values) != n:
            errors.append(
                f"centroid_col has {len(self.centroid_col.values)} elements, time has {n}"
            )
        if self.centroid_row is not None and len(self.centroid_row.values) != n:
            errors.append(
                f"centroid_row has {len(self.centroid_row.values)} elements, time has {n}"
            )
        if errors:
            raise ValueError(
                "LightCurveSegment array length mismatch:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )
        return self


# ---------------------------------------------------------------------------
# IngestOutput
# ---------------------------------------------------------------------------

class IngestOutput(BaseModel):
    """
    Complete artifact produced by ``run_ingest``.

    ``input`` echoes the full request, enabling full reproducibility from
    the output alone.  ``host_star_id`` is the normalised canonical form of
    the target identifier and is used as the ML split group key (AGENTS.md
    Rule 4).
    """

    input: IngestInput
    """Echo of the ingest request."""

    segments: list[LightCurveSegment]
    """
    Light curve segments, one per sector/quarter fetched.  Must be
    non-empty.
    """

    host_star_id: str
    """
    Canonical target identifier used as the ML split group key.
    Normalised form: ``"KIC {integer}"`` or ``"TIC {integer}"``.
    """

    stellar_params: StellarParams | None = None
    """
    Gaia DR3 stellar parameters.  ``None`` if the Gaia query failed or was
    not requested.  The vet stage uses ``ruwe`` from this record for the
    ``gaia_ruwe`` vetting gate.
    """

    manifest: StageManifest
    """Stage execution record including provenance for all external data."""

    artifact: ArtifactRef
    """Reference to this output's own serialised form on disk."""

    @field_validator("segments")
    @classmethod
    def _segments_nonempty(cls, v: list[LightCurveSegment]) -> list[LightCurveSegment]:
        if not v:
            raise ValueError("IngestOutput.segments must contain at least one segment")
        return v
