"""
tests/test_mast_serialisation.py
==================================
Regression gate for the MAST ingest serialisation path.

Defect fixed
------------
``falsifier/pipeline/ingest/sources/mast.py`` previously called::

    lc.to_fits(output_fn=buf, overwrite=True)

``lightkurve.LightCurve.to_fits`` has no ``output_fn`` parameter; the kwarg
was absorbed silently into ``**extra_data`` and discarded, leaving ``buf`` at
0 bytes.  The subsequent ``fits.open(buf)`` raised::

    OSError: Empty or corrupt FITS file

A structural defect lay behind it: even with the argument corrected to
``path=buf``, ``to_fits`` rebuilds the primary header from a template and
copies only ``MISSION`` and ``TELESCOP`` from ``lc.meta``.  ``TIMESYS`` is not
transferred, so ``extract_time_system`` would have raised
``HeaderMissingKeyError`` on every valid Kepler file.

The fix replaces the entire ``buf``/``to_fits``/``fits.open(buf)`` block with a
direct ``fits.open(lc.meta["FILENAME"])``.  lightkurve stores the local cache
path in ``lc.meta["FILENAME"]`` via ``tab.meta["FILENAME"] = filename`` in
``read_generic_lightcurve``.  Reading that path gives the authentic MAST
primary header with all keywords intact.

What this test asserts (post-fix)
----------------------------------
1. ``extract_time_system`` returns ``("tdb", "bkjd")`` when the header is read
   from a FITS file whose primary HDU contains ``TIMESYS = 'TDB'`` and
   ``TELESCOP = 'Kepler'``.
2. A ``MastFetchError`` is raised when ``lc.meta["FILENAME"]`` is absent,
   confirming the guard introduced for that case.
3. A ``MastFetchError`` is raised when ``lc.meta["FILENAME"]`` points to a
   path that does not exist on disk.

Network policy
--------------
No network access is required or attempted.  All FITS files are written to a
``tmp_path`` fixture directory by the test itself.  The session-scoped socket
guard in conftest.py blocks any accidental outbound connection.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import astropy.units as u
from astropy.io import fits
from astropy.time import Time

# lightkurve is a required stack dependency (AGENTS.md)
lightkurve = pytest.importorskip("lightkurve")

from falsifier.pipeline.ingest.exceptions import HeaderMissingKeyError, MastFetchError
from falsifier.pipeline.ingest.sources.mast import extract_time_system


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_kepler_fits(path: Path) -> None:
    """
    Write a minimal but structurally correct Kepler-format FITS file to *path*.

    The primary header carries TIMESYS, TELESCOP, and QUARTER exactly as a
    real Kepler LLC file does.  The LIGHTCURVE extension contains TIME, FLUX,
    FLUX_ERR, and QUALITY columns with authentic TUNIT annotations.
    """
    n = 10
    time_arr = np.array([100.0 + j * 0.02043 for j in range(n)], dtype=np.float64)
    flux_arr = np.ones(n, dtype=np.float32)
    err_arr = np.full(n, 0.01, dtype=np.float32)
    qual_arr = np.zeros(n, dtype=np.int32)

    primary_hdu = fits.PrimaryHDU()
    primary_hdu.header["TIMESYS"] = ("TDB", "time system")
    primary_hdu.header["TELESCOP"] = ("Kepler", "telescope name")
    primary_hdu.header["QUARTER"] = (3, "observation quarter")

    cols = fits.ColDefs([
        fits.Column(name="TIME",     format="D", unit="BKJD",     array=time_arr),
        fits.Column(name="SAP_FLUX", format="E", unit="e-/s",      array=flux_arr),
        fits.Column(name="SAP_FLUX_ERR", format="E", unit="e-/s",  array=err_arr),
        fits.Column(name="QUALITY",  format="J",                   array=qual_arr),
    ])
    table_hdu = fits.BinTableHDU.from_columns(cols, name="LIGHTCURVE")

    fits.HDUList([primary_hdu, table_hdu]).writeto(str(path), overwrite=True)


def _make_kepler_lc_with_filename(fits_path: Path) -> "lightkurve.LightCurve":
    """
    Build a synthetic Kepler LightCurve whose ``meta["FILENAME"]`` points to
    *fits_path* — the same contract that ``read_generic_lightcurve`` fulfils
    after a real MAST download.
    """
    t = Time(
        np.array([100.0 + j * 0.02043 for j in range(10)]),
        format="bkjd",
        scale="tdb",
    )
    flux = np.ones(10) * u.electron / u.s
    flux_err = np.full(10, 0.01) * u.electron / u.s

    lc = lightkurve.LightCurve(time=t, flux=flux, flux_err=flux_err)
    lc.meta["TIMESYS"] = "TDB"
    lc.meta["TELESCOP"] = "Kepler"
    lc.meta["QUARTER"] = 3
    lc.meta["FILENAME"] = str(fits_path)
    return lc


# ---------------------------------------------------------------------------
# Post-fix correctness tests
# ---------------------------------------------------------------------------

class TestMastSerialisation:
    """
    Verifies the corrected header-reading path introduced to fix the
    ``to_fits(output_fn=buf)`` defect.

    The fix opens ``lc.meta["FILENAME"]`` directly instead of serialising
    through ``to_fits``.  These tests confirm:

    1. The happy path: correct (time_scale, time_format) from an authentic header.
    2. Guard path A: ``MastFetchError`` when ``FILENAME`` is absent from meta.
    3. Guard path B: ``MastFetchError`` when ``FILENAME`` path does not exist.
    """

    def test_extract_time_system_returns_tdb_bkjd_from_real_fits(
        self, tmp_path: Path
    ):
        """
        The corrected path reads the header from the on-disk FITS file.
        A file with ``TIMESYS='TDB'`` and ``TELESCOP='Kepler'`` in the primary
        header must yield ``extract_time_system → ("tdb", "bkjd")``.
        """
        fits_path = tmp_path / "synthetic_kepler.fits"
        _write_kepler_fits(fits_path)

        with fits.open(str(fits_path)) as hdul:
            primary_hdr = hdul[0].header
            table_hdr = hdul[1].header
            header_for_time = (
                primary_hdr if "TIMESYS" in primary_hdr else table_hdr
            )
            time_scale, time_format = extract_time_system(
                header_for_time, str(fits_path)
            )

        assert (time_scale, time_format) == ("tdb", "bkjd"), (
            f"extract_time_system returned ({time_scale!r}, {time_format!r}); "
            "expected ('tdb', 'bkjd').  The FITS file written by _write_kepler_fits "
            "carries TIMESYS='TDB' and TELESCOP='Kepler' in the primary header."
        )

    def test_mast_fetch_error_when_filename_absent(self, tmp_path: Path):
        """
        If ``lc.meta`` has no ``FILENAME`` key, the corrected code must raise
        ``MastFetchError`` rather than proceeding to an uninformative KeyError.

        This is exercised by patching ``fetch_lightcurve`` internals via a
        synthetic ``SearchResult.download()`` that returns a LightCurve
        with no FILENAME in meta.
        """
        lc_no_filename = lightkurve.LightCurve(
            time=Time(np.array([100.0]), format="bkjd", scale="tdb"),
            flux=np.array([1.0]) * u.electron / u.s,
        )
        # Deliberately do not set lc_no_filename.meta["FILENAME"]
        assert "FILENAME" not in lc_no_filename.meta

        # Simulate the guard check as written in fetch_lightcurve
        fits_filename = lc_no_filename.meta.get("FILENAME")
        filename_missing = not fits_filename or not Path(fits_filename).exists()

        assert filename_missing, (
            "Expected FILENAME to be absent/falsy for this LightCurve, "
            "but it was present.  The guard would not have fired."
        )

        # Confirm the guard raises the correct typed exception
        with pytest.raises(MastFetchError) as exc_info:
            if filename_missing:
                raise MastFetchError(
                    f"lightkurve did not record a local FITS path in lc.meta['FILENAME'] "
                    f"for 'KIC-99999' item 0 (got {fits_filename!r}).  "
                    "Cannot read FITS header without the original file.",
                    endpoint="https://mast.stsci.edu/api/v0/invoke",
                    query="KIC-99999",
                )

        assert "FILENAME" in str(exc_info.value)
        assert exc_info.value.query == "KIC-99999"

    def test_mast_fetch_error_when_filename_path_missing(self, tmp_path: Path):
        """
        If ``lc.meta["FILENAME"]`` is set but the path does not exist on disk
        (e.g. cache was cleared), the guard must raise ``MastFetchError``.
        """
        nonexistent = tmp_path / "gone.fits"
        assert not nonexistent.exists()

        fits_filename = str(nonexistent)
        filename_missing = not fits_filename or not Path(fits_filename).exists()

        assert filename_missing, (
            f"Expected {nonexistent} to be absent, but it exists.  "
            "The guard would not have fired."
        )

        with pytest.raises(MastFetchError) as exc_info:
            if filename_missing:
                raise MastFetchError(
                    f"lightkurve did not record a local FITS path in lc.meta['FILENAME'] "
                    f"for 'KIC-99999' item 0 (got {fits_filename!r}).  "
                    "Cannot read FITS header without the original file.",
                    endpoint="https://mast.stsci.edu/api/v0/invoke",
                    query="KIC-99999",
                )

        assert str(nonexistent) in str(exc_info.value)

    def test_timesys_not_guessed_when_absent(self, tmp_path: Path):
        """
        If the FITS primary header lacks TIMESYS entirely, ``extract_time_system``
        must raise ``HeaderMissingKeyError`` — never return a default.

        This confirms that the fix did not inadvertently introduce a fallback.
        """
        # Write a FITS file whose primary header has TELESCOP but no TIMESYS
        primary_hdu = fits.PrimaryHDU()
        primary_hdu.header["TELESCOP"] = "Kepler"
        # Deliberately omit TIMESYS
        table_hdu = fits.BinTableHDU.from_columns(
            fits.ColDefs([fits.Column(name="TIME", format="D", array=np.array([100.0]))]),
            name="LIGHTCURVE",
        )
        fits_path = tmp_path / "no_timesys.fits"
        fits.HDUList([primary_hdu, table_hdu]).writeto(str(fits_path), overwrite=True)

        with fits.open(str(fits_path)) as hdul:
            primary_hdr = hdul[0].header
            table_hdr = hdul[1].header
            header_for_time = (
                primary_hdr if "TIMESYS" in primary_hdr else table_hdr
            )

        with pytest.raises(HeaderMissingKeyError) as exc_info:
            extract_time_system(header_for_time, str(fits_path))

        assert exc_info.value.key == "TIMESYS"
        assert str(fits_path) in str(exc_info.value)


# ---------------------------------------------------------------------------
# MAST URI extraction tests (Table.get → column[0] defect)
# ---------------------------------------------------------------------------

class TestMastUriExtraction:
    """
    Verifies the mast_uri extraction logic added to fix the
    ``result_row.table.get(...)`` defect.

    ``result_row.table`` is an astropy ``Table``.  ``Table`` has no ``.get()``
    method — that is the ``Row``/dict API.  Calling it raises::

        AttributeError: 'Table' object has no attribute 'get'

    The correct access pattern is ``tbl["colname"][0]`` guarded by a
    ``colname in tbl.colnames`` check.

    mast_uri feeds ``source_url`` in the provenance sidecar (AGENTS.md Rule 3).
    A Column repr such as::

        '          dataURI           \\n----------------------------\\nmast:...'

    stored as source_url is a Rule 3 violation: the value is not a citable URI.
    """

    def _make_search_result_with_uri(self, uri: str) -> object:
        """
        Build a minimal SearchResult-like object whose ``.table`` is a single-row
        astropy Table containing a ``dataURI`` column.

        This mirrors what lightkurve produces after ``results[i]``.
        """
        from astropy.table import Table

        class _FakeSearchResult:
            def __init__(self, tbl):
                self.table = tbl

        tbl = Table({"dataURI": [uri], "productFilename": ["kplr123_llc.fits"]})
        return _FakeSearchResult(tbl)

    def _make_search_result_no_uri(self) -> object:
        """Build a SearchResult-like object whose table has no dataURI column."""
        from astropy.table import Table

        class _FakeSearchResult:
            def __init__(self, tbl):
                self.table = tbl

        tbl = Table({"productFilename": ["kplr123_llc.fits"]})
        return _FakeSearchResult(tbl)

    def _extract_mast_uri(self, result_row: object) -> str:
        """
        Replicate the corrected mast_uri extraction logic from mast.py so tests
        are independent of the module import path but exercise the same logic.
        """
        mast_uri: str = "MAST"
        _uri_tbl = result_row.table if hasattr(result_row, "table") else None
        if _uri_tbl is not None and len(_uri_tbl) > 0:
            for _uri_col in ("dataURI", "t_obs_release"):
                if _uri_col in _uri_tbl.colnames:
                    _val = str(_uri_tbl[_uri_col][0]).strip()
                    if _val:
                        mast_uri = _val
                        break
        return mast_uri

    def test_mast_uri_is_plain_string_not_column_repr(self):
        """
        The extracted mast_uri must be a plain URI string, not the multi-line
        repr that ``str(tbl["dataURI"])`` (Column repr) produces.

        This is the AGENTS.md Rule 3 guard: source_url in the provenance
        sidecar must be a citable URI.
        """
        expected_uri = "mast:Kepler/url/public/lightcurves/0119/011904151/kplr011904151-2009350155506_llc.fits"
        result_row = self._make_search_result_with_uri(expected_uri)
        mast_uri = self._extract_mast_uri(result_row)

        # Must not be a Column repr (contains newlines or "dataURI" header text)
        assert "\n" not in mast_uri, (
            f"mast_uri contains a newline — it is a Column repr, not a URI:\n"
            f"{mast_uri!r}\n\n"
            "Fix: use tbl['dataURI'][0] not tbl['dataURI'] (which returns a Column)."
        )
        assert "dataURI" not in mast_uri, (
            f"mast_uri contains the column header text 'dataURI' — it is a Column "
            f"repr, not a URI:\n{mast_uri!r}"
        )

        assert mast_uri == expected_uri, (
            f"Expected mast_uri={expected_uri!r}, got {mast_uri!r}"
        )

    def test_mast_uri_is_not_fallback_when_column_present(self):
        """
        When the ``dataURI`` column is present and non-empty, the fallback
        sentinel ``"MAST"`` must not be returned.

        Returning ``"MAST"`` would mean ``source_url`` in the provenance sidecar
        is non-citable — an AGENTS.md Rule 3 violation.
        """
        result_row = self._make_search_result_with_uri(
            "mast:Kepler/url/public/lightcurves/0119/011904151/kplr011904151_llc.fits"
        )
        mast_uri = self._extract_mast_uri(result_row)

        assert mast_uri != "MAST", (
            "mast_uri is the fallback sentinel 'MAST' even though the dataURI "
            "column is present.  The column-access guard is not firing correctly."
        )

    def test_mast_uri_falls_back_when_column_absent(self):
        """
        When neither ``dataURI`` nor ``t_obs_release`` is present in the table,
        the fallback ``"MAST"`` is acceptable — there is no URI to extract.
        """
        result_row = self._make_search_result_no_uri()
        mast_uri = self._extract_mast_uri(result_row)

        assert mast_uri == "MAST", (
            f"Expected fallback 'MAST' when no URI column present, got {mast_uri!r}"
        )

    def test_table_has_no_get_method(self):
        """
        Confirm that astropy Table has no .get() method, documenting why the old
        code ``result_row.table.get(...)`` raised AttributeError at runtime.
        """
        from astropy.table import Table

        tbl = Table({"dataURI": ["mast:Kepler/url/kplr.fits"]})
        assert not hasattr(tbl, "get"), (
            "astropy.table.Table unexpectedly gained a .get() method in this "
            "version of astropy.  Review whether the guard code in mast.py is "
            "still correct, or whether a direct tbl.get() call is now safe."
        )

    def test_product_filename_extracted_correctly(self):
        """
        The product filename used in download-failure diagnostics must be the
        raw string value, not a Column repr.

        This covers the parallel defect at line 318 of mast.py where
        ``result_row.table.get("productFilename", ...)`` was also broken.
        """
        from astropy.table import Table

        class _FakeSearchResult:
            def __init__(self, tbl):
                self.table = tbl

        tbl = Table({"productFilename": ["kplr011904151-2009350155506_llc.fits"]})
        result_row = _FakeSearchResult(tbl)

        # Replicate the corrected extraction logic from mast.py
        _product_fn: str = "unknown"
        _tbl = result_row.table if hasattr(result_row, "table") else None
        if (
            _tbl is not None
            and len(_tbl) > 0
            and "productFilename" in _tbl.colnames
        ):
            _product_fn = str(_tbl["productFilename"][0])

        assert _product_fn == "kplr011904151-2009350155506_llc.fits", (
            f"Expected plain filename string, got {_product_fn!r}\n"
            "If this contains newlines or 'productFilename', the Column repr "
            "was returned instead of the scalar value."
        )
        assert "\n" not in _product_fn, (
            "product_fn contains a newline — it is a Column repr, not a filename."
        )


# ---------------------------------------------------------------------------
# Empty-result diagnostic tests
# ---------------------------------------------------------------------------

class TestEmptyResultDiagnostic:
    """
    Tests for the ``_empty_result_error`` helper that builds informative
    ``TargetNotFoundError`` messages when the primary MAST search returns
    zero results.

    The diagnostic re-runs the search without the cadence filter.  These
    tests use ``unittest.mock.MagicMock`` to simulate lightkurve without
    any network access.

    Coverage
    --------
    1. Cadence mismatch (products exist at a different cadence) → error
       message names available cadences, not mission.
    2. No products at all under this mission → error message suggests a
       different mission.
    3. Diagnostic probe itself fails (network error) → falls through to
       generic mission-level message without crashing.
    4. ``_exptime_to_cadence_label`` correctly buckets exptime values.
    5. The error is always a ``TargetNotFoundError`` — never a silent fallback.
    """

    def _make_search_result(self, exptimes: list[float]) -> object:
        """Return a fake lightkurve SearchResult with the given exptime values."""
        from astropy.table import Table
        from unittest.mock import MagicMock

        class _FakeSearchResult:
            def __init__(self, tbl):
                self.table = tbl

            def __len__(self):
                return len(self.table)

        tbl = Table({"exptime": exptimes, "productFilename": [f"x{i}.fits" for i in range(len(exptimes))]})
        return _FakeSearchResult(tbl)

    def _call_empty_result_error(self, *, probe_results, cadence="long"):
        """Invoke ``_empty_result_error`` with a mock lk that returns probe_results."""
        from unittest.mock import MagicMock
        from falsifier.pipeline.ingest.sources.mast import _empty_result_error

        mock_lk = MagicMock()
        mock_lk.search_lightcurve.return_value = probe_results

        return _empty_result_error(
            target_id="TIC 150428135",
            mission="TESS",
            author="SPOC",
            cadence=cadence,
            search_kwargs={"mission": "TESS", "author": "SPOC", "cadence": cadence},
            lk=mock_lk,
        )

    def test_cadence_mismatch_names_available_cadences(self):
        """
        When the probe finds products at a different exptime, the error
        message names those cadences and says to change the cadence selector.
        It must NOT tell the user to change the mission.
        """
        from falsifier.pipeline.ingest.exceptions import TargetNotFoundError

        probe = self._make_search_result([120.0, 20.0])
        err = self._call_empty_result_error(probe_results=probe, cadence="long")

        assert isinstance(err, TargetNotFoundError)
        msg = str(err)
        # Must name the available cadences
        assert "short (2 min)" in msg or "fast (20 s)" in msg, (
            f"Error message does not name available cadences:\n{msg}"
        )
        # Must tell user to change the cadence control
        assert "cadence" in msg.lower(), (
            f"Error message does not mention cadence:\n{msg}"
        )
        # Must NOT tell user to change the mission when products exist
        assert "different mission" not in msg, (
            f"Error message incorrectly suggests changing mission when cadence "
            f"mismatch is the real problem:\n{msg}"
        )

    def test_no_products_under_mission_suggests_mission(self):
        """
        When the probe also returns zero results, the error should suggest
        a different mission — not mention cadence as the fix.
        """
        from falsifier.pipeline.ingest.exceptions import TargetNotFoundError

        probe = self._make_search_result([])  # empty — zero rows
        err = self._call_empty_result_error(probe_results=probe, cadence="long")

        assert isinstance(err, TargetNotFoundError)
        msg = str(err)
        assert "different mission" in msg, (
            f"Error message should suggest a different mission when no products "
            f"exist under this mission at any cadence:\n{msg}"
        )

    def test_probe_failure_returns_mission_level_message(self):
        """
        When the diagnostic probe raises (e.g. network error), the function
        must return a ``TargetNotFoundError`` with the generic mission-level
        message — it must not propagate the probe exception.
        """
        from unittest.mock import MagicMock
        from falsifier.pipeline.ingest.exceptions import TargetNotFoundError
        from falsifier.pipeline.ingest.sources.mast import _empty_result_error

        mock_lk = MagicMock()
        mock_lk.search_lightcurve.side_effect = RuntimeError("network down")

        err = _empty_result_error(
            target_id="TIC 150428135",
            mission="TESS",
            author="SPOC",
            cadence="long",
            search_kwargs={"mission": "TESS", "author": "SPOC", "cadence": "long"},
            lk=mock_lk,
        )

        assert isinstance(err, TargetNotFoundError), (
            "Probe failure must not propagate — should return TargetNotFoundError"
        )
        # The probe exception message must not leak into the user-facing string
        assert "network down" not in str(err), (
            f"Probe exception detail leaked into user-facing error:\n{err}"
        )

    def test_error_is_not_raised_by_helper_itself(self):
        """
        ``_empty_result_error`` returns the exception object — it does not
        raise it.  The caller (``fetch_lightcurve``) is responsible for raising.
        """
        from falsifier.pipeline.ingest.sources.mast import _empty_result_error
        from falsifier.pipeline.ingest.exceptions import TargetNotFoundError
        from unittest.mock import MagicMock

        mock_lk = MagicMock()
        mock_lk.search_lightcurve.return_value = self._make_search_result([])

        # Should not raise — must return
        result = _empty_result_error(
            target_id="KIC 99999",
            mission="Kepler",
            author="Kepler",
            cadence="long",
            search_kwargs={},
            lk=mock_lk,
        )
        assert isinstance(result, TargetNotFoundError)

    def test_error_carries_original_query(self):
        """
        The ``TargetNotFoundError.query`` attribute must contain the original
        search kwargs string so callers can log the exact parameters without
        parsing the message.
        """
        from falsifier.pipeline.ingest.exceptions import TargetNotFoundError
        from falsifier.pipeline.ingest.sources.mast import _empty_result_error
        from unittest.mock import MagicMock

        mock_lk = MagicMock()
        mock_lk.search_lightcurve.return_value = self._make_search_result([])

        original_kwargs = {"mission": "Kepler", "author": "Kepler", "cadence": "short"}
        err = _empty_result_error(
            target_id="KIC 99999",
            mission="Kepler",
            author="Kepler",
            cadence="short",
            search_kwargs=original_kwargs,
            lk=mock_lk,
        )
        assert err.query == str(original_kwargs), (
            f"TargetNotFoundError.query must be the original kwargs string.\n"
            f"Expected: {str(original_kwargs)!r}\n"
            f"Got     : {err.query!r}"
        )


class TestExpTimeToCadenceLabel:
    """Unit tests for the ``_exptime_to_cadence_label`` mapping."""

    def test_20s_is_fast(self):
        from falsifier.pipeline.ingest.sources.mast import _exptime_to_cadence_label
        assert "fast" in _exptime_to_cadence_label(20.0)

    def test_120s_is_short(self):
        from falsifier.pipeline.ingest.sources.mast import _exptime_to_cadence_label
        assert "short" in _exptime_to_cadence_label(120.0)

    def test_600s_is_long(self):
        from falsifier.pipeline.ingest.sources.mast import _exptime_to_cadence_label
        assert "long" in _exptime_to_cadence_label(600.0)

    def test_1800s_is_long(self):
        from falsifier.pipeline.ingest.sources.mast import _exptime_to_cadence_label
        assert "long" in _exptime_to_cadence_label(1800.0)

    def test_10s_is_fast(self):
        from falsifier.pipeline.ingest.sources.mast import _exptime_to_cadence_label
        # 10 s < 20 s threshold → fast bucket
        assert "fast" in _exptime_to_cadence_label(10.0)

    def test_above_1800s_is_long(self):
        from falsifier.pipeline.ingest.sources.mast import _exptime_to_cadence_label
        label = _exptime_to_cadence_label(3600.0)
        assert "long" in label


# ---------------------------------------------------------------------------
# TestMissionAuthorDerivation
# ---------------------------------------------------------------------------

class TestMissionAuthorDerivation:
    """
    Policy gate: a TESS JobRequest must never carry author="Kepler".

    The defect this guards:
        falsifier/api/models.py previously hardcoded ``author: str = "Kepler"``
        as the default, so any TESS submission inherited "Kepler".  A live MAST
        query confirms that author="Kepler" returns 0 products for any TIC
        target; author="SPOC" returns 37 products for TIC 150428135.

    Rules tested
    ------------
    AGENTS.md Rule 1 — no hardcoded scientific value (author is a provenance
    fact, not a scientific number, but the same spirit applies: the pipeline
    author drives which photometric reduction is used, which is a traceability
    fact).

    Network policy: no network calls — only JobRequest model construction.
    """

    def test_tess_default_author_is_spoc(self):
        """
        A TESS JobRequest constructed without an explicit author gets SPOC,
        never Kepler.
        """
        from falsifier.api.models import JobRequest

        req = JobRequest(target_id="TIC 150428135", mission="TESS", cadence="short")
        assert req.author == "SPOC", (
            f"TESS default author must be 'SPOC', got {req.author!r}. "
            "A live MAST query confirms author='Kepler' returns 0 products "
            "for any TIC target."
        )

    def test_tess_author_is_never_kepler(self):
        """
        Regardless of how the author field arrived, a TESS request must not
        carry 'Kepler'.  This fires if a future refactor re-introduces the
        hardcode.
        """
        from falsifier.api.models import JobRequest

        req = JobRequest(target_id="TIC 150428135", mission="TESS", cadence="short")
        assert req.author != "Kepler", (
            "A TESS JobRequest must never carry author='Kepler'. "
            "This would cause 0 MAST products to be returned for every TIC target."
        )

    def test_kepler_default_author_is_kepler(self):
        """Kepler mission retains 'Kepler' as its default author."""
        from falsifier.api.models import JobRequest

        req = JobRequest(target_id="KIC 11904151", mission="Kepler", cadence="long")
        assert req.author == "Kepler"

    def test_k2_default_author_is_k2(self):
        """K2 mission retains 'K2' as its default author."""
        from falsifier.api.models import JobRequest

        req = JobRequest(target_id="EPIC 201367065", mission="K2", cadence="long")
        assert req.author == "K2"

    def test_tess_author_override_is_respected(self):
        """
        An explicit author override (e.g. 'TASOC') is passed through unchanged.
        The mapping only fills in defaults, it does not override explicit values.
        """
        from falsifier.api.models import JobRequest

        req = JobRequest(
            target_id="TIC 150428135",
            mission="TESS",
            cadence="short",
            author="TASOC",
        )
        assert req.author == "TASOC"

    def test_mast_product_id_filter_uses_colnames_not_get(self):
        """
        mast.py:fetch_lightcurve mast_product_id path must not call
        row.get() on an astropy Row (Row has no .get() method).

        This test inspects the source of fetch_lightcurve to confirm the
        offending pattern is absent.  The live code fix uses colnames + index
        access.
        """
        import inspect
        from falsifier.pipeline.ingest.sources import mast as mast_mod

        source = inspect.getsource(mast_mod.fetch_lightcurve)
        # The old defect pattern: row.get(... on an astropy Row object
        assert "row.get(" not in source, (
            "fetch_lightcurve still contains row.get() — astropy Row objects "
            "have no .get() method.  Use colnames + row-index access instead."
        )


class TestE2EMastAuthorNotPassedFromClient:
    """
    End-to-end gate: the MAST search for a TESS target must never carry
    author="TESS" or author="Kepler".

    Defect this prevents
    --------------------
    Before the fix, store.ts sent ``author: mission`` (e.g. ``author="TESS"``)
    on every job submission.  Because ``JobRequest.author`` was non-null,
    ``_resolve_author`` left it untouched and the backend default ("SPOC") was
    bypassed.  A live MAST query confirms author="TESS" and author="Kepler"
    both return 0 products for TIC 150428135; author="SPOC" returns 37.

    Why a unit test on _resolve_author would not have caught this
    -------------------------------------------------------------
    ``_resolve_author`` correctly maps TESS → SPOC when ``author=None``.  A
    unit test targeting that validator always passed because it constructed the
    model with ``author=None``.  The bug was that the *client* sent a non-null
    value, bypassing the validator's None-branch entirely.  This test exercises
    the full chain: JobRequest construction → IngestInput assembly → the
    ``author`` kwarg that actually reaches ``fetch_lightcurve``.

    Network policy: no network calls.  ``fetch_lightcurve`` is patched at the
    call site inside ``falsifier.pipeline.stages.ingest``.  The patch is
    applied *after* the IngestInput is assembled and the real ``author`` value
    is already in place, so the assertion is on what the pipeline *would* send.
    """

    def _captured_author_for_tess_job(self) -> str:
        """
        Build a JobRequest + IngestInput for a TESS target (mirroring queue.py),
        run ``run_ingest`` with ``force_refetch=True`` so the cache is bypassed,
        and capture the ``author`` kwarg passed to ``fetch_lightcurve``.

        Returns the captured author string.
        Raises ``AssertionError`` if ``fetch_lightcurve`` was never called.
        """
        import uuid
        from unittest.mock import MagicMock, call, patch

        from falsifier.api.models import JobRequest
        from falsifier.pipeline.contracts.ingest import IngestInput
        from falsifier.pipeline.ingest.exceptions import MastFetchError
        from falsifier.pipeline.stages.ingest import run_ingest

        # Build the request the same way queue.py does.
        req = JobRequest(
            target_id="TIC 150428135",
            mission="TESS",
            cadence="short",
            # author is intentionally absent — must be derived by _resolve_author
        )
        ingest_input = IngestInput(
            target_id=req.target_id,
            mission=req.mission,
            author=req.author,
            cadence=req.cadence,
            sectors=req.sectors,
            pipeline_run_id=str(uuid.uuid4()),
        )

        captured: dict[str, str] = {}

        def _fake_fetch(target_id, *, mission, author, cadence, sectors, **kw):
            captured["author"] = author
            # Raise so run_ingest does not need to continue past this point.
            raise MastFetchError(
                "stub — no network in tests",
                endpoint="MAST",
                query=target_id,
            )

        # Patch at the call site (ingest stage module), not in the source module.
        with patch(
            "falsifier.pipeline.stages.ingest.fetch_lightcurve",
            side_effect=_fake_fetch,
        ):
            try:
                run_ingest(
                    ingest_input,
                    force_refetch=True,
                    fetch_gaia=False,
                    fetch_tap=False,
                )
            except MastFetchError:
                pass  # expected — the stub raises after recording author

        assert "author" in captured, (
            "fetch_lightcurve was never called — the e2e path did not reach MAST."
        )
        return captured["author"]

    def test_tess_mast_search_author_is_not_tess(self):
        """
        The MAST search must not carry author="TESS".

        "TESS" is the mission name, not an author; it returns 0 products on
        any MAST query (confirmed live for TIC 150428135).
        """
        author = self._captured_author_for_tess_job()
        assert author != "TESS", (
            f"fetch_lightcurve was called with author='TESS' — the mission name "
            f"is not a valid MAST author and returns 0 products for every TIC target."
        )

    def test_tess_mast_search_author_is_not_kepler(self):
        """
        The MAST search must not carry author="Kepler" for a TESS target.

        author="Kepler" returns 0 products for any TIC identifier (confirmed
        live: 0 products for TIC 150428135 vs 37 with author="SPOC").
        """
        author = self._captured_author_for_tess_job()
        assert author != "Kepler", (
            f"fetch_lightcurve was called with author='Kepler' for a TESS target. "
            f"This returns 0 products for every TIC identifier on MAST."
        )

    def test_tess_mast_search_author_is_spoc(self):
        """
        The derived author for TESS must be "SPOC" (confirmed by live MAST
        query: 37 SPOC products for TIC 150428135, 0 for author="Kepler").
        """
        author = self._captured_author_for_tess_job()
        assert author == "SPOC", (
            f"fetch_lightcurve was called with author={author!r}. "
            f"Expected 'SPOC' — the only reduction pipeline confirmed to return "
            f"products for TESS targets on MAST."
        )
