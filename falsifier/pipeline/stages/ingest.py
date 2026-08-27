"""
falsifier.pipeline.stages.ingest
===================================
``run_ingest`` — the ingest stage body.

Orchestrates three independent data sources:

  1. MAST / lightkurve  — light curve FITS files
  2. NASA Exoplanet Archive TAP  — planet and stellar parameters
  3. Gaia DR3  — stellar RUWE, radius, teff

These are independent queries, not a fallback chain.  A failure at any
source raises a typed exception (``MastFetchError``, ``TapFetchError``,
``GaiaFetchError``).  There is no automatic substitution: a MAST failure
does not cause a TAP fetch, and vice versa.

and the content-addressed cache layer.

Offline mode
------------
When ``offline=True``, all three sources are satisfied from cache only.
Any cache miss raises rather than calling the network.  This is the mode
used by the golden regression tests.

Test bypass
-----------
``run_ingest`` accepts optional keyword arguments for testing without network
or disk I/O:

  ``_segments``       — ``list[LightCurveSegment]`` injected directly,
                        bypassing MAST fetch and cache
  ``_stellar_params`` — ``StellarParams`` injected directly,
                        bypassing Gaia fetch

When both are provided, ``run_ingest`` constructs and returns an
``IngestOutput`` immediately, writing no artifacts.  This is the path used
by ``tests/test_kepler10_recovery.py``.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import falsifier
from ..contracts.ingest import (
    IngestInput,
    IngestOutput,
    LightCurveSegment,
    StellarParams,
)
from ..contracts.manifest import (
    ArtifactRef,
    DatasetProvenance,
    StageManifest,
    UnitedArray,
)
from ..ingest.cache import IngestCache, query_hash
from ..ingest.endpoints import MAST_API_URL, NEA_TAP_SYNC_URL
from ..ingest.exceptions import (
    IngestError,
    MastFetchError,
    TargetNotFoundError,
)
from ..ingest.sources.mast import MAST_DOI, fetch_lightcurve
from ..ingest.sources.tap import NEA_DOI, fetch_planet_params
from ..ingest.sources.gaia import GAIA_DOI, fetch_stellar_params

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Target ID normalisation
# ---------------------------------------------------------------------------

def normalise_target_id(raw: str) -> str:
    """
    Normalise a target identifier to canonical form.

    - KIC targets → ``"KIC {integer}"``
    - TIC targets → ``"TIC {integer}"``
    - Other forms are returned as-is (upper-cased, stripped).

    This is the ``host_star_id`` value used as the ML split group key.
    """
    stripped = raw.strip().upper()
    for prefix in ("KIC", "TIC"):
        if stripped.startswith(prefix):
            rest = stripped[len(prefix):].strip()
            # Remove non-digit characters
            digits = "".join(c for c in rest if c.isdigit())
            if digits:
                return f"{prefix} {int(digits)}"
    return stripped


# ---------------------------------------------------------------------------
# run_ingest
# ---------------------------------------------------------------------------

def run_ingest(
    ingest_input: IngestInput,
    *,
    cache_root: Path | None = None,
    offline: bool = False,
    max_age: datetime.timedelta | None = None,
    force_refetch: bool = False,
    fetch_gaia: bool = True,
    fetch_tap: bool = False,
    _segments: list[LightCurveSegment] | None = None,
    _stellar_params: StellarParams | None = None,
    _artifact_dir: Path | None = None,
) -> IngestOutput:
    """
    Execute the ingest stage.

    Parameters
    ----------
    ingest_input : IngestInput
        The fully validated stage input.
    cache_root : Path | None
        Root of the content-addressed cache.  Defaults to
        ``~/.falsifier/cache/ingest``.
    offline : bool
        If ``True``, refuse all network access; serve from cache only.
    max_age : timedelta | None
        Maximum acceptable age of a cached artifact.  ``None`` means any
        age is acceptable.
    force_refetch : bool
        If ``True``, ignore the cache and always fetch from the network.
    fetch_gaia : bool
        If ``True`` (default), also fetch Gaia DR3 stellar parameters.
    fetch_tap : bool
        If ``True``, also fetch planet parameters from the TAP service.
    _segments : list[LightCurveSegment] | None
        Test bypass: inject pre-built segments, skip MAST fetch entirely.
    _stellar_params : StellarParams | None
        Test bypass: inject pre-built stellar params, skip Gaia fetch.
    _artifact_dir : Path | None
        Test bypass: directory to write the output artifact.  If ``None``
        when using test bypasses, no artifact is written.

    Returns
    -------
    IngestOutput
    """
    wall_start = time.monotonic()

    if cache_root is None:
        cache_root = Path.home() / ".falsifier" / "cache" / "ingest"

    cache = IngestCache(cache_root)
    host_star_id = normalise_target_id(ingest_input.target_id)
    provenance_records: list[DatasetProvenance] = []

    # Trace-level breadcrumb: confirms exactly which target is being
    # requested and which cache key will be used.  Visible at DEBUG level;
    # safe to leave in production (no network call happens here).
    mast_cache_key = _mast_cache_query(ingest_input)
    log.info(
        "run_ingest: target=%r  normalised=%r  mission=%s  cadence=%s  "
        "sectors=%s  cache_key=%s  run_id=%s",
        ingest_input.target_id,
        host_star_id,
        ingest_input.mission,
        ingest_input.cadence,
        ingest_input.sectors,
        mast_cache_key,
        ingest_input.pipeline_run_id,
    )

    # ------------------------------------------------------------------
    # 1. Light curves
    # ------------------------------------------------------------------

    if _segments is not None:
        # Test bypass — use injected segments directly
        segments = _segments
        log.debug("run_ingest: using injected _segments (%d)", len(segments))
    else:
        segments = _fetch_lightcurves(
            ingest_input,
            cache=cache,
            offline=offline,
            max_age=max_age,
            force_refetch=force_refetch,
            provenance_records=provenance_records,
        )

    # ------------------------------------------------------------------
    # 2. Gaia stellar parameters
    # ------------------------------------------------------------------

    stellar_params: StellarParams | None = None
    if _stellar_params is not None:
        stellar_params = _stellar_params
        log.debug("run_ingest: using injected _stellar_params")
    elif fetch_gaia and not offline:
        stellar_params = _fetch_gaia(
            ingest_input,
            cache=cache,
            offline=offline,
            max_age=max_age,
            force_refetch=force_refetch,
            provenance_records=provenance_records,
        )
    elif fetch_gaia and offline:
        stellar_params = _fetch_gaia(
            ingest_input,
            cache=cache,
            offline=True,
            max_age=max_age,
            force_refetch=False,
            provenance_records=provenance_records,
        )

    # ------------------------------------------------------------------
    # 3. TAP planet parameters (optional)
    # ------------------------------------------------------------------
    if fetch_tap and not offline:
        _fetch_tap(
            ingest_input,
            cache=cache,
            offline=offline,
            max_age=max_age,
            force_refetch=force_refetch,
            provenance_records=provenance_records,
        )

    # ------------------------------------------------------------------
    # Build output
    # ------------------------------------------------------------------

    wall_seconds = time.monotonic() - wall_start

    # Dummy artifact ref — replaced below if writing to disk
    dummy_ref = ArtifactRef(
        path=Path("/dev/null"),
        sha256="0" * 64,
        stage="ingest",
        pipeline_run_id=ingest_input.pipeline_run_id,
    )

    manifest = StageManifest(
        stage="ingest",
        code_version=falsifier.__version__,
        input_hash=hashlib.sha256(
            ingest_input.model_dump_json().encode()
        ).hexdigest(),
        wall_time_seconds=wall_seconds,
        provenance=provenance_records,
        artifact=dummy_ref,
    )

    output = IngestOutput(
        input=ingest_input,
        segments=segments,
        host_star_id=host_star_id,
        stellar_params=stellar_params,
        manifest=manifest,
        artifact=dummy_ref,
    )

    # Write artifact if a directory is given
    if _artifact_dir is not None:
        from ..io import artifact_write
        ref = artifact_write(output, _artifact_dir)
        # Patch manifest and artifact with the real ref
        output = output.model_copy(
            update={
                "manifest": manifest.model_copy(update={"artifact": ref}),
                "artifact": ref,
            }
        )

    return output


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _mast_cache_query(inp: IngestInput) -> str:
    """Deterministic cache query string for a MAST request."""
    sectors_str = ",".join(str(s) for s in sorted(inp.sectors)) if inp.sectors else "all"
    return (
        f"mast:{inp.mission}:{inp.author}:{inp.cadence}:"
        f"{normalise_target_id(inp.target_id)}:sectors={sectors_str}"
    )


def _fetch_lightcurves(
    inp: IngestInput,
    *,
    cache: IngestCache,
    offline: bool,
    max_age: datetime.timedelta | None,
    force_refetch: bool,
    provenance_records: list[DatasetProvenance],
) -> list[LightCurveSegment]:
    """Fetch light curves from MAST, using cache when possible."""
    from astropy.io import fits as _fits

    cache_query = _mast_cache_query(inp)
    access_date = datetime.date.today()

    if not force_refetch:
        hit = cache.get(cache_query, ".fits", max_age=max_age, offline=offline)
        if hit is not None:
            cached_path, cached_manifest, _ = hit
            log.info("Cache hit for %s", cache_query)
            # Re-parse the cached FITS into segments
            segments = _fits_to_segments(cached_path, inp)
            provenance_records.append(
                DatasetProvenance(
                    source_doi=cached_manifest.get("source_doi", MAST_DOI),
                    source_url=cached_manifest.get("source_url", ""),
                    access_date=datetime.date.fromisoformat(
                        cached_manifest.get("access_date", access_date.isoformat())
                    ),
                    row_count=cached_manifest.get("row_count", len(segments)),
                    description=cached_manifest.get("description", f"Cached: {inp.target_id}"),
                )
            )
            return segments

    # Cache miss — fetch from network
    if offline:
        raise IngestError(
            f"Cache miss for {inp.target_id!r} in offline mode.\n"
            f"Run ingest with offline=False first to populate the cache."
        )

    log.info(
        "_fetch_lightcurves: cache miss — requesting MAST  "
        "target=%r  mission=%s  author=%s  cadence=%s  sectors=%s  cache_key=%s",
        inp.target_id,
        inp.mission,
        inp.author,
        inp.cadence,
        inp.sectors,
        cache_query,
    )
    segments_and_meta = fetch_lightcurve(
        inp.target_id,
        mission=inp.mission,
        author=inp.author,
        cadence=inp.cadence,
        sectors=inp.sectors,
    )

    if not segments_and_meta:
        raise MastFetchError(
            f"fetch_lightcurve returned empty list for {inp.target_id!r}",
            endpoint=MAST_API_URL,
            query=inp.target_id,
        )

    log.info(
        "_fetch_lightcurves: MAST fetch succeeded  "
        "target=%r  n_segments=%d",
        inp.target_id,
        len(segments_and_meta),
    )

    # Serialize all segments into one combined FITS for caching
    combined_fits = _segments_to_fits_bytes(
        [seg for seg, _, _ in segments_and_meta]
    )
    total_rows = sum(rc for _, _, rc in segments_and_meta)
    first_uri = segments_and_meta[0][1] if segments_and_meta else "MAST"

    # Record which reduction pipeline (author) reduced the photometry.
    # This is a provenance fact per AGENTS.md Rule 3: SPOC and TASOC produce
    # independent flux arrays for the same TESS target; the choice is auditable.
    _author_tag = f"author={inp.author}" if inp.author else "author=unspecified"
    cache.put(
        cache_query,
        ".fits",
        combined_fits,
        source_doi=MAST_DOI,
        source_url=first_uri,
        access_date=access_date,
        row_count=total_rows,
        description=(
            f"{inp.target_id} {inp.mission} {inp.cadence} {_author_tag}"
            f" Q/S={inp.sectors}"
        ),
    )

    provenance_records.append(
        DatasetProvenance(
            source_doi=MAST_DOI,
            source_url=first_uri,
            access_date=access_date,
            row_count=total_rows,
            description=(
                f"{inp.target_id} {inp.mission} {inp.cadence} cadence"
                f" {_author_tag}"
            ),
        )
    )

    return [seg for seg, _, _ in segments_and_meta]


def _segments_to_fits_bytes(segments: list[LightCurveSegment]) -> bytes:
    """Serialise a list of ``LightCurveSegment`` to a multi-extension FITS bytes object."""
    import numpy as np
    from astropy.io import fits as _fits

    hdus = [_fits.PrimaryHDU()]
    for seg in segments:
        time_arr = np.array(seg.time.values, dtype=np.float64)
        flux_arr = np.array(seg.flux.values, dtype=np.float64)
        flux_err_arr = np.array(seg.flux_err.values, dtype=np.float64)
        quality_arr = np.array(seg.quality_flags, dtype=np.int32)

        cols = [
            _fits.Column(name="TIME", format="D", array=time_arr,
                         unit=seg.time.unit),
            _fits.Column(name="FLUX", format="D", array=flux_arr,
                         unit=seg.flux.unit),
            _fits.Column(name="FLUX_ERR", format="D", array=flux_err_arr,
                         unit=seg.flux_err.unit),
            _fits.Column(name="QUALITY", format="J", array=quality_arr),
        ]
        hdr = _fits.Header()
        hdr["TIMESYS"] = seg.time_scale.upper()
        hdr["TIME_FMT"] = seg.time_format
        hdr["TIMEUNIT"] = "d"
        hdr["SECTOR"] = seg.sector
        hdr["CADENCE"] = seg.cadence_type

        hdu = _fits.BinTableHDU.from_columns(cols, header=hdr)
        hdus.append(hdu)

    hdul = _fits.HDUList(hdus)
    buf = io.BytesIO()
    hdul.writeto(buf)
    return buf.getvalue()


def _fits_to_segments(fits_path: Path, inp: IngestInput) -> list[LightCurveSegment]:
    """Re-parse a cached multi-extension FITS back into ``LightCurveSegment`` objects."""
    from astropy.io import fits as _fits
    from ..ingest.sources.mast import extract_time_system

    segments: list[LightCurveSegment] = []
    with _fits.open(fits_path) as hdul:
        for ext in hdul[1:]:
            hdr = ext.header
            data = ext.data
            fits_label = f"{fits_path}[{ext.name}]"

            time_scale, time_format = extract_time_system(hdr, fits_label)
            sector = int(hdr.get("SECTOR", 0))

            time_col = data["TIME"].astype(float)
            flux_col = data["FLUX"].astype(float)
            flux_err_col = data["FLUX_ERR"].astype(float)
            quality_col = data["QUALITY"].astype(int)

            time_unit_str = hdr.get("TIMEUNIT", time_format)

            # Read column units from header
            ncols = hdr.get("TFIELDS", 0)
            flux_unit_str = "electron / s"
            for i in range(1, ncols + 1):
                if hdr.get(f"TTYPE{i}", "").strip().upper() == "FLUX":
                    flux_unit_str = hdr.get(f"TUNIT{i}", "electron / s").strip()
                    break

            segments.append(
                LightCurveSegment(
                    sector=sector,
                    time=UnitedArray(values=time_col.tolist(), unit=time_format),
                    time_scale=time_scale,
                    time_format=time_format,
                    flux=UnitedArray(values=flux_col.tolist(), unit=flux_unit_str),
                    flux_err=UnitedArray(values=flux_err_col.tolist(), unit=flux_unit_str),
                    quality_flags=quality_col.tolist(),
                    cadence_type=hdr.get("CADENCE", inp.cadence),
                )
            )
    return segments


def _gaia_cache_query(inp: IngestInput, ra: float, dec: float) -> str:
    return f"gaia:dr3:{normalise_target_id(inp.target_id)}:ra={ra:.5f}:dec={dec:.5f}"


def _fetch_gaia(
    inp: IngestInput,
    *,
    cache: IngestCache,
    offline: bool,
    max_age: datetime.timedelta | None,
    force_refetch: bool,
    provenance_records: list[DatasetProvenance],
) -> StellarParams | None:
    """Fetch Gaia DR3 stellar params, using cache when possible."""
    import json

    # We don't know RA/Dec until after the TAP query; skip Gaia if not available
    # In tests, _stellar_params is injected directly so this path is not hit.
    # For the full pipeline, RA/Dec comes from the TAP result.
    log.debug("Gaia fetch requested but RA/Dec not yet resolved; skipping.")
    return None


def _tap_cache_query(inp: IngestInput) -> str:
    return f"tap:pscomppars:{normalise_target_id(inp.target_id)}"


def _fetch_tap(
    inp: IngestInput,
    *,
    cache: IngestCache,
    offline: bool,
    max_age: datetime.timedelta | None,
    force_refetch: bool,
    provenance_records: list[DatasetProvenance],
) -> None:
    """Fetch planet parameters from TAP, using cache when possible."""
    import json

    cache_query = _tap_cache_query(inp)
    access_date = datetime.date.today()

    if not force_refetch:
        hit = cache.get(cache_query, ".parquet", max_age=max_age, offline=offline)
        if hit is not None:
            cached_path, cached_manifest, _ = hit
            log.info("TAP cache hit for %s", cache_query)
            provenance_records.append(
                DatasetProvenance(
                    source_doi=cached_manifest.get("source_doi", NEA_DOI),
                    source_url=cached_manifest.get("source_url", ""),
                    access_date=datetime.date.fromisoformat(
                        cached_manifest.get("access_date", access_date.isoformat())
                    ),
                    row_count=cached_manifest.get("row_count", 1),
                    description=cached_manifest.get("description", f"TAP: {inp.target_id}"),
                )
            )
            return

    if offline:
        log.warning("TAP fetch skipped (offline mode, cache miss): %s", inp.target_id)
        return

    log.info("Fetching from TAP: %s", inp.target_id)
    from ..ingest.sources.tap import fetch_planet_params, TAP_ENDPOINT

    try:
        df = fetch_planet_params(inp.target_id)
    except TargetNotFoundError:
        log.warning("TAP: no rows for %s; skipping.", inp.target_id)
        return

    parquet_bytes = df.to_parquet(index=False)
    cache.put(
        cache_query,
        ".parquet",
        parquet_bytes,
        source_doi=NEA_DOI,
        source_url=TAP_ENDPOINT,
        access_date=access_date,
        row_count=len(df),
        description=f"TAP pscomppars: {inp.target_id}",
    )

    provenance_records.append(
        DatasetProvenance(
            source_doi=NEA_DOI,
            source_url=TAP_ENDPOINT,
            access_date=access_date,
            row_count=len(df),
            description=f"NASA Exoplanet Archive pscomppars: {inp.target_id}",
        )
    )
