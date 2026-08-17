"""
tests/pipeline/stages/test_ingest.py
=====================================
Unit tests for the ingest stage body and its dependencies:

  - Cache hit / miss
  - max_age path (stale artifact returned as miss / raises in offline mode)
  - time-system extraction from Kepler and TESS FITS headers
  - Typed exception on bad target name (TargetNotFoundError)
  - Offline mode raises IngestError on cache miss
  - Retired TAP table reference raises ValueError
  - run_ingest with injected _segments (test-bypass path)
"""

from __future__ import annotations

import datetime
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from astropy.io import fits


# ---------------------------------------------------------------------------
# Helpers: build minimal in-memory FITS files for time-system tests
# ---------------------------------------------------------------------------

def _make_kepler_fits(n: int = 10) -> bytes:
    """Minimal Kepler-format FITS: TIMESYS=TDB, TELESCOP=Kepler, TIMEUNIT=d."""
    time_arr = np.arange(n, dtype=np.float64)
    flux_arr = np.ones(n, dtype=np.float64)
    err_arr = np.full(n, 0.01, dtype=np.float64)
    qual_arr = np.zeros(n, dtype=np.int32)

    col_time = fits.Column(name="TIME", format="D", array=time_arr, unit="d")
    col_flux = fits.Column(name="FLUX", format="D", array=flux_arr, unit="electron / s")
    col_err = fits.Column(name="FLUX_ERR", format="D", array=err_arr, unit="electron / s")
    col_qual = fits.Column(name="QUALITY", format="J", array=qual_arr)

    hdr = fits.Header()
    hdr["TIMESYS"] = "TDB"
    hdr["TELESCOP"] = "Kepler"
    hdr["TIMEUNIT"] = "d"
    hdr["QUARTER"] = 3

    primary = fits.PrimaryHDU(header=hdr)
    table = fits.BinTableHDU.from_columns(
        [col_time, col_flux, col_err, col_qual], header=hdr
    )
    hdul = fits.HDUList([primary, table])
    buf = io.BytesIO()
    hdul.writeto(buf)
    return buf.getvalue()


def _make_tess_fits(n: int = 10) -> bytes:
    """Minimal TESS-format FITS: TIMESYS=TDB, TELESCOP=TESS, TIMEUNIT=d."""
    time_arr = np.arange(n, dtype=np.float64) + 1500.0
    flux_arr = np.ones(n, dtype=np.float64)
    err_arr = np.full(n, 0.01, dtype=np.float64)
    qual_arr = np.zeros(n, dtype=np.int32)

    col_time = fits.Column(name="TIME", format="D", array=time_arr, unit="d")
    col_flux = fits.Column(name="FLUX", format="D", array=flux_arr, unit="dimensionless")
    col_err = fits.Column(name="FLUX_ERR", format="D", array=err_arr, unit="dimensionless")
    col_qual = fits.Column(name="QUALITY", format="J", array=qual_arr)

    hdr = fits.Header()
    hdr["TIMESYS"] = "TDB"
    hdr["TELESCOP"] = "TESS"
    hdr["TIMEUNIT"] = "d"
    hdr["SECTOR"] = 5

    primary = fits.PrimaryHDU(header=hdr)
    table = fits.BinTableHDU.from_columns(
        [col_time, col_flux, col_err, col_qual], header=hdr
    )
    hdul = fits.HDUList([primary, table])
    buf = io.BytesIO()
    hdul.writeto(buf)
    return buf.getvalue()


def _make_fits_no_timesys(n: int = 5) -> bytes:
    """FITS with neither TIMESYS nor TELESCOP — should trigger HeaderMissingKeyError."""
    time_arr = np.arange(n, dtype=np.float64)
    col_time = fits.Column(name="TIME", format="D", array=time_arr)
    hdr = fits.Header()
    # Deliberately omit TIMESYS and TELESCOP
    primary = fits.PrimaryHDU()
    table = fits.BinTableHDU.from_columns([col_time], header=hdr)
    hdul = fits.HDUList([primary, table])
    buf = io.BytesIO()
    hdul.writeto(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Time-system extraction
# ---------------------------------------------------------------------------

class TestTimeSystemExtraction:
    def test_kepler_header_gives_bkjd(self):
        from falsifier.pipeline.ingest.sources.mast import extract_time_system

        fits_bytes = _make_kepler_fits()
        with fits.open(io.BytesIO(fits_bytes)) as hdul:
            hdr = hdul[0].header

        time_scale, time_format = extract_time_system(hdr, "test_kepler.fits")
        assert time_scale == "tdb"
        assert time_format == "bkjd"

    def test_tess_header_gives_btjd(self):
        from falsifier.pipeline.ingest.sources.mast import extract_time_system

        fits_bytes = _make_tess_fits()
        with fits.open(io.BytesIO(fits_bytes)) as hdul:
            hdr = hdul[0].header

        time_scale, time_format = extract_time_system(hdr, "test_tess.fits")
        assert time_scale == "tdb"
        assert time_format == "btjd"

    def test_raises_on_missing_timesys(self):
        from falsifier.pipeline.ingest.exceptions import HeaderMissingKeyError
        from falsifier.pipeline.ingest.sources.mast import extract_time_system

        fits_bytes = _make_fits_no_timesys()
        with fits.open(io.BytesIO(fits_bytes)) as hdul:
            hdr = hdul[0].header

        with pytest.raises(HeaderMissingKeyError) as exc_info:
            extract_time_system(hdr, "no_timesys.fits")
        assert exc_info.value.key == "TIMESYS"
        assert "no_timesys.fits" in exc_info.value.fits_path

    def test_time_fmt_header_takes_priority(self):
        """Explicit TIME_FMT header takes priority over TELESCOP lookup."""
        from falsifier.pipeline.ingest.sources.mast import extract_time_system

        hdr = fits.Header()
        hdr["TIMESYS"] = "TDB"
        hdr["TELESCOP"] = "Kepler"   # would give bkjd normally
        hdr["TIME_FMT"] = "JD"       # but explicit header overrides

        time_scale, time_format = extract_time_system(hdr, "explicit.fits")
        assert time_scale == "tdb"
        assert time_format == "jd"


# ---------------------------------------------------------------------------
# IngestCache
# ---------------------------------------------------------------------------

class TestIngestCache:
    def test_cache_miss_returns_none(self, tmp_path):
        from falsifier.pipeline.ingest.cache import IngestCache

        cache = IngestCache(tmp_path)
        result = cache.get("nonexistent query", ".fits")
        assert result is None

    def test_put_then_get_returns_hit(self, tmp_path):
        from falsifier.pipeline.ingest.cache import IngestCache

        cache = IngestCache(tmp_path)
        data = b"FITS_DATA_PLACEHOLDER"
        query = "mast:Kepler:Kepler:long:KIC 11904151:sectors=3"

        path, manifest = cache.put(
            query,
            ".fits",
            data,
            source_doi="10.17909/t9-st5g-3177",
            source_url="mast:Kepler/url/public/lightcurves/example.fits",
            access_date=datetime.date(2024, 1, 1),
            row_count=1000,
            description="Test Kepler-10 Q3",
        )

        assert path.exists()
        assert manifest["source_doi"] == "10.17909/t9-st5g-3177"
        assert manifest["row_count"] == 1000

        # Now get it
        hit = cache.get(query, ".fits")
        assert hit is not None
        returned_path, returned_manifest, retrieved_at = hit
        assert returned_path == path
        assert returned_manifest["source_doi"] == "10.17909/t9-st5g-3177"

    def test_cache_hit_sha256_integrity(self, tmp_path):
        from falsifier.pipeline.ingest.cache import IngestCache, _sidecar_path

        cache = IngestCache(tmp_path)
        query = "integrity_test_query"
        data = b"original_data"

        path, _ = cache.put(
            query, ".fits", data,
            source_doi="10.0/test",
            source_url="http://example.com",
            access_date=datetime.date(2024, 1, 1),
            row_count=1,
            description="test",
        )

        # Tamper with the file
        path.write_bytes(b"tampered_data")

        from falsifier.pipeline.ingest.exceptions import CacheCorruptedError
        with pytest.raises(CacheCorruptedError):
            cache.get(query, ".fits")

    def test_max_age_stale_returns_none(self, tmp_path):
        """Artifact older than max_age returns None (allows refetch)."""
        from falsifier.pipeline.ingest.cache import IngestCache
        import time as _time

        cache = IngestCache(tmp_path)
        query = "max_age_test"
        cache.put(
            query, ".fits", b"data",
            source_doi="10.0/test",
            source_url="",
            access_date=datetime.date(2024, 1, 1),
            row_count=1,
            description="test",
        )

        # Set max_age to a negative timedelta so anything is stale
        very_short = datetime.timedelta(seconds=-1)
        result = cache.get(query, ".fits", max_age=very_short, offline=False)
        assert result is None  # stale → miss

    def test_max_age_stale_offline_raises(self, tmp_path):
        """Stale artifact + offline=True must raise StaleArtifactError."""
        from falsifier.pipeline.ingest.cache import IngestCache
        from falsifier.pipeline.ingest.exceptions import StaleArtifactError

        cache = IngestCache(tmp_path)
        query = "stale_offline_test"
        cache.put(
            query, ".fits", b"data",
            source_doi="10.0/test",
            source_url="",
            access_date=datetime.date(2024, 1, 1),
            row_count=1,
            description="test",
        )

        very_short = datetime.timedelta(seconds=-1)
        with pytest.raises(StaleArtifactError):
            cache.get(query, ".fits", max_age=very_short, offline=True)

    @pytest.mark.no_network
    def test_offline_cache_miss_raises(self, tmp_path):
        """Cache miss in offline mode must raise IngestError."""
        from falsifier.pipeline.ingest.cache import IngestCache
        from falsifier.pipeline.ingest.exceptions import IngestError

        cache = IngestCache(tmp_path)
        with pytest.raises(IngestError, match="offline mode"):
            cache.get("not_in_cache", ".fits", offline=True)

    def test_sidecar_has_required_fields(self, tmp_path):
        """Every sidecar must contain source_doi, source_url, access_date, row_count."""
        from falsifier.pipeline.ingest.cache import IngestCache, _sidecar_path

        cache = IngestCache(tmp_path)
        query = "sidecar_fields_test"
        path, manifest = cache.put(
            query, ".fits", b"x",
            source_doi="10.1234/example",
            source_url="https://example.com/data.fits",
            access_date=datetime.date(2024, 6, 1),
            row_count=500,
            description="sidecar test",
        )

        sidecar = _sidecar_path(path)
        with open(sidecar) as f:
            data = json.load(f)

        assert data["source_doi"] == "10.1234/example"
        assert data["source_url"] == "https://example.com/data.fits"
        assert data["access_date"] == "2024-06-01"
        assert data["row_count"] == 500
        assert "retrieved_at" in data

    def test_normalised_query_gives_same_hash(self, tmp_path):
        """Semantically identical queries with different whitespace share a hash."""
        from falsifier.pipeline.ingest.cache import query_hash

        h1 = query_hash("mast:Kepler:Kepler:long:KIC 11904151:sectors=3")
        h2 = query_hash("  mast:Kepler:Kepler:long:KIC 11904151:sectors=3  ")
        assert h1 == h2

    def test_different_queries_give_different_hashes(self, tmp_path):
        from falsifier.pipeline.ingest.cache import query_hash

        h1 = query_hash("mast:Kepler:Kepler:long:KIC 11904151:sectors=3")
        h2 = query_hash("mast:Kepler:Kepler:long:KIC 11904151:sectors=4")
        assert h1 != h2


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------

class TestTypedExceptions:
    def test_fetch_error_carries_endpoint_and_query(self):
        from falsifier.pipeline.ingest.endpoints import MAST_API_URL
        from falsifier.pipeline.ingest.exceptions import MastFetchError

        err = MastFetchError(
            "connection refused",
            endpoint=MAST_API_URL,
            query="KIC 11904151",
        )
        assert err.endpoint == MAST_API_URL
        assert err.query == "KIC 11904151"
        assert "connection refused" in str(err)
        assert "mast.stsci.edu" in str(err)

    def test_header_missing_key_error_carries_context(self):
        from falsifier.pipeline.ingest.exceptions import HeaderMissingKeyError

        err = HeaderMissingKeyError(
            "TIMESYS missing",
            fits_path="/path/to/file.fits",
            key="TIMESYS",
        )
        assert err.fits_path == "/path/to/file.fits"
        assert err.key == "TIMESYS"
        assert "TIMESYS" in str(err)

    def test_target_not_found_is_fetch_error_subclass(self):
        from falsifier.pipeline.ingest.exceptions import (
            FetchError,
            TargetNotFoundError,
        )

        err = TargetNotFoundError(
            "not found",
            endpoint="MAST",
            query="BADTARGET",
        )
        assert isinstance(err, FetchError)


# ---------------------------------------------------------------------------
# TAP table guard
# ---------------------------------------------------------------------------

class TestTapTableGuard:
    def test_retired_table_exoplanet_raises(self):
        from falsifier.pipeline.ingest.sources.tap import _guard_table

        with pytest.raises(ValueError, match="retired table"):
            _guard_table("SELECT * FROM exoplanet WHERE pl_name='Kepler-10 b'")

    def test_retired_table_exomultpars_raises(self):
        from falsifier.pipeline.ingest.sources.tap import _guard_table

        with pytest.raises(ValueError, match="retired table"):
            _guard_table("SELECT pl_name FROM exomultpars WHERE hostname='Kepler-10'")

    def test_retired_table_compositepars_raises(self):
        from falsifier.pipeline.ingest.sources.tap import _guard_table

        with pytest.raises(ValueError, match="retired table"):
            _guard_table("SELECT * FROM compositepars LIMIT 10")

    def test_approved_table_ps_passes(self):
        from falsifier.pipeline.ingest.sources.tap import _guard_table
        # Must not raise
        _guard_table("SELECT pl_name FROM ps WHERE hostname LIKE '%Kepler-10%'")

    def test_approved_table_pscomppars_passes(self):
        from falsifier.pipeline.ingest.sources.tap import _guard_table
        # Must not raise
        _guard_table("SELECT pl_name FROM pscomppars WHERE hostname LIKE '%Kepler-10%'")

    def test_invalid_table_arg_raises(self):
        from falsifier.pipeline.ingest.sources.tap import fetch_planet_params
        # fetch_planet_params validates table kwarg
        with pytest.raises(ValueError, match="not approved"):
            # This will raise before hitting the network
            fetch_planet_params.__wrapped__("Kepler-10", table="exoplanet") if hasattr(
                fetch_planet_params, "__wrapped__"
            ) else pytest.skip("Cannot test without calling network")


# ---------------------------------------------------------------------------
# run_ingest — test-bypass path
# ---------------------------------------------------------------------------

class TestRunIngestTestBypass:
    @pytest.mark.no_network
    def test_run_ingest_with_injected_segments(self, tmp_path):
        """
        run_ingest with _segments= bypass must return IngestOutput without
        hitting the network.
        """
        from falsifier.pipeline.contracts.ingest import IngestInput
        from falsifier.pipeline.contracts.manifest import UnitedArray
        from falsifier.pipeline.stages.ingest import run_ingest

        n = 10
        from falsifier.pipeline.contracts.ingest import LightCurveSegment

        seg = LightCurveSegment(
            sector=3,
            time=UnitedArray(values=list(range(n)), unit="bkjd"),
            time_scale="tdb",
            time_format="bkjd",
            flux=UnitedArray(values=[1.0] * n, unit="electron / s"),
            flux_err=UnitedArray(values=[0.01] * n, unit="electron / s"),
            quality_flags=[0] * n,
            cadence_type="long",
        )

        inp = IngestInput(
            target_id="KIC 11904151",
            mission="Kepler",
            author="Kepler",
            cadence="long",
            sectors=[3],
            pipeline_run_id="bypass-test",
        )

        out = run_ingest(
            inp,
            cache_root=tmp_path / "cache",
            offline=True,
            _segments=[seg],
            _stellar_params=None,
        )

        assert out.host_star_id == "KIC 11904151"
        assert len(out.segments) == 1
        assert out.segments[0].time_scale == "tdb"
        assert out.segments[0].time_format == "bkjd"
        assert out.manifest.stage == "ingest"

    @pytest.mark.no_network
    def test_run_ingest_normalises_host_star_id(self, tmp_path):
        """host_star_id is normalised to canonical form."""
        from falsifier.pipeline.contracts.ingest import IngestInput, LightCurveSegment
        from falsifier.pipeline.contracts.manifest import UnitedArray
        from falsifier.pipeline.stages.ingest import run_ingest

        n = 5
        seg = LightCurveSegment(
            sector=3,
            time=UnitedArray(values=list(range(n)), unit="bkjd"),
            time_scale="tdb",
            time_format="bkjd",
            flux=UnitedArray(values=[1.0] * n, unit="electron / s"),
            flux_err=UnitedArray(values=[0.01] * n, unit="electron / s"),
            quality_flags=[0] * n,
            cadence_type="long",
        )

        inp = IngestInput(
            target_id="kic11904151",  # non-canonical form
            mission="Kepler",
            author="Kepler",
            cadence="long",
            sectors=[3],
            pipeline_run_id="normalise-test",
        )

        out = run_ingest(inp, cache_root=tmp_path / "cache", offline=True, _segments=[seg])
        assert out.host_star_id == "KIC 11904151"

    @pytest.mark.no_network
    def test_run_ingest_manifest_has_correct_stage(self, tmp_path):
        from falsifier.pipeline.contracts.ingest import IngestInput, LightCurveSegment
        from falsifier.pipeline.contracts.manifest import UnitedArray
        from falsifier.pipeline.stages.ingest import run_ingest

        n = 5
        seg = LightCurveSegment(
            sector=1,
            time=UnitedArray(values=list(range(n)), unit="btjd"),
            time_scale="tdb",
            time_format="btjd",
            flux=UnitedArray(values=[1.0] * n, unit="dimensionless"),
            flux_err=UnitedArray(values=[0.001] * n, unit="dimensionless"),
            quality_flags=[0] * n,
            cadence_type="short",
        )
        inp = IngestInput(
            target_id="TIC 261136679",
            mission="TESS",
            author="SPOC",
            cadence="short",
            sectors=[1],
            pipeline_run_id="tess-test",
        )

        out = run_ingest(inp, cache_root=tmp_path / "cache", offline=True, _segments=[seg])
        assert out.manifest.stage == "ingest"
        assert out.manifest.code_version == "0.1.0-dev"
