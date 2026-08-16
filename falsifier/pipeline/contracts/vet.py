"""
falsifier.pipeline.contracts.vet
==================================
Pydantic contracts for the vet pipeline stage.

  VettingTestOutcome — PASS | FAIL | FLAG | INCONCLUSIVE
  VettingTestName    — seven load-bearing canonical identifiers
  VettingTestResult  — one test's result + metric + reason
  Disposition        — deterministic classification of a TCE
  VetInput           — per-TCE request
  VetOutput          — the complete, self-contained disposition record

Policy
------
Disposition lives here and nowhere else.  The truth table is enforced as
Pydantic validators so any code that constructs a VetOutput with an
inconsistent disposition fails at object-creation time:

  All seven PASS               → candidate
  Any FAIL                     → false_positive   (first FAIL triggers)
  No FAIL + any FLAG           → candidate_with_caveats  (first FLAG triggers)
  No FAIL + no FLAG + any INC  → ambiguous        (first INCONCLUSIVE triggers)

ClassifyOutput must never restate or override this disposition.
"""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from .manifest import ArtifactRef, DatasetProvenance, StageManifest

__all__ = [
    "VettingTestOutcome",
    "VettingTestName",
    "VettingTestResult",
    "Disposition",
    "VetInput",
    "VetOutput",
]

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

VettingTestOutcome = Literal["PASS", "FAIL", "FLAG", "INCONCLUSIVE"]
"""
Four-valued outcome for each vetting test:
  PASS         — test passed cleanly
  FAIL         — hard rejection gate triggered
  FLAG         — soft caution (passes the gate but warrants annotation)
  INCONCLUSIVE — test could not determine an outcome
"""

VettingTestName = Literal[
    "odd_even_depth",
    "secondary_eclipse",
    "centroid_shift",
    "transit_shape",
    "stellar_density",
    "gaia_ruwe",
    "systematics_coincidence",
]
"""
Seven canonical, load-bearing vetting test names.

These strings appear in the golden EB test (``tests/test_known_eb_rejected.py``)
and are asserted on by name.  Do NOT rename them without updating:
  - tests/test_known_eb_rejected.py (EXPECTED_TRIGGERING_TEST)
  - docs/PROVEN_GATES.md (gate 2 section)
  - pipeline-contracts-plan.md (Sub-Task 5, step 3)
"""

# Canonical ordering — used to validate that exactly one result exists per test
VETTING_TEST_ORDER: tuple[str, ...] = (
    "odd_even_depth",
    "secondary_eclipse",
    "centroid_shift",
    "transit_shape",
    "stellar_density",
    "gaia_ruwe",
    "systematics_coincidence",
)

Disposition = Literal[
    "candidate",
    "candidate_with_caveats",
    "false_positive",
    "ambiguous",
]
"""
Deterministic classification of a TCE, computed from the seven vetting tests.
This value lives exclusively in VetOutput.  No downstream stage may override it.
"""


# ---------------------------------------------------------------------------
# VettingTestResult
# ---------------------------------------------------------------------------

class VettingTestResult(BaseModel):
    """Result of one vetting test for one TCE."""

    test_name: VettingTestName
    """Typed to the load-bearing Literal; unknown names fail at construction."""

    outcome: VettingTestOutcome

    metric_value: float | None = None
    """The scalar metric the test evaluated, if applicable (e.g. RUWE = 1.42)."""

    metric_unit: str | None = None
    """Unit string, ``"dimensionless"``, or ``None`` if no metric applies."""

    reason: str
    """Required, non-empty one-sentence human-readable explanation."""

    @field_validator("reason")
    @classmethod
    def _reason_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("VettingTestResult.reason must be a non-empty string")
        return v


# ---------------------------------------------------------------------------
# VetInput
# ---------------------------------------------------------------------------

class VetInput(BaseModel):
    """Per-TCE request to the vet stage."""

    search_artifact: ArtifactRef
    """Points to the SearchOutput that contains this TCE."""

    tce_id: str
    """One TCE per VetInput.  Vet runs per-TCE, not per-star."""

    pipeline_run_id: str


# ---------------------------------------------------------------------------
# VetOutput
# ---------------------------------------------------------------------------

class VetOutput(BaseModel):
    """
    Complete, self-contained disposition record for one TCE.

    The ``disposition`` field is the only authoritative verdict; it is
    computed deterministically from ``test_results`` and validated at
    construction.  The "API-deletion test": if the classifier and its API
    were deleted, this record alone must constitute a defensible scientific
    result.
    """

    input: VetInput
    tce_id: str
    host_star_id: str

    test_results: list[VettingTestResult]
    """Exactly seven entries, one per canonical test, in VETTING_TEST_ORDER."""

    disposition: Disposition

    triggering_test: VettingTestName | None
    """
    The test whose outcome determined the disposition.
    None only when disposition == "candidate" (all seven PASS).
    Typed to VettingTestName so unknown names are rejected at construction.
    """

    triggering_reason: str | None
    """The reason string from the triggering test.  None only for "candidate"."""

    manifest: StageManifest
    artifact: ArtifactRef

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("test_results")
    @classmethod
    def _exactly_seven(cls, v: list[VettingTestResult]) -> list[VettingTestResult]:
        if len(v) != 7:
            found = [r.test_name for r in v]
            expected = set(VETTING_TEST_ORDER)
            present = {r.test_name for r in v}
            missing = expected - present
            extra = present - expected
            msg = f"test_results must contain exactly 7 entries; got {len(v)}."
            if missing:
                msg += f" Missing: {sorted(missing)}."
            if extra:
                msg += f" Extra: {sorted(extra)}."
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def _disposition_consistent(self) -> "VetOutput":
        results = self.test_results

        # Compute the expected disposition from the outcomes
        outcomes = {r.test_name: r.outcome for r in results}

        # Priority 1: any FAIL → false_positive
        first_fail = next(
            (r for r in results if r.outcome == "FAIL"), None
        )
        if first_fail is not None:
            expected = "false_positive"
            trig_test: VettingTestName | None = first_fail.test_name  # type: ignore[assignment]
            trig_reason: str | None = first_fail.reason
        else:
            # Priority 2: no FAIL + any FLAG → candidate_with_caveats
            first_flag = next(
                (r for r in results if r.outcome == "FLAG"), None
            )
            if first_flag is not None:
                expected = "candidate_with_caveats"
                trig_test = first_flag.test_name  # type: ignore[assignment]
                trig_reason = first_flag.reason
            else:
                # Priority 3: any INCONCLUSIVE → ambiguous
                first_inc = next(
                    (r for r in results if r.outcome == "INCONCLUSIVE"), None
                )
                if first_inc is not None:
                    expected = "ambiguous"
                    trig_test = first_inc.test_name  # type: ignore[assignment]
                    trig_reason = first_inc.reason
                else:
                    # All PASS
                    expected = "candidate"
                    trig_test = None
                    trig_reason = None

        if self.disposition != expected:
            raise ValueError(
                f"VetOutput.disposition is inconsistent with test_results.\n"
                f"  Declared  : {self.disposition!r}\n"
                f"  Computed  : {expected!r}\n"
                f"  Outcomes  : "
                + ", ".join(f"{r.test_name}={r.outcome}" for r in results)
            )

        # Validate triggering_test / triggering_reason coherence
        if expected == "candidate":
            if self.triggering_test is not None or self.triggering_reason is not None:
                raise ValueError(
                    "disposition == 'candidate' requires triggering_test == None "
                    "and triggering_reason == None"
                )
        else:
            if self.triggering_test is None or self.triggering_reason is None:
                raise ValueError(
                    f"disposition == {self.disposition!r} requires both "
                    "triggering_test and triggering_reason to be non-None"
                )

        return self
