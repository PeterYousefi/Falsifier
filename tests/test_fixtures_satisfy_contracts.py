"""
tests/test_fixtures_satisfy_contracts.py
=========================================
Contract test: every committed fixture JSON must satisfy the API-layer
Pydantic models (DetectionReport → VetResult).

Motivation (D3 from competition gap analysis)
---------------------------------------------
fixtures/job.json was hand-authored and had never been passed through the
Pydantic models, so the VetResult model_validator that enforces the disposition
truth table had never run against it.

This test:
  1. Discovers all committed fixture JSON files in:
       frontend/src/fixtures/      (frontend fixtures served in fixture-mode)
       tests/fixtures/api/         (backend API fixtures)
  2. Filters to job-record shapes (must have "job_id" and "report" keys).
  3. Constructs DetectionReport(**data["report"]) for each file.
  4. For every VetResult inside report.vet, also constructs VetResult(**vet_dict)
     directly so the model_validator fires regardless of how Pydantic nests it.
  5. Any ValidationError is a test failure with the verbatim Pydantic message.

Policy
------
- Pure stdlib + pydantic — no astropy, no network.
- No scientific values are asserted here; only structural consistency.
- Adding a new fixture without updating it to satisfy the contracts is a
  CI-blocking failure, not a warning.

Outcome enum coverage (P1 contract)
------------------------------------
Also asserts that the set of outcome strings used in any fixture's test_results
is a subset of the four canonical VettingTestOutcome values.  This catches a
hand-authored fixture that introduces a fifth value before any TypeScript check
fires.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from falsifier.api.models import DetectionReport, VetResult

# ---------------------------------------------------------------------------
# Fixture discovery
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_FIXTURE_DIRS = [
    _REPO_ROOT / "frontend" / "src" / "fixtures",
    _REPO_ROOT / "tests" / "fixtures" / "api",
]

_CANONICAL_OUTCOMES = frozenset({"PASS", "FAIL", "FLAG", "INCONCLUSIVE"})


def _collect_fixture_paths() -> list[Path]:
    paths: list[Path] = []
    for d in _FIXTURE_DIRS:
        if d.exists():
            paths.extend(sorted(d.glob("*.json")))
    return paths


def _is_job_record(data: dict) -> bool:
    """Return True if the JSON looks like a JobRecord (has job_id + report)."""
    return isinstance(data, dict) and "job_id" in data and "report" in data


# ---------------------------------------------------------------------------
# Parametrised test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture_path", _collect_fixture_paths(), ids=lambda p: p.name)
def test_fixture_satisfies_detection_report_contract(fixture_path: Path) -> None:
    """
    Load one fixture JSON and construct DetectionReport from its report block.

    Fails with verbatim ValidationError if the report does not satisfy the
    DetectionReport schema (including the VetResult truth-table validator
    added for Option B).
    """
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))

    if not _is_job_record(raw):
        pytest.skip(f"{fixture_path.name}: not a job-record shape (no job_id/report keys)")

    report_dict = raw["report"]

    try:
        report = DetectionReport(**report_dict)
    except ValidationError as exc:
        pytest.fail(
            f"DetectionReport(**{fixture_path.name}['report']) raised ValidationError:\n"
            + exc.json(indent=2)
        )

    # Extra: validate each VetResult individually so the model_validator fires
    # even if Pydantic coerces the nested list without running it.
    for i, vet_dict in enumerate(report_dict.get("vet", [])):
        try:
            VetResult(**vet_dict)
        except ValidationError as exc:
            pytest.fail(
                f"VetResult(**{fixture_path.name}['report']['vet'][{i}]) raised ValidationError:\n"
                + exc.json(indent=2)
            )


@pytest.mark.parametrize("fixture_path", _collect_fixture_paths(), ids=lambda p: p.name)
def test_fixture_outcomes_are_canonical(fixture_path: Path) -> None:
    """
    Every outcome string in any fixture test_results must be one of the four
    canonical VettingTestOutcome values (PASS / FAIL / FLAG / INCONCLUSIVE).

    Prevents a hand-authored fixture from introducing a fifth outcome value
    that would silently pass TypeScript but break the Python truth-table
    validator and the outcomeConfig exhaustiveness contract.
    """
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))

    if not _is_job_record(raw):
        pytest.skip(f"{fixture_path.name}: not a job-record shape")

    for vet_entry in raw.get("report", {}).get("vet", []):
        for result in vet_entry.get("test_results", []):
            outcome = result.get("outcome")
            assert outcome in _CANONICAL_OUTCOMES, (
                f"{fixture_path.name}: test_results entry has outcome={outcome!r}, "
                f"which is not in {sorted(_CANONICAL_OUTCOMES)}."
            )
