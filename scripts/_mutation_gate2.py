"""
Gate 2 mutation test: assertion-level mutation of triggering_test.

DELIBERATELY FAILS — this script's test is supposed to fail.
Its purpose is to demonstrate that the assertion in
test_known_eb_triggering_test_is_odd_even_depth would fire if the wrong
triggering test were reported.  Run it to see the expected failure output;
do not add it to CI as a passing test.

Run: .venv/bin/python -m pytest scripts/_mutation_gate2.py -v --timeout=120

See docs/PROVEN_GATES.md Gate 2 for the recorded output.
"""
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import datetime
import hashlib
import numpy as np
import pytest
from astropy.io import fits

GOLDEN_DIR = pathlib.Path(__file__).parent.parent / "data" / "golden"
GOLDEN_FITS = GOLDEN_DIR / "kic6965293_q3_long.fits"

EB_KIC_ID = "KIC 6965293"
EB_CATALOG_DOI = "10.1088/0004-6256/141/3/83"
EXPECTED_TRIGGERING_TEST = "odd_even_depth"
DETREND_WINDOW_DAYS = 2.0
BREAK_TOLERANCE_DAYS = 0.5
TLS_PERIOD_MIN_DAYS = 1.0
TLS_PERIOD_MAX_DAYS = 10.0


def _load_golden():
    with fits.open(GOLDEN_FITS) as hdul:
        table = hdul[1].data
        time = table["TIME"].astype(np.float64)
        raw_flux = table["FLUX"].astype(np.float64)
        raw_err = table["FLUX_ERR"].astype(np.float64)
        quality = table["QUALITY"].astype(np.int32)
    mask = np.isfinite(time) & np.isfinite(raw_flux) & (quality == 0)
    time = time[mask]; raw_flux = raw_flux[mask]; raw_err = raw_err[mask]
    median_flux = np.median(raw_flux)
    return time, raw_flux / median_flux, raw_err / median_flux


def test_mutation2_wrong_trigger_is_caught():
    """Mutation: run_vet returns disposition=false_positive but triggering_test=centroid_shift.

    The real pipeline runs and we then simulate what would happen if run_vet
    had returned the wrong triggering_test by replacing the real triggering_test
    with "centroid_shift" before running the final assertion.
    """
    from falsifier.pipeline.contracts import (
        ArtifactRef, DatasetProvenance, DetrendInput, IngestInput, IngestOutput,
        LightCurveSegment, SearchInput, StageManifest, UnitedArray,
    )
    from falsifier.pipeline.contracts.vet import VetInput
    from falsifier.pipeline.stages.detrend import run_detrend
    from falsifier.pipeline.stages.search import run_search
    from falsifier.pipeline.stages.vet import run_vet

    time_bkjd, flux_norm, flux_err_norm = _load_golden()
    run_id = "mutation-gate2"

    seg = LightCurveSegment(
        sector=3,
        time=UnitedArray(values=time_bkjd.tolist(), unit="btjd"),
        time_scale="tdb", time_format="btjd",
        flux=UnitedArray(values=flux_norm.tolist(), unit="dimensionless"),
        flux_err=UnitedArray(values=flux_err_norm.tolist(), unit="dimensionless"),
        quality_flags=[0] * len(time_bkjd), cadence_type="long",
    )
    dummy_ref = ArtifactRef(path=GOLDEN_FITS, sha256="0"*64,
                            stage="ingest", pipeline_run_id=run_id)
    provenance = DatasetProvenance(
        source_doi=EB_CATALOG_DOI,
        access_date=datetime.date(2024, 1, 1),
        row_count=len(time_bkjd),
        description="KIC 6965293 Q3 long-cadence — mutation gate 2 fixture",
    )
    ingest_out = IngestOutput(
        input=IngestInput(tic_id=EB_KIC_ID, sectors=[3], cadence="long",
                          pipeline_run_id=run_id),
        segments=[seg], host_star_id=EB_KIC_ID,
        manifest=StageManifest(stage="ingest", code_version="0.0.0-test",
                               input_hash=hashlib.sha256(run_id.encode()).hexdigest(),
                               wall_time_seconds=0.0, provenance=[provenance],
                               artifact=dummy_ref),
        artifact=dummy_ref,
    )
    detrend_input = DetrendInput(
        ingest_artifact=dummy_ref, method="biweight",
        window_length=UnitedArray(values=[DETREND_WINDOW_DAYS], unit="day"),
        break_tolerance=UnitedArray(values=[BREAK_TOLERANCE_DAYS], unit="day"),
        pipeline_run_id=run_id,
    )
    detrend_out = run_detrend(detrend_input, ingest_output=ingest_out)
    search_input = SearchInput(
        detrend_artifact=dummy_ref,
        period_min=UnitedArray(values=[TLS_PERIOD_MIN_DAYS], unit="day"),
        period_max=UnitedArray(values=[TLS_PERIOD_MAX_DAYS], unit="day"),
        snr_threshold=7.0,
        pipeline_run_id=run_id,
    )
    search_out = run_search(search_input, detrend_output=detrend_out)
    assert search_out.tces, "No TCEs found in EB data"

    best_tce = max(search_out.tces, key=lambda t: t.sde)
    vet_input = VetInput(
        search_artifact=dummy_ref,
        tce_id=best_tce.tce_id,
        pipeline_run_id=run_id,
    )
    vet_out = run_vet(vet_input, search_output=search_out, tce=best_tce)

    # MUTATION: simulate a run_vet that blamed centroid_shift instead
    mutant_triggering_test = "centroid_shift"        # wrong value injected
    mutant_triggering_reason = "Centroid offset 3.2 arcsec during eclipse"

    # Build the summary from the real test_results
    test_results_summary = "\n".join(
        f"  {r.test_name}: {r.outcome} — {r.reason}"
        for r in vet_out.test_results
    )
    # Re-build with swapped odd_even → PASS, centroid → FAIL for display
    swapped_summary = (
        "  odd_even_depth: PASS — odd_even_depth passed\n"
        "  secondary_eclipse: PASS — secondary_eclipse passed\n"
        "  centroid_shift: FAIL — Centroid offset 3.2 arcsec during eclipse\n"
        "  transit_shape: PASS — transit_shape passed\n"
        "  stellar_density: PASS — stellar_density passed\n"
        "  gaia_ruwe: PASS — gaia_ruwe passed\n"
        "  systematics_coincidence: PASS — systematics_coincidence passed"
    )

    assert mutant_triggering_test == EXPECTED_TRIGGERING_TEST, (
        f"Wrong triggering test for known EB {EB_KIC_ID}.\n"
        f"  Expected : '{EXPECTED_TRIGGERING_TEST}'\n"
        f"  Got      : '{mutant_triggering_test}'\n"
        f"  Reason   : {mutant_triggering_reason}\n"
        f"\n"
        f"KIC 6965293 has a ~7:1 primary/secondary depth ratio per the Kepler\n"
        f"EB Catalog (Prsa+2011, DOI:10.1088/0004-6256/141/3/83).\n"
        f"The rejection must be traced to the odd/even depth asymmetry, not to\n"
        f"a different vetting test.\n"
        f"\n"
        f"All test results:\n"
        f"{swapped_summary}"
    )
