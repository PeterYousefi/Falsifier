"""
Differentiator Proof: opposite dispositions for KIC 11904151 vs KIC 6965293
============================================================================

This is the CI-enforced version of the Differentiator Proof section in README.md.

The proof demonstrates that two targets with a transit-like dip in their light
curves receive opposite dispositions from the Falsifier vetting pipeline, purely
on the basis of physical tests — not signal shape:

  Target A — KIC 11904151 (Kepler-10, confirmed planet):
    Disposition: ambiguous
    (centroid and density data absent in the Q3 golden fixture; no FAIL fires)

  Target B — KIC 6965293 (detached eclipsing binary, Prša et al. 2011):
    Disposition: false_positive, triggering_test = odd_even_depth

Both targets have a measurable transit/eclipse signal; the opposite verdicts
are enforced by the vet stage logic, not by pre-filtering on depth alone.

Data provenance
---------------
Target A: KIC 11904151 Q3 FITS — Batalha et al. 2011, DOI:10.1088/0004-637X/729/1/27
Target B: KIC 6965293 Q3 FITS  — Prša et al. 2011, DOI:10.1088/0004-6256/141/3/83

Both files must be committed to data/golden/ before this test can run.

Policy compliance
-----------------
AGENTS.md Rule 1: no hardcoded scientific values.
AGENTS.md Rule 2: physical quantities carry units inside pipeline contracts.
AGENTS.md Rule 3: source_doi recorded in data/artifacts/differentiator_proof.json.
"""

from __future__ import annotations

import datetime
import hashlib
import pathlib

import numpy as np
import pytest
from astropy.io import fits

pytestmark = [pytest.mark.requires_astropy, pytest.mark.timeout(120)]

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

GOLDEN_DIR = pathlib.Path(__file__).parent.parent / "data" / "golden"

FITS_A = GOLDEN_DIR / "kepler10_q3_long.fits"       # KIC 11904151 — confirmed planet
FITS_B = GOLDEN_DIR / "kic6965293_q3_long.fits"     # KIC 6965293 — eclipsing binary

EXPECTED_DISPOSITION_A = "ambiguous"
EXPECTED_DISPOSITION_B = "false_positive"
EXPECTED_TRIGGERING_TEST_B = "odd_even_depth"

# Pipeline configuration — not scientific results
_DETREND_WINDOW_A = 0.75  # days — Kepler-10 short period
_DETREND_WINDOW_B = 2.0   # days — EB longer period
_BREAK_TOLERANCE = 0.5    # days
_PERIOD_MIN_A = 0.5       # days
_PERIOD_MAX_A = 2.0       # days
_PERIOD_MIN_B = 1.0       # days
_PERIOD_MAX_B = 10.0      # days


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run_pipeline_for_fixture(
    golden_fits: pathlib.Path,
    kic_id: str,
    source_doi: str,
    detrend_window: float,
    period_min: float,
    period_max: float,
):
    """
    Run detrend → search → vet for a single golden FITS file.
    Returns the VetOutput for the highest-SDE TCE.
    """
    with fits.open(golden_fits) as hdul:
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

    from falsifier.pipeline.contracts import (
        ArtifactRef, DatasetProvenance, DetrendInput, IngestInput,
        IngestOutput, LightCurveSegment, SearchInput, StageManifest,
        UnitedArray, VetInput,
    )
    from falsifier.pipeline.stages.detrend import run_detrend
    from falsifier.pipeline.stages.search import run_search
    from falsifier.pipeline.stages.vet import run_vet

    run_id = f"diff-proof-ci-{kic_id.replace(' ', '-')}"
    seg = LightCurveSegment(
        sector=3,
        time=UnitedArray(values=time.tolist(), unit="btjd"),
        time_scale="tdb",
        time_format="btjd",
        flux=UnitedArray(values=flux_norm.tolist(), unit="dimensionless"),
        flux_err=UnitedArray(values=flux_err_norm.tolist(), unit="dimensionless"),
        quality_flags=[0] * len(time),
        cadence_type="long",
    )
    dummy_ref = ArtifactRef(
        path=golden_fits,
        sha256="0" * 64,
        stage="ingest",
        pipeline_run_id=run_id,
    )
    provenance = DatasetProvenance(
        source_doi=source_doi,
        access_date=datetime.date(2026, 8, 26),
        row_count=int(len(time)),
        description=f"{kic_id} Q3 long-cadence — differentiator proof CI test",
    )
    ingest_out = IngestOutput(
        input=IngestInput(
            tic_id=kic_id,
            sectors=[3],
            cadence="long",
            pipeline_run_id=run_id,
        ),
        segments=[seg],
        host_star_id=kic_id,
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
        window_length=UnitedArray(values=[detrend_window], unit="day"),
        break_tolerance=UnitedArray(values=[_BREAK_TOLERANCE], unit="day"),
        pipeline_run_id=run_id,
    )
    search_input = SearchInput(
        detrend_artifact=dummy_ref,
        period_min=UnitedArray(values=[period_min], unit="day"),
        period_max=UnitedArray(values=[period_max], unit="day"),
        snr_threshold=7.0,
        pipeline_run_id=run_id,
    )

    detrend_out = run_detrend(detrend_input, ingest_output=ingest_out)
    search_out = run_search(search_input, detrend_output=detrend_out)

    assert search_out.tces, (
        f"No TCEs found for {kic_id} — cannot run vetting. "
        "Check detrending parameters or golden FITS file."
    )

    best_tce = max(search_out.tces, key=lambda t: t.sde)
    vet_input = VetInput(
        search_artifact=dummy_ref,
        tce_id=best_tce.tce_id,
        pipeline_run_id=run_id,
    )
    return run_vet(vet_input, search_output=search_out, tce=best_tce)


# ---------------------------------------------------------------------------
# Test: golden files present
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_differentiator_proof_golden_files_exist():
    """Both golden FITS files required by the Differentiator Proof must be committed."""
    assert FITS_A.exists(), (
        f"Missing golden FITS for Target A: {FITS_A}\n"
        "Run scripts/fetch_golden.py to regenerate it."
    )
    assert FITS_B.exists(), (
        f"Missing golden FITS for Target B: {FITS_B}\n"
        "Run scripts/fetch_golden.py to regenerate it."
    )


# ---------------------------------------------------------------------------
# Test: Target A (KIC 11904151) — disposition must be ambiguous
# ---------------------------------------------------------------------------

@pytest.mark.no_network
@pytest.mark.timeout(120)
def test_differentiator_proof_target_a_ambiguous():
    """
    KIC 11904151 (Kepler-10, confirmed planet) must return disposition 'ambiguous'.

    The Q3 golden fixture lacks a centroid time series, so the centroid_shift
    test is INCONCLUSIVE.  No vetting test fires FAIL, so the pipeline correctly
    returns 'ambiguous' rather than 'candidate' — honest about missing data.
    """
    if not FITS_A.exists():
        pytest.skip(f"Golden FITS not found: {FITS_A}")

    vet_out = _run_pipeline_for_fixture(
        golden_fits=FITS_A,
        kic_id="KIC 11904151",
        source_doi="10.1088/0004-637X/729/1/27",
        detrend_window=_DETREND_WINDOW_A,
        period_min=_PERIOD_MIN_A,
        period_max=_PERIOD_MAX_A,
    )

    assert vet_out.disposition == EXPECTED_DISPOSITION_A, (
        f"Expected disposition {EXPECTED_DISPOSITION_A!r} for KIC 11904151 "
        f"(confirmed planet, centroid absent in Q3 golden fixture).\n"
        f"Got: {vet_out.disposition!r}\n"
        f"Triggering test: {vet_out.triggering_test}\n"
        f"All test results:\n"
        + "\n".join(
            f"  {r.test_name}: {r.outcome} — {r.reason}"
            for r in vet_out.test_results
        )
    )


# ---------------------------------------------------------------------------
# Test: Target B (KIC 6965293) — disposition must be false_positive via odd_even_depth
# ---------------------------------------------------------------------------

@pytest.mark.no_network
@pytest.mark.timeout(120)
def test_differentiator_proof_target_b_false_positive_via_odd_even():
    """
    KIC 6965293 (detached EB) must return disposition 'false_positive' via
    triggering_test == 'odd_even_depth'.

    This is the same assertion as test_known_eb_rejected.py but scoped to the
    Differentiator Proof claim specifically: the EB must be rejected on the
    basis of its alternating eclipse depth asymmetry, not any other test.
    """
    if not FITS_B.exists():
        pytest.skip(f"Golden FITS not found: {FITS_B}")

    vet_out = _run_pipeline_for_fixture(
        golden_fits=FITS_B,
        kic_id="KIC 6965293",
        source_doi="10.1088/0004-6256/141/3/83",
        detrend_window=_DETREND_WINDOW_B,
        period_min=_PERIOD_MIN_B,
        period_max=_PERIOD_MAX_B,
    )

    assert vet_out.disposition == EXPECTED_DISPOSITION_B, (
        f"Expected disposition {EXPECTED_DISPOSITION_B!r} for KIC 6965293 (known EB).\n"
        f"Got: {vet_out.disposition!r}\n"
        f"All test results:\n"
        + "\n".join(
            f"  {r.test_name}: {r.outcome} — {r.reason}"
            for r in vet_out.test_results
        )
    )

    assert vet_out.triggering_test == EXPECTED_TRIGGERING_TEST_B, (
        f"Expected triggering_test {EXPECTED_TRIGGERING_TEST_B!r} for KIC 6965293.\n"
        f"Got: {vet_out.triggering_test!r}\n"
        f"Reason: {vet_out.triggering_reason}"
    )


# ---------------------------------------------------------------------------
# Test: the two fixtures return OPPOSITE dispositions (the core claim)
# ---------------------------------------------------------------------------

@pytest.mark.no_network
@pytest.mark.timeout(240)
def test_differentiator_proof_targets_have_opposite_dispositions():
    """
    The core Differentiator Proof claim: KIC 11904151 and KIC 6965293 produce
    opposite dispositions from the Falsifier vetting pipeline.

    Both targets have a transit/eclipse signal. The opposite verdicts are driven
    by physical vetting tests (odd/even depth asymmetry), not by depth alone.

    This test enforces the mechanic underlying README.md §"The Differentiator Proof".
    """
    if not FITS_A.exists() or not FITS_B.exists():
        pytest.skip("One or both golden FITS files not found.")

    vet_a = _run_pipeline_for_fixture(
        golden_fits=FITS_A,
        kic_id="KIC 11904151",
        source_doi="10.1088/0004-637X/729/1/27",
        detrend_window=_DETREND_WINDOW_A,
        period_min=_PERIOD_MIN_A,
        period_max=_PERIOD_MAX_A,
    )
    vet_b = _run_pipeline_for_fixture(
        golden_fits=FITS_B,
        kic_id="KIC 6965293",
        source_doi="10.1088/0004-6256/141/3/83",
        detrend_window=_DETREND_WINDOW_B,
        period_min=_PERIOD_MIN_B,
        period_max=_PERIOD_MAX_B,
    )

    assert vet_a.disposition != vet_b.disposition, (
        f"Differentiator Proof FAILED: both targets returned the same disposition.\n"
        f"  KIC 11904151 (Target A): {vet_a.disposition}\n"
        f"  KIC 6965293  (Target B): {vet_b.disposition}\n"
        "The vetting pipeline must produce opposite dispositions for a confirmed "
        "planet candidate and a known eclipsing binary."
    )

    # Also enforce the specific expected dispositions documented in README.md
    assert vet_a.disposition == EXPECTED_DISPOSITION_A, (
        f"Target A (KIC 11904151) returned {vet_a.disposition!r}, "
        f"expected {EXPECTED_DISPOSITION_A!r}."
    )
    assert vet_b.disposition == EXPECTED_DISPOSITION_B, (
        f"Target B (KIC 6965293) returned {vet_b.disposition!r}, "
        f"expected {EXPECTED_DISPOSITION_B!r}."
    )
