"""
tests/test_stellar_density_reason_accuracy.py
==============================================
Policy gate: the stellar_density vetting test must produce a reason string
that accurately reflects WHY it returned INCONCLUSIVE.

Fix 3 regression guard.

The defect: ``_test_stellar_density`` previously hardcoded the string
"Stellar parameters not available; stellar density consistency test skipped."
even when ``stellar_density_rho_sun`` was present (as it is for KIC 11904151
with rho=1.09 ρ☉ from Batalha+2011).  That string is false when data IS
available.

This test asserts:
1.  When stellar_density_rho_sun IS provided, the reason string does NOT
    claim data is "not available" — it says the test is "not yet implemented".

2.  When stellar_density_rho_sun is None, the reason string DOES say the
    data is not available.

3.  The fixture job.json's stellar_density reason string is consistent with
    the actual presence of stellar_density_rho_sun in that same entry.

Markers
-------
@pytest.mark.no_network — no outgoing connections.
"""

from __future__ import annotations

import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
FIXTURE_JOB = REPO_ROOT / "frontend" / "src" / "fixtures" / "job.json"

pytestmark = pytest.mark.no_network


# ---------------------------------------------------------------------------
# Unit tests for _test_stellar_density
# ---------------------------------------------------------------------------

def _make_mock_tce_and_search():
    """Return minimal mock objects accepted by _test_stellar_density."""
    # We only need attributes accessed by _test_stellar_density, which is now
    # just the optional stellar_density_rho_sun parameter — tce and search_output
    # are passed but not used for the density check itself.
    from unittest.mock import MagicMock

    tce = MagicMock()
    search_output = MagicMock()
    return tce, search_output


def test_stellar_density_reason_not_available_when_none():
    """
    When stellar_density_rho_sun is None, the reason must say the data is
    "not available" — it would be wrong to say the check is implemented but
    skipping, because there's literally no data to run it against.
    """
    from falsifier.pipeline.stages.vet import _test_stellar_density

    tce, search_output = _make_mock_tce_and_search()
    result = _test_stellar_density(tce, search_output, stellar_density_rho_sun=None)

    assert result.outcome == "INCONCLUSIVE", (
        f"Expected INCONCLUSIVE when stellar_density_rho_sun is None; "
        f"got {result.outcome!r}"
    )
    # The reason MUST indicate data is not available
    reason_lower = result.reason.lower()
    assert "not available" in reason_lower or "not present" in reason_lower, (
        f"When stellar_density_rho_sun is None, the reason should say the data "
        f"is not available.\n  Got: {result.reason!r}"
    )
    # The reason must NOT claim parameters are present when they are not
    assert "available but unused" not in result.reason, (
        f"Reason falsely claims data is available when it is None.\n"
        f"  Got: {result.reason!r}"
    )


def test_stellar_density_reason_not_claiming_data_absent_when_present():
    """
    When stellar_density_rho_sun IS provided, the reason must NOT claim
    "Stellar parameters not available".  That statement is false when the
    value is present.

    The correct reason explains that the stub does not run the check, not
    that the data is missing.
    """
    from falsifier.pipeline.stages.vet import _test_stellar_density

    tce, search_output = _make_mock_tce_and_search()
    result = _test_stellar_density(tce, search_output, stellar_density_rho_sun=1.09)

    assert result.outcome == "INCONCLUSIVE", (
        f"Expected INCONCLUSIVE; got {result.outcome!r}"
    )
    # The reason MUST NOT claim data is missing when it is present
    assert "not available" not in result.reason, (
        f"Reason falsely claims stellar data is 'not available' when "
        f"stellar_density_rho_sun=1.09 was provided.\n  Got: {result.reason!r}"
    )
    # The reason SHOULD mention that the value is available
    assert "available" in result.reason or "1.09" in result.reason, (
        f"Reason should acknowledge that stellar_density_rho_sun=1.09 is present.\n"
        f"  Got: {result.reason!r}"
    )
    # The reason SHOULD indicate the check is not implemented (stub)
    assert "not yet implemented" in result.reason or "stub" in result.reason, (
        f"Reason should state that the check is not implemented in the pipeline stub.\n"
        f"  Got: {result.reason!r}"
    )


def test_stellar_density_reason_embeds_density_value():
    """
    When stellar_density_rho_sun is provided, the reason string must embed
    the actual value so a reader can trace it back to the source.
    """
    from falsifier.pipeline.stages.vet import _test_stellar_density

    tce, search_output = _make_mock_tce_and_search()
    test_rho = 1.09  # Batalha+2011 value for KIC 11904151
    result = _test_stellar_density(tce, search_output, stellar_density_rho_sun=test_rho)

    # The reason must contain some representation of the density value
    # (the format string uses {:.4g} which gives "1.09" for this value)
    assert "1.09" in result.reason, (
        f"Reason string should embed the density value 1.09 for traceability.\n"
        f"  Got: {result.reason!r}"
    )


# ---------------------------------------------------------------------------
# Fixture consistency: job.json reason string matches stellar_density_rho_sun
# ---------------------------------------------------------------------------

def test_fixture_stellar_density_reason_consistent_with_field():
    """
    In job.json, the stellar_density test_result reason must be consistent
    with whether stellar_density_rho_sun is present in the same vet entry.

    For KIC 11904151.01:
    - stellar_density_rho_sun = 1.09 (present, from Batalha+2011)
    - The reason must NOT say "not available"
    """
    data = json.loads(FIXTURE_JOB.read_text(encoding="utf-8"))
    vet_entries = data["report"]["vet"]

    for vet_entry in vet_entries:
        tce_id = vet_entry.get("tce_id", "unknown")
        rho = vet_entry.get("stellar_density_rho_sun")

        # Find the stellar_density test result
        stellar_result = None
        for tr in vet_entry.get("test_results", []):
            if tr.get("test_name") == "stellar_density":
                stellar_result = tr
                break

        if stellar_result is None:
            continue  # test not present in this entry — skip

        reason = stellar_result.get("reason", "")

        if rho is not None:
            # Data IS available — reason must not claim it's missing
            assert "not available" not in reason, (
                f"TCE {tce_id!r}: stellar_density_rho_sun={rho} is present, "
                f"but the reason falsely claims it is 'not available'.\n"
                f"  Reason: {reason!r}\n"
                f"Fix: update vet.py to say the check is not implemented, "
                f"not that data is absent."
            )
        else:
            # Data genuinely absent — reason should say so
            assert "not available" in reason.lower() or "not present" in reason.lower(), (
                f"TCE {tce_id!r}: stellar_density_rho_sun is None, "
                f"but the reason does not say the data is unavailable.\n"
                f"  Reason: {reason!r}"
            )
