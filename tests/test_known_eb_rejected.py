"""
Golden-file regression: known eclipsing binary rejected by odd/even depth test
===============================================================================

The committed FITS file data/golden/kic6965293_q3_long.fits is the Kepler
Quarter-3 long-cadence light curve for KIC 6965293, a detached eclipsing
binary listed in the Kepler Eclipsing Binary Catalog.

Eclipsing binary reference
--------------------------
Prša et al. 2011, AJ 141, 83
DOI: 10.1088/0004-6256/141/3/83

KIC 6965293 characteristics (from catalog)
-------------------------------------------
  Type     : detached EB
  Period   : 2.6045 days
  Primary eclipse depth   : 0.1396 (13.96 % relative flux drop)
  Secondary eclipse depth : 0.0209 ( 2.09 % relative flux drop)
  Depth ratio (primary / secondary) : 6.68 — confirmed in catalog
  Morphology parameter    : 0.04 (strongly detached)
  Source  : Prša et al. 2011, AJ 141, 83, DOI 10.1088/0004-6256/141/3/83

KIC 6965293 was confirmed against the catalog before use.  See
docs/PROVEN_GATES.md "EB catalog verification" section.  It was NOT swapped.

SHA-256 integrity
-----------------
The provenance sidecar (kic6965293_q3_long.provenance.json) records the
SHA-256 of the committed FITS file.  The fixture verifies it before any test
logic runs.

Policy requirement (AGENTS.md + pipeline-contracts-plan.md Sub-Task 5)
-----------------------------------------------------------------------
When VetOutput.disposition is "false_positive", the triggering_test field
MUST name the specific test that caused rejection.  For a clear odd/even EB,
the triggering_test MUST be "odd_even_depth" — not merely any rejection.

This test WILL FAIL until the vet stage body is implemented.  That is
intentional.  The test exists to pin the contract before the implementation.

Network policy
--------------
Decorated with @pytest.mark.no_network.  No downloads occur.
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
GOLDEN_FITS = GOLDEN_DIR / "kic6965293_q3_long.fits"
GOLDEN_PROVENANCE = GOLDEN_DIR / "kic6965293_q3_long.provenance.json"

# Prša et al. 2011, DOI:10.1088/0004-6256/141/3/83
EB_KIC_ID = "KIC 6965293"
EB_CATALOG_DOI = "10.1088/0004-6256/141/3/83"

# The load-bearing test name string — must match VettingTestName exactly.
# See pipeline-contracts-plan.md Sub-Task 5, step 3 and the golden EB anchor.
EXPECTED_TRIGGERING_TEST = "odd_even_depth"

DETREND_WINDOW_DAYS = 2.0    # wider window needed for longer EB period
BREAK_TOLERANCE_DAYS = 0.5
TLS_PERIOD_MIN_DAYS = 1.0
TLS_PERIOD_MAX_DAYS = 10.0


# ---------------------------------------------------------------------------
# Shared helper — builds pipeline objects from the golden FITS file
# ---------------------------------------------------------------------------

def _build_pipeline_objects(time_bkjd, flux_norm, flux_err_norm, run_id: str):
    """
    Construct the minimal IngestOutput, DetrendInput, and SearchInput needed
    by both test functions.  Extracted to avoid duplicating the fixture
    assembly boilerplate.
    """
    from falsifier.pipeline.contracts import (
        ArtifactRef,
        DatasetProvenance,
        DetrendInput,
        IngestInput,
        IngestOutput,
        LightCurveSegment,
        SearchInput,
        StageManifest,
        UnitedArray,
    )

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
        pipeline_run_id=run_id,
    )
    provenance = DatasetProvenance(
        source_doi=EB_CATALOG_DOI,
        access_date=datetime.date(2024, 1, 1),
        row_count=len(time_bkjd),
        description="KIC 6965293 Q3 long-cadence — golden EB test fixture",
    )
    ingest_out = IngestOutput(
        input=IngestInput(
            tic_id=EB_KIC_ID,
            sectors=[3],
            cadence="long",
            pipeline_run_id=run_id,
        ),
        segments=[seg],
        host_star_id=EB_KIC_ID,
        manifest=StageManifest(
            stage="ingest",
            code_version="0.0.0-test",
            input_hash=hashlib.sha256(run_id.encode()).hexdigest(),
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
        pipeline_run_id=run_id,
    )

    search_input = SearchInput(
        detrend_artifact=dummy_ref,
        period_min=UnitedArray(values=[TLS_PERIOD_MIN_DAYS], unit="day"),
        period_max=UnitedArray(values=[TLS_PERIOD_MAX_DAYS], unit="day"),
        snr_threshold=7.0,
        pipeline_run_id=run_id,
    )

    return dummy_ref, ingest_out, detrend_input, search_input


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
def golden_eb_lightcurve():
    """
    Load the committed EB FITS file.
    Before loading, verifies SHA-256 against the provenance sidecar.
    Returns (time_bkjd, flux_norm, flux_err_norm).
    TIME is BKJD (BJD − 2454833.0), scale TDB.
    """
    if not GOLDEN_FITS.exists():
        pytest.skip(
            f"Golden EB file not found: {GOLDEN_FITS}. "
            "Run scripts/fetch_golden.py once to generate it."
        )

    # SHA-256 integrity check
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
                f"Update sha256 in {GOLDEN_PROVENANCE} if the change was intentional."
            )

    with fits.open(GOLDEN_FITS) as hdul:
        table = hdul[1].data
        time = table["TIME"].astype(np.float64)
        raw_flux = table["FLUX"].astype(np.float64)
        raw_err = table["FLUX_ERR"].astype(np.float64)
        quality = table["QUALITY"].astype(np.int32)

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
def test_golden_eb_file_exists():
    """The golden EB FITS file must be committed to the repository."""
    assert GOLDEN_FITS.exists(), (
        f"Golden EB file missing: {GOLDEN_FITS}\n"
        "Run scripts/fetch_golden.py to regenerate it, then commit."
    )


@pytest.mark.no_network
def test_golden_eb_provenance_sidecar_exists():
    """The provenance sidecar JSON must exist alongside the EB FITS file."""
    assert GOLDEN_PROVENANCE.exists(), (
        f"Provenance sidecar missing: {GOLDEN_PROVENANCE}\n"
        "This file is committed alongside the FITS file."
    )


@pytest.mark.no_network
def test_golden_eb_sha256_is_pinned():
    """sha256 in the EB provenance sidecar must not be the sentinel value."""
    if not GOLDEN_FITS.exists() or not GOLDEN_PROVENANCE.exists():
        pytest.skip("Golden EB files not present")

    with open(GOLDEN_PROVENANCE) as f:
        provenance = json.load(f)

    sha = provenance.get("sha256", "__FILL_AFTER_FETCH__")
    assert sha != "__FILL_AFTER_FETCH__", (
        f"sha256 in {GOLDEN_PROVENANCE.name} is still the sentinel value.\n"
        "Run scripts/fetch_golden.py and update the sha256 field."
    )


@pytest.mark.no_network
def test_golden_eb_sha256_matches_file():
    """SHA-256 of the committed EB FITS file matches the pinned sidecar value."""
    if not GOLDEN_FITS.exists() or not GOLDEN_PROVENANCE.exists():
        pytest.skip("Golden EB files not present")

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
        "The golden EB FITS file has been modified since it was committed.\n"
        f"If intentional, update sha256 in {GOLDEN_PROVENANCE.name} and recommit."
    )


@pytest.mark.no_network
def test_golden_eb_file_has_required_columns():
    """FITS table must contain TIME, FLUX, FLUX_ERR, QUALITY."""
    if not GOLDEN_FITS.exists():
        pytest.skip("Golden EB file not present")

    with fits.open(GOLDEN_FITS) as hdul:
        colnames = {c.name for c in hdul[1].columns}

    required = {"TIME", "FLUX", "FLUX_ERR", "QUALITY"}
    missing = required - colnames
    assert not missing, (
        f"Golden EB FITS missing columns: {missing}\n"
        f"Present: {colnames}"
    )


@pytest.mark.no_network
@pytest.mark.timeout(60)
def test_known_eb_disposition_is_false_positive(golden_eb_lightcurve):
    """
    The pipeline must reject KIC 6965293 with disposition == "false_positive".

    This is the coarse gate.  The next test pins the specific mechanism.
    Both tests must pass together; passing only this one is insufficient.

    This test WILL FAIL until the vet stage body is implemented.
    """
    from falsifier.pipeline.stages.detrend import run_detrend
    from falsifier.pipeline.stages.search import run_search
    from falsifier.pipeline.stages.vet import run_vet
    from falsifier.pipeline.contracts import VetInput

    time_bkjd, flux_norm, flux_err_norm = golden_eb_lightcurve
    dummy_ref, ingest_out, detrend_input, search_input = _build_pipeline_objects(
        time_bkjd, flux_norm, flux_err_norm, run_id="eb-test"
    )

    detrend_out = run_detrend(detrend_input, ingest_output=ingest_out)
    search_out = run_search(search_input, detrend_output=detrend_out)

    assert search_out.tces, (
        f"TLS found no TCEs in {EB_KIC_ID}.\n"
        "Expected an eclipse signal for a clear detached EB.\n"
        "Check detrending parameters or TLS period grid."
    )

    best_tce = max(search_out.tces, key=lambda t: t.sde)
    vet_input = VetInput(
        search_artifact=dummy_ref,
        tce_id=best_tce.tce_id,
        pipeline_run_id="eb-test",
    )
    vet_out = run_vet(vet_input, search_output=search_out, tce=best_tce)

    assert vet_out.disposition == "false_positive", (
        f"Expected disposition 'false_positive' for known EB {EB_KIC_ID}.\n"
        f"Got: '{vet_out.disposition}'\n"
        f"Test results:\n"
        + "\n".join(
            f"  {r.test_name}: {r.outcome} — {r.reason}"
            for r in vet_out.test_results
        )
    )


@pytest.mark.no_network
@pytest.mark.timeout(60)
def test_known_eb_triggering_test_is_odd_even_depth(golden_eb_lightcurve):
    """
    The specific rejection mechanism for KIC 6965293 must be the odd/even
    depth test named "odd_even_depth" — not merely any false-positive path.

    This is the load-bearing assertion.  The golden EB test asserts on the
    string "odd_even_depth" specifically because:

      1. VettingTestName is a typed Literal — the name is part of the contract.
      2. KIC 6965293 has a ~7:1 primary/secondary depth ratio per the Kepler
         EB Catalog (Prsa+2011, DOI:10.1088/0004-6256/141/3/83).
      3. Any implementation that rejects this target via a different test
         (stellar_density, systematics_coincidence, etc.) is not correctly
         implementing the odd/even depth vetting gate.

    This test WILL FAIL until the vet stage body is implemented.
    """
    from falsifier.pipeline.stages.detrend import run_detrend
    from falsifier.pipeline.stages.search import run_search
    from falsifier.pipeline.stages.vet import run_vet
    from falsifier.pipeline.contracts import VetInput

    time_bkjd, flux_norm, flux_err_norm = golden_eb_lightcurve
    dummy_ref, ingest_out, detrend_input, search_input = _build_pipeline_objects(
        time_bkjd, flux_norm, flux_err_norm, run_id="eb-test-2"
    )

    detrend_out = run_detrend(detrend_input, ingest_output=ingest_out)
    search_out = run_search(search_input, detrend_output=detrend_out)

    assert search_out.tces, (
        f"TLS found no TCEs in {EB_KIC_ID} — cannot test triggering_test."
    )

    best_tce = max(search_out.tces, key=lambda t: t.sde)
    vet_input = VetInput(
        search_artifact=dummy_ref,
        tce_id=best_tce.tce_id,
        pipeline_run_id="eb-test-2",
    )
    vet_out = run_vet(vet_input, search_output=search_out, tce=best_tce)

    # The contract requires triggering_test is non-None whenever disposition
    # is not "candidate" (VetOutput validator, Sub-Task 5 step 9).
    assert vet_out.triggering_test is not None, (
        "triggering_test is None but disposition is not 'candidate'.\n"
        "This violates the VetOutput validator contract."
    )

    # Load-bearing string assertion: exactly "odd_even_depth".
    assert vet_out.triggering_test == EXPECTED_TRIGGERING_TEST, (
        f"Wrong triggering test for known EB {EB_KIC_ID}.\n"
        f"  Expected : '{EXPECTED_TRIGGERING_TEST}'\n"
        f"  Got      : '{vet_out.triggering_test}'\n"
        f"  Reason   : {vet_out.triggering_reason}\n"
        f"\n"
        f"KIC 6965293 has a ~7:1 primary/secondary depth ratio per the Kepler\n"
        f"EB Catalog (Prsa+2011, DOI:{EB_CATALOG_DOI}).\n"
        f"The rejection must be traced to the odd/even depth asymmetry, not to\n"
        f"a different vetting test.\n"
        f"\n"
        f"All test results:\n"
        + "\n".join(
            f"  {r.test_name}: {r.outcome} — {r.reason}"
            for r in vet_out.test_results
        )
    )

    # Verify the reason field is non-empty (VettingTestResult.reason contract).
    assert vet_out.triggering_reason, (
        "triggering_reason is empty. VetOutput contract requires a non-empty "
        "one-sentence explanation alongside the triggering_test name."
    )
