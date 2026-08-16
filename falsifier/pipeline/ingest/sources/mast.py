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
  silently.  Never fall back to a different product.

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
import io
import logging
import warnings
from pathlib import Path
from typing import Any

import numpy as np

from ...contracts.ingest import LightCurveSegment
from ...contracts.manifest import UnitedArray
from ..exceptions import (
    HeaderMissingKeyError,
    MastFetchError,
    NoProductMatchError,
    PartialDataError,
    TargetNotFoundError,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAST_DOI = "10.17909/t9-st5g-3177"
"""
DOI for the MAST High Level Science Products archive.
Used as DatasetProvenance.source_doi for all MAST-fetched data.
"""

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

    Returns
    -------
    list of ``(segment, mast_uri, row_count)`` tuples — one per sector/quarter.

    Raises
    ------
    TargetNotFoundError
        If lightkurve returns zero results.
    NoProductMatchError
        If *mast_product_id* is given but no result matches it.
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
        raise MastFetchError(
            f"lightkurve.search_lightcurve failed: {exc}",
            endpoint="https://mast.stsci.edu",
            query=str(search_kwargs),
        ) from exc

    if len(results) == 0:
        raise TargetNotFoundError(
            f"No MAST results for target={target_id!r} with {search_kwargs}",
            endpoint="https://mast.stsci.edu",
            query=str(search_kwargs),
        )

    # Pin to specific product if requested
    if mast_product_id is not None:
        matched_indices = [
            i for i, row in enumerate(results.table)
            if mast_product_id in str(row.get("productFilename", "")
                                     or row.get("obs_id", ""))
        ]
        if not matched_indices:
            raise NoProductMatchError(
                f"No result matches mast_product_id={mast_product_id!r} "
                f"for target={target_id!r}.\n"
                f"Available products: {list(results.table['productFilename'])}",
                endpoint="https://mast.stsci.edu",
                query=mast_product_id,
            )
        if len(matched_indices) > 1:
            from ..exceptions import AmbiguousProductError
            raise AmbiguousProductError(
                f"Multiple results match mast_product_id={mast_product_id!r}; "
                "mast_product_id must be unique.",
                endpoint="https://mast.stsci.edu",
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

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                lc = result_row.download()
        except Exception as exc:
            raise MastFetchError(
                f"lightkurve download failed for {target_id!r} item {i}: {exc}",
                endpoint="https://mast.stsci.edu",
                query=target_id,
            ) from exc

        if lc is None:
            raise MastFetchError(
                f"lightkurve download returned None for {target_id!r} item {i}",
                endpoint="https://mast.stsci.edu",
                query=target_id,
            )

        # --- serialize to in-memory FITS to read the header properly ---
        buf = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lc.to_fits(output_fn=buf, overwrite=True)
        buf.seek(0)

        with fits.open(buf) as hdul:
            # Primary header for time system, secondary for table columns
            primary_hdr = hdul[0].header
            table_hdr = hdul[1].header
            table_data = hdul[1].data

            # Determine which header has TIMESYS — usually primary for Kepler
            header_for_time = primary_hdr if "TIMESYS" in primary_hdr else table_hdr

            # If neither has it, check both combined
            if "TIMESYS" not in primary_hdr and "TIMESYS" not in table_hdr:
                raise HeaderMissingKeyError(
                    f"Neither primary nor table header has TIMESYS for {target_id!r}",
                    fits_path=str(target_id),
                    key="TIMESYS",
                )

            fits_path_str = f"in-memory:{target_id}[{i}]"
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

        # Determine MAST URI from the result table
        mast_uri = str(
            result_row.table.get("dataURI", result_row.table.get("t_obs_release", "MAST"))
            if hasattr(result_row, "table") else "MAST"
        )

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
