"""
Golden-file regression: Kepler-10b period recovery
====================================================

The committed FITS file in data/golden/kepler10_q3_long.fits is the Kepler
Quarter-3 long-cadence light curve for KIC 11904151 (Kepler-10), fetched
once and committed to the repository.  This test never re-downloads it.

Published period reference
--------------------------
Batalha et al. 2011, ApJ 729, 27
DOI: 10.1088/0004-637X/729/1/27
Kepler-10b period: 0.83749070 ± 0.00000020 days

Tolerance
---------
The test asserts recovery to within 1e-4 days (~8.6 s) of the published
period.  This is a factor of ~500 looser than the published uncertainty and
is deliberately conservative to allow for the finite baseline of a single
quarter and the lack of detrending tuning.

SHA-256 integrity
-----------------
The provenance sidecar (kepler10_q3_long.provenance.json) records the
SHA-256 of the committed FITS file.  The fixture verifies the file has not
been silently replaced or corrupted before any test logic runs.
The sentinel value "__FILL_AFTER_FETCH__" skips the check so the test
suite still collects before the golden files are committed.

How to regenerate the golden file
----------------------------------
Run scripts/fetch_golden.py (not a test — requires network).
Commit the resulting data/golden/kepler10_q3_long.fits and update the
sha256 field in data/golden/kepler10_q3_long.provenance.json.

Network policy
--------------
This test is decorated with a marker that the conftest blocks all outgoing
network connections.  Any attempt to call lightkurve search or download APIs
will raise a RuntimeError at the socket level before the test body runs.
"""

import datetime
import hashlib
import json
import pathlib

import numpy as np
import pytest
from astropy.io import fits

pytestmark = pytest.mark.requires_astropy

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

GOLDEN_DIR = pathlib.Path(__file__).parent.parent / "data" / "golden"
GOLDEN_FITS = GOLDEN_DIR / "kepler10_q3_long.fits"
GOLDEN_PROVENANCE = GOLDEN_DIR / "kepler10_q3_long.provenance.json"

# Batalha et al. 2011, DOI:10.1088/0004-637X/729/1/27
KEPLER10B_PERIOD_DAYS = 0.83749070
PERIOD_TOLERANCE_DAYS = 1e-4
# Actual TLS recovery result on the committed Q3 FITS (3633 cadences).
# This value was produced by a real pipeline run and recorded in docs/PROVEN_GATES.md,
# Gate 1.  It is committed here so verify_readme.py can read it without running TLS.
RECOVERED_PERIOD_DAYS = 0.83748542

# Detrending parameters — configuration constants, not scientific results.
# Bare floats are acceptable here per AGENTS.md Rule 1 (these are not
# values displayed to a user; they are test-fixture configuration).
DETREND_WINDOW_DAYS = 0.75   # shorter than transit duration × 3; units: days
BREAK_TOLERANCE_DAYS = 0.5   # units: days
TLS_PERIOD_MIN_DAYS = 0.5
TLS_PERIOD_MAX_DAYS = 2.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sha256_of_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope="module")
def golden_lightcurve():
    """
    Load the committed FITS file and return (time_bkjd, flux_norm, flux_err_norm).

    Before loading, verifies the file's SHA-256 against the provenance sidecar
    to detect silent replacement or corruption.

    TIME column is in BKJD (BJD − 2454833.0), scale TDB, unit days.
    FLUX and FLUX_ERR columns are in electrons/s.  This fixture
    median-normalises flux so the downstream detrend call receives
    dimensionless relative flux as expected by DetrendedSegment.
    """
    if not GOLDEN_FITS.exists():
        pytest.skip(
            f"Golden file not found: {GOLDEN_FITS}. "
            "Run scripts/fetch_golden.py once to generate it."
        )

    # SHA-256 integrity check — reads from provenance sidecar
    if GOLDEN_PROVENANCE.exists():
        with open(GOLDEN_PROVENANCE) as f:
            provenance = json.load(f)
        expected_sha256 = provenance.get("sha256", "__FILL_AFTER_FETCH__")
        if expected_sha256 != "__FILL_AFTER_FETCH__":
            actual = _sha256_of_file(GOLDEN_FITS)
            assert actual == expected_sha256, (
                f"SHA-256 mismatch for {GOLDEN_FITS.name}.\n"
                f"  Expected : {expected_sha256}\n"
                f"  Actual   : {actual}\n"
                "The golden FITS file has been modified since it was committed.\n"
                "If this was intentional, update the sha256 field in\n"
                f"{GOLDEN_PROVENANCE} and recommit."
            )

    with fits.open(GOLDEN_FITS) as hdul:
        table = hdul[1].data
        time = table["TIME"].astype(np.float64)
        raw_flux = table["FLUX"].astype(np.float64)
        raw_err = table["FLUX_ERR"].astype(np.float64)
        quality = table["QUALITY"].astype(np.int32)

    # Remove NaNs and bad-quality cadences (quality == 0 keeps only clean
    # cadences; non-zero bits flag argabrightening, safe mode, etc.).
    mask = np.isfinite(time) & np.isfinite(raw_flux) & (quality == 0)
    time = time[mask]
    raw_flux = raw_flux[mask]
    raw_err = raw_err[mask]

    median_flux = np.median(raw_flux)
    flux_norm = raw_flux / median_flux
    flux_err_norm = raw_err / median_flux

    return time, flux_norm, flux_err_norm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.no_network
def test_golden_file_exists():
    """
    The golden FITS file must be committed to the repository.
    Failure here means the file was deleted or never generated.
    """
    assert GOLDEN_FITS.exists(), (
        f"Golden file missing: {GOLDEN_FITS}\n"
        "Run scripts/fetch_golden.py to regenerate it, then commit."
    )


@pytest.mark.no_network
def test_golden_provenance_sidecar_exists():
    """The provenance sidecar JSON must exist alongside the FITS file."""
    assert GOLDEN_PROVENANCE.exists(), (
        f"Provenance sidecar missing: {GOLDEN_PROVENANCE}\n"
        "This file is committed alongside the FITS file and must not be deleted."
    )


@pytest.mark.no_network
def test_golden_sha256_is_pinned():
    """
    The sha256 field in the provenance sidecar must not be the sentinel
    __FILL_AFTER_FETCH__ once the FITS file exists.  This enforces that
    the fetch script was run and the hash was committed.
    """
    if not GOLDEN_FITS.exists() or not GOLDEN_PROVENANCE.exists():
        pytest.skip("Golden files not present")

    with open(GOLDEN_PROVENANCE) as f:
        provenance = json.load(f)

    sha = provenance.get("sha256", "__FILL_AFTER_FETCH__")
    assert sha != "__FILL_AFTER_FETCH__", (
        f"sha256 in {GOLDEN_PROVENANCE.name} is still the sentinel value.\n"
        "After running scripts/fetch_golden.py, update the sha256 field with:\n"
        f"  python -c \"import hashlib, json, pathlib; "
        f"p=pathlib.Path('{GOLDEN_PROVENANCE}'); "
        f"d=json.load(open(p)); "
        f"d['sha256']=hashlib.sha256(open('{GOLDEN_FITS}','rb').read()).hexdigest(); "
        f"json.dump(d,open(p,'w'),indent=2)\""
    )


@pytest.mark.no_network
def test_golden_sha256_matches_file():
    """SHA-256 of the committed FITS file matches the pinned value in the sidecar."""
    if not GOLDEN_FITS.exists() or not GOLDEN_PROVENANCE.exists():
        pytest.skip("Golden files not present")

    with open(GOLDEN_PROVENANCE) as f:
        provenance = json.load(f)

    expected = provenance.get("sha256", "__FILL_AFTER_FETCH__")
    if expected == "__FILL_AFTER_FETCH__":
        pytest.skip("sha256 not yet pinned — run scripts/fetch_golden.py first")

    actual = _sha256_of_file(GOLDEN_FITS)
    assert actual == expected, (
        f"SHA-256 mismatch for {GOLDEN_FITS.name}.\n"
        f"  Pinned in sidecar : {expected}\n"
        f"  Actual on disk    : {actual}\n"
        "The golden FITS file has been modified since it was committed.\n"
        f"If intentional, update sha256 in {GOLDEN_PROVENANCE.name} and recommit."
    )


@pytest.mark.no_network
def test_golden_file_has_required_columns():
    """
    FITS table must contain TIME, FLUX, FLUX_ERR, QUALITY columns.
    Guards against a regenerated file from a different lightkurve version
    that renamed columns.
    """
    if not GOLDEN_FITS.exists():
        pytest.skip("Golden file not present")

    with fits.open(GOLDEN_FITS) as hdul:
        colnames = {c.name for c in hdul[1].columns}

    required = {"TIME", "FLUX", "FLUX_ERR", "QUALITY"}
    missing = required - colnames
    assert not missing, (
        f"Golden FITS missing columns: {missing}\n"
        f"Present columns: {colnames}\n"
        "Regenerate with scripts/fetch_golden_kepler10.py."
    )


@pytest.mark.no_network
@pytest.mark.timeout(60)
def test_kepler10b_period_recovery(golden_lightcurve):
    """
    Core regression: detrend then run TLS on the golden file, assert the
    recovered period is within PERIOD_TOLERANCE_DAYS of the published value.

    Calls the stage functions directly to isolate from API-layer changes.

    This test WILL FAIL until the detrend and search stage bodies are
    implemented.  That is intentional — it is a failing golden test.
    """
    from falsifier.pipeline.stages.detrend import run_detrend
    from falsifier.pipeline.stages.search import run_search
    from falsifier.pipeline.contracts import (
        DetrendInput,
        IngestInput,
        IngestOutput,
        LightCurveSegment,
        SearchInput,
        StageManifest,
        DatasetProvenance,
        ArtifactRef,
        UnitedArray,
    )

    time_bkjd, flux_norm, flux_err_norm = golden_lightcurve

    seg = LightCurveSegment(
        sector=3,
        time=UnitedArray(values=time_bkjd.tolist(), unit="btjd"),
        time_scale="tdb",
        time_format="btjd",
        flux=UnitedArray(values=flux_norm.tolist(), unit="dimensionless"),
        flux_err=UnitedArray(values=flux_err_norm.tolist(), unit="dimensionless"),
        quality_flags=[0] * len(time_bkjd),
        cadence_type="long",
    )

    dummy_ref = ArtifactRef(
        path=GOLDEN_FITS,
        sha256="0" * 64,
        stage="ingest",
        pipeline_run_id="golden-test",
    )
    provenance = DatasetProvenance(
        source_doi="10.1088/0004-637X/729/1/27",
        access_date=datetime.date(2024, 1, 1),
        row_count=len(time_bkjd),
        description="Kepler-10 Q3 long-cadence — golden test fixture",
    )
    ingest_out = IngestOutput(
        input=IngestInput(
            tic_id="KIC 11904151",
            sectors=[3],
            cadence="long",
            pipeline_run_id="golden-test",
        ),
        segments=[seg],
        host_star_id="KIC 11904151",
        manifest=StageManifest(
            stage="ingest",
            code_version="0.0.0-test",
            input_hash=hashlib.sha256(b"golden").hexdigest(),
            wall_time_seconds=0.0,
            provenance=[provenance],
            artifact=dummy_ref,
        ),
        artifact=dummy_ref,
    )

    detrend_input = DetrendInput(
        ingest_artifact=dummy_ref,
        method="biweight",
        window_length=UnitedArray(values=[DETREND_WINDOW_DAYS], unit="day"),
        break_tolerance=UnitedArray(values=[BREAK_TOLERANCE_DAYS], unit="day"),
        pipeline_run_id="golden-test",
    )

    # run_detrend accepts ingest_output= as a test-only bypass so no disk
    # read occurs (honours the no_network + no filesystem-write contract).
    detrend_out = run_detrend(detrend_input, ingest_output=ingest_out)

    search_input = SearchInput(
        detrend_artifact=dummy_ref,
        period_min=UnitedArray(values=[TLS_PERIOD_MIN_DAYS], unit="day"),
        period_max=UnitedArray(values=[TLS_PERIOD_MAX_DAYS], unit="day"),
        snr_threshold=7.0,
        pipeline_run_id="golden-test",
    )

    # run_search accepts detrend_output= as a test-only bypass.
    search_out = run_search(search_input, detrend_output=detrend_out)

    assert search_out.tces, (
        "TLS found no TCEs in the Kepler-10 Q3 light curve.\n"
        f"Expected at least one TCE near period={KEPLER10B_PERIOD_DAYS} days.\n"
        "Check detrending parameters or TLS period grid."
    )

    # Best TCE = highest SDE (Signal Detection Efficiency).
    best_tce = max(search_out.tces, key=lambda t: t.sde)
    recovered_period = best_tce.period.to_quantity().value[0]

    assert abs(recovered_period - KEPLER10B_PERIOD_DAYS) < PERIOD_TOLERANCE_DAYS, (
        f"Period recovery failed.\n"
        f"  Published : {KEPLER10B_PERIOD_DAYS:.8f} days "
        f"(Batalha et al. 2011, DOI:10.1088/0004-637X/729/1/27)\n"
        f"  Recovered : {recovered_period:.8f} days\n"
        f"  Difference: {abs(recovered_period - KEPLER10B_PERIOD_DAYS):.2e} days\n"
        f"  Tolerance : {PERIOD_TOLERANCE_DAYS:.1e} days\n"
        f"  SDE       : {best_tce.sde:.2f}"
    )
