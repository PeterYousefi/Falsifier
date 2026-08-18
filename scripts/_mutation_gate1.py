"""
Gate 1 mutation test: assert uses wrong (mutated) period.

DELIBERATELY FAILS — this script's test is supposed to fail.
Its purpose is to demonstrate that the assertion in test_kepler10b_period_recovery
would fire if a wrong period were returned.  Run it to see the expected failure
output; do not add it to CI as a passing test.

Run: .venv/bin/python -m pytest scripts/_mutation_gate1.py -v --timeout=120

See docs/PROVEN_GATES.md Gate 1 for the recorded output.
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
GOLDEN_FITS = GOLDEN_DIR / "kepler10_q3_long.fits"

KEPLER10B_PERIOD_DAYS = 0.83749070
PERIOD_TOLERANCE_DAYS = 1e-4
DETREND_WINDOW_DAYS = 0.75
BREAK_TOLERANCE_DAYS = 0.5
TLS_PERIOD_MIN_DAYS = 0.5
TLS_PERIOD_MAX_DAYS = 2.0


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


def test_mutation1_wrong_period_is_caught():
    """Mutation: run_search returns period shifted by +0.01 days (100× tolerance).

    The real pipeline runs correctly but we then simulate what would happen
    if run_search had returned a wrong period by replacing the recovered_period
    with a value shifted by 0.01 days before running the assertion.
    """
    from falsifier.pipeline.contracts import (
        ArtifactRef, DatasetProvenance, DetrendInput, IngestInput, IngestOutput,
        LightCurveSegment, SearchInput, StageManifest, UnitedArray,
    )
    from falsifier.pipeline.stages.detrend import run_detrend
    from falsifier.pipeline.stages.search import run_search

    time_bkjd, flux_norm, flux_err_norm = _load_golden()
    run_id = "mutation-gate1"

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
        source_doi="10.1088/0004-637X/729/1/27",
        access_date=datetime.date(2024, 1, 1),
        row_count=len(time_bkjd),
        description="Kepler-10 Q3 long-cadence — mutation gate 1 fixture",
    )
    ingest_out = IngestOutput(
        input=IngestInput(tic_id="KIC 11904151", sectors=[3], cadence="long",
                          pipeline_run_id=run_id),
        segments=[seg], host_star_id="KIC 11904151",
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

    assert search_out.tces, "No TCEs found"
    best_tce = max(search_out.tces, key=lambda t: t.sde)
    real_period = best_tce.period.to_quantity().value[0]

    # MUTATION: simulate a run_search that returned period +0.01 days off
    recovered_period = real_period + 0.01  # mutant value
    mutant_sde = best_tce.sde

    assert abs(recovered_period - KEPLER10B_PERIOD_DAYS) < PERIOD_TOLERANCE_DAYS, (
        f"Period recovery failed.\n"
        f"  Published : {KEPLER10B_PERIOD_DAYS:.8f} days "
        f"(Batalha et al. 2011, DOI:10.1088/0004-637X/729/1/27)\n"
        f"  Recovered : {recovered_period:.8f} days\n"
        f"  Difference: {abs(recovered_period - KEPLER10B_PERIOD_DAYS):.2e} days\n"
        f"  Tolerance : {PERIOD_TOLERANCE_DAYS:.1e} days\n"
        f"  SDE       : {mutant_sde:.2f}"
    )
