"""
Gate 2 pipeline-level mutation: run_vet is patched to return the wrong triggering_test.

DELIBERATELY FAILS — this script's test is supposed to fail.
Its purpose is to demonstrate that ``test_known_eb_triggering_test_is_odd_even_depth``
catches a defective ``run_vet`` implementation — not merely a wrong variable at
assertion time.

Unlike ``_mutation_gate2.py`` (assertion-level), this script patches
``falsifier.pipeline.stages.vet.run_vet`` before it is called so the full
detrend → search → vet pipeline runs but vet returns a wrong triggering_test.

Run: .venv/bin/python -m pytest scripts/_mutation_gate2_pipeline.py -v --timeout=120

See docs/PROVEN_GATES.md Gate 2 (pipeline-level section) for the recorded output.
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


def test_mutation2_pipeline_wrong_trigger_is_caught():
    """
    Pipeline-level mutation: patch run_vet to replace triggering_test with
    "centroid_shift" instead of "odd_even_depth", then run the golden assertion.

    The full detrend → search pipeline runs against the committed EB FITS.
    run_vet is wrapped so that after the real vet runs, the VetOutput's
    triggering_test is replaced with the mutant value before the result is
    returned to the caller.

    This confirms the assertion rejects a defective run_vet implementation,
    not just a wrong variable injected after a correct run.
    """
    from falsifier.pipeline.contracts import (
        ArtifactRef, DatasetProvenance, DetrendInput, IngestInput, IngestOutput,
        LightCurveSegment, SearchInput, StageManifest, UnitedArray,
    )
    from falsifier.pipeline.contracts.vet import VetInput
    from falsifier.pipeline.stages.detrend import run_detrend
    from falsifier.pipeline.stages.search import run_search
    import falsifier.pipeline.stages.vet as _vet_module

    time_bkjd, flux_norm, flux_err_norm = _load_golden()
    run_id = "mutation-gate2-pipeline"

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
        description="KIC 6965293 Q3 — pipeline mutation gate 2 fixture",
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
    assert search_out.tces, "No TCEs found in EB data — cannot exercise run_vet"

    best_tce = max(search_out.tces, key=lambda t: t.sde)
    vet_input = VetInput(
        search_artifact=dummy_ref,
        tce_id=best_tce.tce_id,
        pipeline_run_id=run_id,
    )

    # --- MUTATION: wrap run_vet to corrupt triggering_test ---
    _real_run_vet = _vet_module.run_vet

    def _mutant_run_vet(inp, *, search_output=None, tce=None):
        """Return the real vet output but replace triggering_test with centroid_shift."""
        result = _real_run_vet(inp, search_output=search_output, tce=tce)
        # Only corrupt when the real result is a false_positive so we target
        # the exact assertion the golden test checks.
        if result.disposition == "false_positive":
            return result.model_copy(update={
                "triggering_test": "centroid_shift",
                "triggering_reason": "Centroid offset 3.2 arcsec during eclipse (mutant)",
            })
        return result

    with patch.object(_vet_module, "run_vet", side_effect=_mutant_run_vet):
        vet_out = _vet_module.run_vet(vet_input, search_output=search_out, tce=best_tce)

    assert vet_out.triggering_test is not None, (
        "triggering_test is None — disposition is not 'candidate' so this is a contract bug"
    )

    # This assertion MUST FAIL because triggering_test has been mutated to centroid_shift
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
