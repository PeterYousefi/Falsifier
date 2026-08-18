"""
Gate 1 pipeline-level mutation: run_search is patched to return a wrong period.

DELIBERATELY FAILS — this script's test is supposed to fail.
Its purpose is to demonstrate that ``test_kepler10b_period_recovery``
catches a defective ``run_search`` implementation — not merely a wrong
variable at assertion time.

Unlike ``_mutation_gate1.py`` (assertion-level), this script patches
``falsifier.pipeline.stages.search.run_search`` *before* it is called
and verifies that the golden test's assertion fires on the mutant output.

Run: .venv/bin/python -m pytest scripts/_mutation_gate1_pipeline.py -v --timeout=120

See docs/PROVEN_GATES.md Gate 1 (pipeline-level section) for the recorded output.
"""
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import datetime
import hashlib
import numpy as np
import pytest
from unittest.mock import patch
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


def test_mutation1_pipeline_wrong_period_is_caught():
    """
    Pipeline-level mutation: patch run_search to return a period shifted
    by +0.01 days (100× the tolerance), then run the golden test assertion.

    The real run_detrend runs on the committed FITS file.  run_search is
    replaced with a stub that calls the real implementation, then replaces
    the period on the best TCE with the wrong value before returning.

    This confirms the assertion rejects a defective run_search, not just
    a wrong variable injected after a correct run.
    """
    from falsifier.pipeline.contracts import (
        ArtifactRef, DatasetProvenance, DetrendInput, IngestInput, IngestOutput,
        LightCurveSegment, SearchInput, StageManifest, UnitedArray,
    )
    from falsifier.pipeline.stages.detrend import run_detrend
    import falsifier.pipeline.stages.search as _search_module
    from falsifier.pipeline.contracts.manifest import UnitedArray as UA

    time_bkjd, flux_norm, flux_err_norm = _load_golden()
    run_id = "mutation-gate1-pipeline"

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
        description="Kepler-10 Q3 — pipeline mutation gate 1 fixture",
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

    # --- MUTATION: wrap run_search to corrupt the period on the best TCE ---
    _real_run_search = _search_module.run_search

    def _mutant_run_search(inp, *, detrend_output=None):
        """Return the real search output but shift the best TCE period by +0.01 d."""
        result = _real_run_search(inp, detrend_output=detrend_output)
        if not result.tces:
            return result
        best = max(result.tces, key=lambda t: t.sde)
        real_period = best.period.to_quantity().value[0]
        wrong_period = real_period + 0.01  # 100× tolerance: should be caught

        # Build a copy of the TCE list with the mutated period
        mutated_tces = []
        for tce in result.tces:
            if tce.tce_id == best.tce_id:
                # Replace period in-place via model_copy
                mutated = tce.model_copy(
                    update={"period": UA(values=[wrong_period], unit="day")}
                )
                mutated_tces.append(mutated)
            else:
                mutated_tces.append(tce)

        return result.model_copy(update={"tces": mutated_tces})

    with patch.object(_search_module, "run_search", side_effect=_mutant_run_search):
        search_out = _search_module.run_search(search_input, detrend_output=detrend_out)

    assert search_out.tces, "No TCEs returned by mutant run_search"
    best_tce = max(search_out.tces, key=lambda t: t.sde)
    recovered_period = best_tce.period.to_quantity().value[0]

    # This assertion MUST FAIL because recovered_period is +0.01 days off
    assert abs(recovered_period - KEPLER10B_PERIOD_DAYS) < PERIOD_TOLERANCE_DAYS, (
        f"Period recovery failed.\n"
        f"  Published : {KEPLER10B_PERIOD_DAYS:.8f} days "
        f"(Batalha et al. 2011, DOI:10.1088/0004-637X/729/1/27)\n"
        f"  Recovered : {recovered_period:.8f} days\n"
        f"  Difference: {abs(recovered_period - KEPLER10B_PERIOD_DAYS):.2e} days\n"
        f"  Tolerance : {PERIOD_TOLERANCE_DAYS:.1e} days\n"
        f"  SDE       : {best_tce.sde:.2f}"
    )
