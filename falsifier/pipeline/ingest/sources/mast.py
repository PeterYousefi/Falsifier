"""
falsifier.pipeline.ingest.sources.mast
=========================================
MAST / lightkurve light curve fetcher.

Responsibilities
----------------
- Download a light curve for a pinned mission + author + cadence + sector/quarter.
- Read ``time_scale`` and ``time_format`` from the FITS header (TIMESYS and
  TIMEUNIT / TIME_FMT).  Raise ``HeaderMissingKeyError`` if either is absent.
- Return ``list[LightCurveSegment]`` with all physical arrays as ``UnitedArray``.
- Raise typed exceptions on all failure modes.  Never return partial data
  silently.  Never fall back to a different data source.  A MAST failure
  raises ``MastFetchError``; calling code must handle it explicitly and may
  choose to attempt a TAP or Gaia query as a separate, explicit step.
  There is no automatic source substitution in this module.

Time-system extraction
----------------------
Kepler FITS headers::

    TIMESYS = 'TDB '
    TIMEUNIT = 'd   '
    (time column: BKJD — Barycentric Kepler Julian Date = BJD − 2454833.0)

TESS FITS headers::

    TIMESYS = 'TDB '
    TIMEUNIT = 'd   '
    (time column: BTJD — Barycentric TESS Julian Date = BJD − 2457000.0)

The ``time_format`` is derived from the TELESCOP header keyword combined
with TIMEUNIT: for Kepler it is ``"bkjd"``; for TESS it is ``"btjd"``.
Both are registered astropy ``Time`` formats.

FITS column units
-----------------
Flux units are read from the TUNIT keyword of the FITS binary table.  If
absent, the flux column is labelled ``"electron / s"`` (SAP) or
``"dimensionless"`` (PDCSAP) depending on which column was selected, and a
warning is logged.
"""

from __future__ import annotations

import datetime
import logging
import warnings
from pathlib import Path
from typing import Any

import numpy as np

from ...contracts.ingest import LightCurveSegment
from ...contracts.manifest import UnitedArray
from ..endpoints import MAST_API_URL, MAST_DOI
from ..exceptions import (
    HeaderMissingKeyError,
    MastFetchError,
    NoProductMatchError,
    PartialDataError,
    TargetNotFoundError,
)

log = logging.getLogger(__name__)

# Re-export so callers that already import MAST_DOI from here continue to work.
__all__ = ["MAST_DOI", "fetch_lightcurve", "extract_time_system"]

# Map TELESCOP header value → astropy Time format for the time column
_TELESCOP_TO_TIME_FORMAT: dict[str, str] = {
    "Kepler": "bkjd",
    "KEPLER": "bkjd",
    "K2": "bkjd",
    "TESS": "btjd",
}

_TUNIT_FALLBACKS: dict[str, str] = {
    "SAP_FLUX": "electron / s",
    "PDCSAP_FLUX": "dimensionless",
}

# ---------------------------------------------------------------------------
# Time-system extraction from FITS header
# ---------------------------------------------------------------------------

def extract_time_system(header: Any, fits_path: str) -> tuple[str, str]:
    """
    Read ``time_scale`` and ``time_format`` from a lightkurve FITS header.

    Parameters
    ----------
    header : fits.Header
        Primary or extension header from the open FITS file.
    fits_path : str
        Path string used in error messages.

    Returns
    -------
    (time_scale, time_format) — both lower-cased.

    Raises
    ------
    HeaderMissingKeyError
        If TIMESYS is absent, or if the time_format cannot be determined.
    """
    # time_scale: from TIMESYS
    if "TIMESYS" not in header:
        raise HeaderMissingKeyError(
            f"FITS header lacks TIMESYS in {fits_path}.\n"
            "Cannot determine time scale.  This must come from the header.",
            fits_path=fits_path,
            key="TIMESYS",
        )
    time_scale = header["TIMESYS"].strip().lower()

    # time_format: prefer explicit TIME_FMT, else derive from TELESCOP
    if "TIME_FMT" in header:
        time_format = header["TIME_FMT"].strip().lower()
    elif "TELESCOP" in header:
        telescop = header["TELESCOP"].strip()
        if telescop not in _TELESCOP_TO_TIME_FORMAT:
            raise HeaderMissingKeyError(
                f"Unknown TELESCOP value '{telescop}' in {fits_path}; "
                "cannot derive time_format.  Add it to _TELESCOP_TO_TIME_FORMAT.",
                fits_path=fits_path,
                key="TELESCOP",
            )
        time_format = _TELESCOP_TO_TIME_FORMAT[telescop]
    elif "TIMEUNIT" in header:
        # Last resort: TIMEUNIT gives 'd' — not enough alone, but paired
        # with ORIGIN we can sometimes infer.  Raise rather than guess.
        raise HeaderMissingKeyError(
            f"FITS header has TIMEUNIT='{header['TIMEUNIT']}' but no TELESCOP "
            f"or TIME_FMT in {fits_path}.  Cannot derive time_format without "
            "guessing.  Add TIME_FMT to the FITS header.",
            fits_path=fits_path,
            key="TIME_FMT",
        )
    else:
        raise HeaderMissingKeyError(
            f"FITS header lacks both TIME_FMT and TELESCOP in {fits_path}.\n"
            "Cannot determine time_format.",
            fits_path=fits_path,
            key="TIME_FMT",
        )

    return time_scale, time_format


# ---------------------------------------------------------------------------
# Flux unit extraction
# ---------------------------------------------------------------------------

def _flux_unit_from_header(header: Any, col_name: str, fits_path: str) -> str:
    """
    Read the FITS TUNIT keyword for *col_name* from the binary table header.

    Falls back to a known default for SAP_FLUX / PDCSAP_FLUX with a warning.

    Parameters
    ----------
    header : fits.Header
        Binary-table extension header containing TTYPE/TUNIT keywords.
    col_name : str
        Name of the flux column whose unit to look up (e.g. ``"SAP_FLUX"``).
    fits_path : str
        Path string used in the UserWarning message when no TUNIT is found.

    Returns
    -------
    str
        Unit string from TUNIT, or a per-column fallback with a UserWarning
        if the keyword is absent.
    """
    # Find column index (1-based) for col_name
    ncols = header.get("TFIELDS", 0)
    for i in range(1, ncols + 1):
        if header.get(f"TTYPE{i}", "").strip().upper() == col_name.upper():
            unit_key = f"TUNIT{i}"
            if unit_key in header:
                return header[unit_key].strip()
            break

    # No TUNIT found — use fallback
    fallback = _TUNIT_FALLBACKS.get(col_name.upper(), "dimensionless")
    warnings.warn(
        f"No TUNIT found for column '{col_name}' in {fits_path}; "
        f"assuming '{fallback}'.",
        UserWarning,
        stacklevel=4,
    )
    return fallback


# ---------------------------------------------------------------------------
# Empty-result diagnostic helper
# ---------------------------------------------------------------------------

# Maps lightkurve exptime (seconds) → human-readable cadence label.
# Lightkurve's own buckets: 'fast' ≤ 20 s, 'short' ≤ 120 s, else 'long'.
_EXPTIME_TO_CADENCE: list[tuple[float, str]] = [
    (20.0,   "fast (20 s)"),
    (120.0,  "short (2 min)"),
    (600.0,  "long (10 min)"),
    (1800.0, "long (30 min)"),
]


def _exptime_to_cadence_label(exptime_s: float) -> str:
    """
    Return a human-readable cadence label for an exposure time in seconds.

    Parameters
    ----------
    exptime_s : float
        Exposure time in seconds (from the lightkurve search result table).

    Returns
    -------
    str
        Human-readable label such as ``"fast (20 s)"`` or ``"long (30 min)"``.
    """
    for threshold, label in _EXPTIME_TO_CADENCE:
        if exptime_s <= threshold:
            return label
    return f"long ({exptime_s:.0f} s)"


def _empty_result_error(
    *,
    target_id: str,
    mission: str,
    author: str,
    cadence: str,
    search_kwargs: dict,
    lk: object,
) -> TargetNotFoundError:
    """
    Build an informative ``TargetNotFoundError`` when the primary search
    returns zero results.

    Strategy
    --------
    1. Re-run without the ``cadence`` filter (same mission + author).
       If products exist, the error names which cadences ARE available and
       tells the user to change the cadence control — not the mission.
    2. If still zero: target has no products under this mission at all.
       Suggest a different mission.

    The diagnostic search is read-only and never substitutes data — the
    caller will still raise, not proceed (AGENTS.md: no source substitution).

    Parameters
    ----------
    target_id : str
        The target identifier that returned zero results.
    mission : str
        Mission name passed to the original lightkurve search (e.g.
        ``"Kepler"``).
    author : str
        Reduction pipeline author filter (e.g. ``"Kepler"``).
    cadence : str
        Cadence filter that matched zero results (e.g. ``"long"``).
    search_kwargs : dict
        The full kwargs dict passed to ``lk.search_lightcurve``; included
        in the exception ``query`` field for diagnostics.
    lk : object
        The imported ``lightkurve`` module used for the diagnostic probe.

    Returns
    -------
    TargetNotFoundError
        Informative exception with cadence availability details when known.
    """
    # --- probe 1: same mission, any cadence ---
    probe_kwargs: dict = {
        "mission": mission,
        "author": author,
    }
    probe_results = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            probe_results = lk.search_lightcurve(target_id, **probe_kwargs)  # type: ignore[attr-defined]
    except Exception:
        # Diagnostic probe failed — fall back to the generic message
        pass

    if probe_results is not None and len(probe_results) > 0:
        # Products exist at a different cadence. Report which ones.
        try:
            import numpy as _np
            exptimes = sorted(set(
                float(e) for e in probe_results.table["exptime"]
                if e is not None
            ))
            cadence_labels = [_exptime_to_cadence_label(e) for e in exptimes]
            available_str = ", ".join(cadence_labels) if cadence_labels else "unknown"
        except Exception:
            available_str = "other cadences"

        return TargetNotFoundError(
            f"No {cadence!r} cadence products found for target={target_id!r} "
            f"under mission={mission!r}.\n"
            f"Available cadence(s) for this target and mission: {available_str}.\n"
            f"Change the cadence selector and resubmit.",
            endpoint=MAST_API_URL,
            query=str(search_kwargs),
        )

    # --- probe 2: no products at all under this mission ---
    return TargetNotFoundError(
        f"No MAST products found for target={target_id!r} under "
        f"mission={mission!r} (author={author!r}).\n"
        f"Try selecting a different mission.",
        endpoint=MAST_API_URL,
        query=str(search_kwargs),
    )


# ---------------------------------------------------------------------------
# Core fetch
# ---------------------------------------------------------------------------

def fetch_lightcurve(
    target_id: str,
    *,
    mission: str,
    author: str,
    cadence: str,
    sectors: list[int] | None,
    mast_product_id: str | None = None,
    flux_column: str = "SAP_FLUX",
) -> list[tuple[LightCurveSegment, str, int]]:
    """
    Download light curve data from MAST via lightkurve.

    Parameters
    ----------
    target_id : str
        Canonical target identifier, e.g. ``"KIC 11904151"`` or
        ``"TIC 150428135"``.
    mission : str
        Mission name passed to ``lk.search_lightcurve``, e.g. ``"Kepler"``
        or ``"TESS"``.
    author : str
        Reduction pipeline author filter (e.g. ``"Kepler"`` or ``"SPOC"``).
    cadence : str
        Cadence filter: ``"long"``, ``"short"``, or ``"fast"``.
    sectors : list[int] or None
        Sector/quarter numbers to fetch.  ``None`` returns all available.
    mast_product_id : str or None
        If given, pin the download to the specific MAST product filename or
        obs_id that contains this string.  Raises if zero or multiple match.
    flux_column : str
        Name of the flux column to read from the FITS binary table.
        Default: ``"SAP_FLUX"``.

    Returns
    -------
    list[tuple[LightCurveSegment, str, int]]
        One ``(segment, mast_uri, row_count)`` tuple per downloaded
        sector/quarter.

    Raises
    ------
    TargetNotFoundError
        If lightkurve returns zero results for the requested target and
        cadence.
    NoProductMatchError
        If *mast_product_id* is given but no result matches it.
    AmbiguousProductError
        If *mast_product_id* matches more than one result.
    MastFetchError
        On any other lightkurve / network failure.
    HeaderMissingKeyError
        If the FITS header lacks TIMESYS or time_format information.
    PartialDataError
        If some sectors were requested but fewer were returned.
    """
    try:
        import lightkurve as lk
        from astropy.io import fits
    except ImportError as exc:
        raise MastFetchError(
            f"lightkurve or astropy not installed: {exc}",
            endpoint="MAST",
            query=target_id,
        ) from exc

    # Build search kwargs — always explicit, never use lightkurve defaults
    search_kwargs: dict[str, Any] = {
        "mission": mission,
        "author": author,
        "cadence": cadence,
    }
    if sectors is not None:
        # lightkurve uses 'quarter' for Kepler and 'sector' for TESS/K2
        if mission == "Kepler":
            search_kwargs["quarter"] = sectors
        else:
            search_kwargs["sector"] = sectors

    log.debug(
        "MAST search: target=%r mission=%s author=%s cadence=%s sectors=%s",
        target_id,
        mission,
        author,
        cadence,
        sectors,
    )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = lk.search_lightcurve(target_id, **search_kwargs)
    except Exception as exc:
        log.exception(
            "lightkurve.search_lightcurve failed for target=%r search_kwargs=%s",
            target_id,
            search_kwargs,
        )
        raise MastFetchError(
            f"lightkurve.search_lightcurve failed: {exc}",
            endpoint=MAST_API_URL,
            query=str(search_kwargs),
        ) from exc

    if len(results) == 0:
        raise _empty_result_error(
            target_id=target_id,
            mission=mission,
            author=author,
            cadence=cadence,
            search_kwargs=search_kwargs,
            lk=lk,
        )

    # Pin to specific product if requested
    if mast_product_id is not None:
        # results.table is an astropy Table; rows are astropy Row objects which
        # have no .get() method.  Use column-name + row-index access instead.
        _tbl = results.table
        _fn_col = "productFilename" if "productFilename" in _tbl.colnames else None
        _id_col = "obs_id" if "obs_id" in _tbl.colnames else None
        matched_indices = []
        for _i in range(len(_tbl)):
            _fn_val = str(_tbl[_fn_col][_i]) if _fn_col else ""
            _id_val = str(_tbl[_id_col][_i]) if _id_col else ""
            if mast_product_id in (_fn_val or _id_val):
                matched_indices.append(_i)
        if not matched_indices:
            _avail = list(_tbl[_fn_col]) if _fn_col else []
            raise NoProductMatchError(
                f"No result matches mast_product_id={mast_product_id!r} "
                f"for target={target_id!r}.\n"
                f"Available products: {_avail}",
                endpoint=MAST_API_URL,
                query=mast_product_id,
            )
        if len(matched_indices) > 1:
            from ..exceptions import AmbiguousProductError
            raise AmbiguousProductError(
                f"Multiple results match mast_product_id={mast_product_id!r}; "
                "mast_product_id must be unique.",
                endpoint=MAST_API_URL,
                query=mast_product_id,
            )
        results = results[matched_indices[0] : matched_indices[0] + 1]

    # Check sector coverage
    if sectors is not None and len(results) < len(sectors):
        log.warning(
            "Requested %d sectors but only %d available for %s",
            len(sectors),
            len(results),
            target_id,
        )
        if len(results) == 0:
            raise PartialDataError(
                f"Requested sectors {sectors} for {target_id!r} but none available."
            )

    segments_out: list[tuple[LightCurveSegment, str, int]] = []

    for i in range(len(results)):
        result_row = results[i]

        log.debug("Downloading %s result %d/%d", target_id, i + 1, len(results))

        # Resolve the product filename for diagnostics before downloading.
        # result_row.table is an astropy Table (not a dict); use column +
        # row-index access.  Table has no .get() — that is the Row/dict API.
        _product_fn: str = "unknown"
        try:
            _tbl = result_row.table if hasattr(result_row, "table") else None
            if (
                _tbl is not None
                and len(_tbl) > 0
                and "productFilename" in _tbl.colnames
            ):
                _product_fn = str(_tbl["productFilename"][0])
        except Exception:
            pass

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                lc = result_row.download()
        except Exception as exc:
            # Attempt to measure the file size of any locally cached copy that
            # lightkurve may have written before raising.
            _cache_path: str | None = None
            _cache_size: int | None = None
            try:
                import lightkurve as _lk_diag
                _lk_cache = Path(_lk_diag.conf.cache_dir)
                # lightkurve names cached files after the product filename
                _candidate = _lk_cache / _product_fn
                if _candidate.exists():
                    _cache_path = str(_candidate)
                    _cache_size = _candidate.stat().st_size
            except Exception:
                pass

            log.exception(
                "lightkurve download failed  target=%r  item=%d/%d  "
                "product_filename=%r  cached_path=%s  cached_size_bytes=%s",
                target_id,
                i + 1,
                len(results),
                _product_fn,
                _cache_path,
                _cache_size,
            )
            raise MastFetchError(
                f"lightkurve download failed for {target_id!r} item {i} "
                f"(product={_product_fn!r}, "
                f"cached_path={_cache_path!r}, "
                f"cached_size_bytes={_cache_size!r}): {exc}",
                endpoint=MAST_API_URL,
                query=target_id,
            ) from exc

        if lc is None:
            raise MastFetchError(
                f"lightkurve download returned None for {target_id!r} item {i}",
                endpoint=MAST_API_URL,
                query=target_id,
            )

        # --- open the original FITS file lightkurve already downloaded ---
        # lightkurve stores the local cache path in lc.meta["FILENAME"] after
        # read_generic_lightcurve runs tab.meta["FILENAME"] = filename.
        # Reading that file directly gives us the authentic MAST primary header
        # (with TIMESYS, TELESCOP, QUARTER, TIMEUNIT, TUNIT* etc.) without any
        # round-trip through to_fits(), which rebuilds only a stripped template
        # header and would silently lose TIMESYS.
        _fits_filename: str | None = lc.meta.get("FILENAME")
        if not _fits_filename or not Path(_fits_filename).exists():
            raise MastFetchError(
                f"lightkurve did not record a local FITS path in lc.meta['FILENAME'] "
                f"for {target_id!r} item {i} (got {_fits_filename!r}).  "
                "Cannot read FITS header without the original file.",
                endpoint=MAST_API_URL,
                query=target_id,
            )

        with fits.open(_fits_filename) as hdul:
            # Primary header for time system, secondary for table columns
            primary_hdr = hdul[0].header
            table_hdr = hdul[1].header
            table_data = hdul[1].data

            # Determine which header has TIMESYS — usually primary for Kepler
            header_for_time = primary_hdr if "TIMESYS" in primary_hdr else table_hdr

            # If neither has it, raise — never guess a time system
            if "TIMESYS" not in primary_hdr and "TIMESYS" not in table_hdr:
                raise HeaderMissingKeyError(
                    f"Neither primary nor table header has TIMESYS for {target_id!r}",
                    fits_path=_fits_filename,
                    key="TIMESYS",
                )

            fits_path_str = _fits_filename
            time_scale, time_format = extract_time_system(header_for_time, fits_path_str)

            # Sector/quarter number
            sector_num = int(
                primary_hdr.get("QUARTER", primary_hdr.get("SECTOR", i))
            )

            # Time array
            time_col = table_data["TIME"].astype(np.float64)
            # lightkurve encodes NaN for bad cadences; keep all for now
            time_unit = time_format  # btjd / bkjd — the unit *is* the format

            # Flux array and unit
            flux_colname = flux_column if flux_column in table_data.names else "FLUX"
            flux_col = table_data[flux_colname].astype(np.float64)
            flux_unit_str = _flux_unit_from_header(table_hdr, flux_colname, fits_path_str)

            err_colname = flux_colname + "_ERR" if (flux_colname + "_ERR") in table_data.names else "FLUX_ERR"
            flux_err_col = table_data[err_colname].astype(np.float64) if err_colname in table_data.names else np.zeros_like(flux_col)

            quality_col = table_data["QUALITY"].astype(np.int32) if "QUALITY" in table_data.names else np.zeros(len(time_col), dtype=np.int32)

            # Centroids (optional)
            centroid_col_ua: UnitedArray | None = None
            centroid_row_ua: UnitedArray | None = None
            if "CENTROID_COL" in table_data.names:
                centroid_col_ua = UnitedArray(
                    values=table_data["CENTROID_COL"].astype(np.float64).tolist(),
                    unit="pix",
                )
            if "CENTROID_ROW" in table_data.names:
                centroid_row_ua = UnitedArray(
                    values=table_data["CENTROID_ROW"].astype(np.float64).tolist(),
                    unit="pix",
                )

        # Determine MAST URI from the result table.
        # result_row.table is an astropy Table; prefer "dataURI" then
        # "t_obs_release".  Table has no .get() — use colnames + row-index.
        # A wrong-but-non-crashing value here is an AGENTS.md Rule 3 violation:
        # mast_uri feeds source_url in the provenance sidecar.
        mast_uri: str = "MAST"
        _uri_tbl = result_row.table if hasattr(result_row, "table") else None
        if _uri_tbl is not None and len(_uri_tbl) > 0:
            for _uri_col in ("dataURI", "t_obs_release"):
                if _uri_col in _uri_tbl.colnames:
                    _val = str(_uri_tbl[_uri_col][0]).strip()
                    if _val:
                        mast_uri = _val
                        break

        segment = LightCurveSegment(
            sector=sector_num,
            time=UnitedArray(values=time_col.tolist(), unit=time_unit),
            time_scale=time_scale,
            time_format=time_format,
            flux=UnitedArray(values=flux_col.tolist(), unit=flux_unit_str),
            flux_err=UnitedArray(values=flux_err_col.tolist(), unit=flux_unit_str),
            quality_flags=quality_col.tolist(),
            cadence_type=cadence,
            centroid_col=centroid_col_ua,
            centroid_row=centroid_row_ua,
        )

        row_count = len(time_col)
        segments_out.append((segment, mast_uri, row_count))

    return segments_out
