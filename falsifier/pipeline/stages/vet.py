"""
falsifier.pipeline.stages.vet
================================
Implementation of the vet pipeline stage.

Seven independent vetting tests
--------------------------------
Each test is an independent function that returns a ``VettingTestResult``.
Tests are evaluated in ``VETTING_TEST_ORDER``:

  1. odd_even_depth           — primary/secondary eclipse depth asymmetry
  2. secondary_eclipse        — presence of a secondary eclipse
  3. centroid_shift           — centroid motion during transit
  4. transit_shape            — V-shaped vs. U-shaped transit profile
  5. stellar_density          — a_Rstar from light curve vs stellar model
  6. gaia_ruwe                — Gaia DR3 RUWE astrometric excess noise
  7. systematics_coincidence  — transit aligned with known systematic artefacts

Disposition truth table (from VetOutput contract)
--------------------------------------------------
  Any FAIL              → false_positive   (first FAIL triggers)
  No FAIL + any FLAG    → candidate_with_caveats
  No FAIL + any INC     → ambiguous
  All PASS              → candidate

The disposition is computed by the VetOutput Pydantic validator — this stage
merely assembles the seven VettingTestResult objects with correct outcomes
and passes them to VetOutput; the validator enforces consistency.

AGENTS.md compliance
--------------------
Rule 1: no scientific thresholds are hardcoded in UI/API code.  All thresholds
in this file are pipeline-internal configuration, not user-facing values.
Rule 2: physical quantities use astropy.units inside computation; results are
returned via UnitedArray / VettingTestResult (dimensionless scalars allowed).
"""

from __future__ import annotations

import hashlib
import math
import time
from pathlib import Path
from typing import Optional

import numpy as np

import falsifier
from falsifier.pipeline.contracts.vet import (
    VETTING_TEST_ORDER,
    VetInput,
    VetOutput,
    VettingTestName,
    VettingTestResult,
)
from falsifier.pipeline.contracts.search import SearchOutput, TCE
from falsifier.pipeline.contracts.manifest import ArtifactRef, StageManifest

__all__ = ["run_vet"]


# ---------------------------------------------------------------------------
# Thresholds — pipeline-internal configuration constants.
# None of these are displayed to a user; they are not covered by AGENTS.md Rule 1.
# ---------------------------------------------------------------------------

# odd_even_depth: TLS odd_even_mismatch > this → FAIL (clear EB signature)
_ODD_EVEN_FAIL_THRESHOLD = 3.0
# odd_even_depth: mismatch > this → FLAG (marginal asymmetry)
_ODD_EVEN_FLAG_THRESHOLD = 1.5

# secondary_eclipse: secondary_eclipse_depth / primary depth > this → FAIL
_SECONDARY_DEPTH_RATIO_FAIL = 0.5   # secondary > 50 % of primary is unphysical for a planet

# transit_shape: odd_even_mismatch also encodes V-shape; depth > 30 000 ppm
# indicates a stellar eclipse more likely than a planet transit.
_DEPTH_VSHAPE_FAIL_PPM = 30_000.0

# gaia_ruwe: RUWE > 1.4 → FLAG (possible unresolved binary / astrometric noise)
_GAIA_RUWE_FLAG = 1.4
# RUWE > 2.0 → FAIL (strong astrometric excess noise)
_GAIA_RUWE_FAIL = 2.0


# ---------------------------------------------------------------------------
# Individual vetting tests
# ---------------------------------------------------------------------------

def _test_odd_even_depth(tce: TCE) -> VettingTestResult:
    """
    Odd/even transit depth asymmetry test.

    TLS computes ``odd_even_mismatch``: the ratio of the difference between
    odd and even transit depths to their combined uncertainty.  Large values
    indicate that alternating transits have significantly different depths,
    which is the hallmark of an eclipsing binary where what appears to be
    two transits per period are actually the primary and secondary eclipses.

    References
    ----------
    Hippke & Heller 2019, DOI 10.1051/0004-6361/201834672, §5.
    """
    mismatch: float = tce.odd_even_mismatch

    if mismatch > _ODD_EVEN_FAIL_THRESHOLD:
        return VettingTestResult(
            test_name="odd_even_depth",
            outcome="FAIL",
            metric_value=mismatch,
            metric_unit="dimensionless",
            reason=(
                f"Odd/even transit depth mismatch {mismatch:.2f} exceeds threshold "
                f"{_ODD_EVEN_FAIL_THRESHOLD:.1f}; alternating depth asymmetry is "
                f"consistent with an eclipsing binary."
            ),
        )
    if mismatch > _ODD_EVEN_FLAG_THRESHOLD:
        return VettingTestResult(
            test_name="odd_even_depth",
            outcome="FLAG",
            metric_value=mismatch,
            metric_unit="dimensionless",
            reason=(
                f"Odd/even transit depth mismatch {mismatch:.2f} is marginally elevated "
                f"(threshold {_ODD_EVEN_FLAG_THRESHOLD:.1f}); warrants further inspection."
            ),
        )
    return VettingTestResult(
        test_name="odd_even_depth",
        outcome="PASS",
        metric_value=mismatch,
        metric_unit="dimensionless",
        reason=f"Odd/even depth mismatch {mismatch:.2f} is below threshold; no asymmetry detected.",
    )


def _test_secondary_eclipse(tce: TCE) -> VettingTestResult:
    """
    Secondary eclipse depth test.

    A deep secondary eclipse (relative to the primary transit depth) is
    inconsistent with a planet transit and indicates a stellar binary.
    """
    if tce.secondary_eclipse_depth is None:
        return VettingTestResult(
            test_name="secondary_eclipse",
            outcome="PASS",
            metric_value=None,
            metric_unit=None,
            reason="No secondary eclipse detected above the search threshold.",
        )

    secondary_ppm: float = tce.secondary_eclipse_depth.values[0]
    primary_ppm: float = tce.depth.values[0]

    if primary_ppm <= 0:
        return VettingTestResult(
            test_name="secondary_eclipse",
            outcome="INCONCLUSIVE",
            metric_value=secondary_ppm,
            metric_unit="ppm",
            reason="Primary transit depth is zero; secondary eclipse ratio undefined.",
        )

    ratio = secondary_ppm / primary_ppm
    if ratio > _SECONDARY_DEPTH_RATIO_FAIL:
        return VettingTestResult(
            test_name="secondary_eclipse",
            outcome="FAIL",
            metric_value=ratio,
            metric_unit="dimensionless",
            reason=(
                f"Secondary eclipse depth ratio {ratio:.2f} exceeds threshold "
                f"{_SECONDARY_DEPTH_RATIO_FAIL:.2f}; inconsistent with planetary transit."
            ),
        )
    return VettingTestResult(
        test_name="secondary_eclipse",
        outcome="PASS",
        metric_value=ratio,
        metric_unit="dimensionless",
        reason=f"Secondary eclipse depth ratio {ratio:.2f} is below threshold; consistent with planet.",
    )


def _test_centroid_shift(tce: TCE, search_output: SearchOutput) -> VettingTestResult:
    """
    Centroid shift test.

    Checks whether the photometric centroid shifts during transit, which
    would indicate the flux drop originates from a nearby contaminating source
    rather than the target star.  Requires MOM_CENTR arrays in the pipeline.

    Without centroid data (not available in the golden fixture), this test
    returns INCONCLUSIVE.
    """
    # Centroid data is not propagated through the current pipeline contract
    # (LightCurveSegment.centroid_col / centroid_row are Optional and absent
    # in the golden test fixtures).  Return INCONCLUSIVE rather than PASS
    # to avoid falsely certifying a target without centroid analysis.
    return VettingTestResult(
        test_name="centroid_shift",
        outcome="INCONCLUSIVE",
        metric_value=None,
        metric_unit=None,
        reason="Centroid time series not available for this target; centroid shift test skipped.",
    )


def _test_transit_shape(tce: TCE) -> VettingTestResult:
    """
    Transit shape test.

    Extremely deep transits (> 30 000 ppm = 3 %) are inconsistent with a
    Jupiter-sized planet transiting a Sun-like star and indicate a stellar
    eclipse.  The odd_even_mismatch encodes V-shape information implicitly;
    a very high mismatch combined with a deep transit is the clearest flag.
    """
    depth_ppm: float = tce.depth.values[0]
    if depth_ppm > _DEPTH_VSHAPE_FAIL_PPM:
        return VettingTestResult(
            test_name="transit_shape",
            outcome="FAIL",
            metric_value=depth_ppm,
            metric_unit="ppm",
            reason=(
                f"Transit depth {depth_ppm:.0f} ppm exceeds {_DEPTH_VSHAPE_FAIL_PPM:.0f} ppm; "
                f"inconsistent with a sub-stellar companion transiting a main-sequence star."
            ),
        )
    return VettingTestResult(
        test_name="transit_shape",
        outcome="PASS",
        metric_value=depth_ppm,
        metric_unit="ppm",
        reason=f"Transit depth {depth_ppm:.0f} ppm is within the planetary regime.",
    )


def _test_stellar_density(tce: TCE, search_output: SearchOutput) -> VettingTestResult:
    """
    Stellar density consistency test.

    Compares the stellar density implied by the transit duration and impact
    parameter (Seager & Mallén-Ornelas 2003) with the spectroscopic/photometric
    density from the stellar model.  Without stellar parameters (absent in the
    golden fixture), returns INCONCLUSIVE.
    """
    return VettingTestResult(
        test_name="stellar_density",
        outcome="INCONCLUSIVE",
        metric_value=None,
        metric_unit=None,
        reason="Stellar parameters not available; stellar density consistency test skipped.",
    )


def _test_gaia_ruwe(search_output: SearchOutput) -> VettingTestResult:
    """
    Gaia DR3 RUWE test.

    RUWE > 1.4 indicates excess astrometric residuals, possibly from an
    unresolved binary.  Without Gaia data in the pipeline fixture, returns
    INCONCLUSIVE.
    """
    # RUWE is stored in IngestOutput.stellar_params which is not threaded
    # through the current DetrendOutput / SearchOutput chain in golden tests.
    return VettingTestResult(
        test_name="gaia_ruwe",
        outcome="INCONCLUSIVE",
        metric_value=None,
        metric_unit=None,
        reason="Gaia RUWE not available for this target; RUWE test skipped.",
    )


def _test_systematics_coincidence(tce: TCE) -> VettingTestResult:
    """
    Systematics coincidence test.

    Checks whether the transit epoch and period are suspiciously aligned with
    known Kepler/TESS systematic artefacts (reaction wheel events, thermal
    breathing, data gaps).  Without a systematics model, returns INCONCLUSIVE.
    """
    return VettingTestResult(
        test_name="systematics_coincidence",
        outcome="INCONCLUSIVE",
        metric_value=None,
        metric_unit=None,
        reason="Systematics catalogue not available; systematics coincidence test skipped.",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_vet(
    inp: VetInput,
    *,
    search_output: Optional[SearchOutput] = None,
    tce: Optional[TCE] = None,
) -> VetOutput:
    """
    Run all seven vetting tests for one TCE and return a VetOutput.

    Parameters
    ----------
    inp : VetInput
        Per-TCE request including tce_id and search_artifact pointer.
    search_output : SearchOutput, optional
        In-memory SearchOutput.  Required when running without disk I/O.
    tce : TCE, optional
        The specific TCE to vet.  If None, looked up from search_output.tces
        by tce_id.

    Returns
    -------
    VetOutput
        Fully validated result including disposition and triggering_test.
    """
    if search_output is None:
        raise NotImplementedError(
            "Disk-based search_artifact loading is not yet implemented. "
            "Pass search_output= directly."
        )

    if tce is None:
        matching = [t for t in search_output.tces if t.tce_id == inp.tce_id]
        if not matching:
            raise ValueError(
                f"TCE '{inp.tce_id}' not found in search_output.tces "
                f"(available: {[t.tce_id for t in search_output.tces]})"
            )
        tce = matching[0]

    t0 = time.monotonic()

    # Run tests in VETTING_TEST_ORDER.
    test_results: list[VettingTestResult] = [
        _test_odd_even_depth(tce),
        _test_secondary_eclipse(tce),
        _test_centroid_shift(tce, search_output),
        _test_transit_shape(tce),
        _test_stellar_density(tce, search_output),
        _test_gaia_ruwe(search_output),
        _test_systematics_coincidence(tce),
    ]

    # Compute disposition from results (mirrors VetOutput validator logic).
    first_fail = next((r for r in test_results if r.outcome == "FAIL"), None)
    if first_fail is not None:
        disposition = "false_positive"
        triggering_test = first_fail.test_name
        triggering_reason = first_fail.reason
    else:
        first_flag = next((r for r in test_results if r.outcome == "FLAG"), None)
        if first_flag is not None:
            disposition = "candidate_with_caveats"
            triggering_test = first_flag.test_name
            triggering_reason = first_flag.reason
        else:
            first_inc = next((r for r in test_results if r.outcome == "INCONCLUSIVE"), None)
            if first_inc is not None:
                disposition = "ambiguous"
                triggering_test = first_inc.test_name
                triggering_reason = first_inc.reason
            else:
                disposition = "candidate"
                triggering_test = None
                triggering_reason = None

    wall_time = time.monotonic() - t0
    run_hash = hashlib.sha256(inp.model_dump_json().encode()).hexdigest()
    artifact_ref = ArtifactRef(
        path=Path(f"/tmp/falsifier/vet_{inp.pipeline_run_id}_{inp.tce_id}.json"),
        sha256=run_hash,
        stage="vet",
        pipeline_run_id=inp.pipeline_run_id,
    )

    return VetOutput(
        input=inp,
        tce_id=inp.tce_id,
        host_star_id=search_output.host_star_id,
        test_results=test_results,
        disposition=disposition,
        triggering_test=triggering_test,
        triggering_reason=triggering_reason,
        manifest=StageManifest(
            stage="vet",
            code_version=getattr(falsifier, "__version__", "0.0.0-dev"),
            input_hash=hashlib.sha256(search_output.model_dump_json().encode()).hexdigest(),
            wall_time_seconds=wall_time,
            provenance=[],
            artifact=artifact_ref,
        ),
        artifact=artifact_ref,
    )
