"""
tests/test_cross_fixture_tce_consistency.py
=============================================
Policy gate: every TCE shared across multiple fixture JSON files must report
the same period_days and depth_ppm.

Fix 2 regression guard.

If ``job.json`` and ``chat.json`` (or any future fixture) describe the same
``tce_id`` with different numeric parameters, one of them is wrong.  This test
catches that class of divergence before it can mislead a judge or a user.

Motivation
----------
KIC 11904151.01 was reported as depth_ppm=176 in job.json and depth_ppm=154 in
chat.json.  The TLS run on the committed golden FITS (kepler10_q3_long.fits)
returns depth≈176 ppm (exact: ~175.8 ppm, rounded to 176).  The 154 value in
chat.json was wrong.  This test would have caught that divergence at CI time.

Scope
-----
- Discovers all ``*.json`` files in ``frontend/src/fixtures/``.
- Collects ``(tce_id, period_days)`` and ``(tce_id, depth_ppm)`` pairs from
  any file with job-record structure (has "report" key with "vet" list) OR from
  any file with a direct tool-call result containing ``tce_id``, ``depth_ppm``.
- Also checks ``chat.json``-style tool call results for ``period_days`` /
  ``depth_ppm`` fields keyed by ``tce_id``.

Policy
------
- Pure stdlib — no network, no pipeline imports.
- Any tce_id appearing in two or more places with a different period_days or
  depth_ppm is a CI-blocking failure.

Markers
-------
@pytest.mark.no_network — no outgoing connections.
"""

from __future__ import annotations

import json
import pathlib
from collections import defaultdict
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent
FIXTURE_DIR = REPO_ROOT / "frontend" / "src" / "fixtures"

pytestmark = pytest.mark.no_network

# Tolerance for period_days comparison: two values are "the same" if they
# differ by less than 1e-4 days (~8.6 s).  Allows for rounding differences
# between a full-precision pipeline value and an abbreviated chat fixture.
_PERIOD_TOLERANCE_DAYS = 1e-4

# Tolerance for depth_ppm comparison: two values are "the same" if they
# differ by less than 5 ppm.  Allows for rounding to integer ppm.
_DEPTH_TOLERANCE_PPM = 5.0


def _collect_tce_params_from_fixtures() -> dict[str, dict[str, list[tuple[str, Any]]]]:
    """
    Scan all fixture JSON files and collect (tce_id → {field → [(filename, value)]}).

    Returns a nested dict:
      tce_id → {
        "period_days": [(filename, value), ...],
        "depth_ppm":   [(filename, value), ...],
      }
    """
    by_tce: dict[str, dict[str, list[tuple[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    if not FIXTURE_DIR.exists():
        return by_tce

    for path in sorted(FIXTURE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        filename = path.name

        # ── Job-record style (job.json) ─────────────────────────────────────
        # report.vet[].tce_id, period_days, depth_ppm
        if isinstance(data, dict) and "report" in data:
            for vet_entry in data["report"].get("vet", []):
                tce_id = vet_entry.get("tce_id")
                if not tce_id:
                    continue
                for field in ("period_days", "depth_ppm"):
                    val = vet_entry.get(field)
                    if val is not None:
                        by_tce[tce_id][field].append((filename, val))

        # ── Chat-style (chat.json) ──────────────────────────────────────────
        # messages[].tool_calls[].result.{tce_id, period_days, depth_ppm}
        if isinstance(data, dict) and "messages" in data:
            for msg in data.get("messages", []):
                for tool_call in msg.get("tool_calls", []):
                    result = tool_call.get("result", {})
                    if not isinstance(result, dict):
                        continue
                    # Some tool results carry tce_id explicitly; others are
                    # identified by the outer message's tce_id field.
                    tce_id = result.get("tce_id") or data.get("tce_id")
                    if not tce_id:
                        continue
                    for field in ("period_days", "depth_ppm"):
                        val = result.get(field)
                        if val is not None:
                            by_tce[tce_id][field].append((filename, val))

    return by_tce


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_cross_fixture_period_days_consistent():
    """
    Any tce_id present in multiple fixture files must have the same period_days
    (within 1e-4 day tolerance).

    This catches stale or hand-authored period values that disagree with the
    pipeline's TLS output on the committed golden FITS.
    """
    by_tce = _collect_tce_params_from_fixtures()

    failures = []
    for tce_id, fields in by_tce.items():
        entries = fields.get("period_days", [])
        if len(entries) < 2:
            continue  # only one source — nothing to cross-check
        values = [v for _, v in entries]
        min_v, max_v = min(values), max(values)
        if max_v - min_v > _PERIOD_TOLERANCE_DAYS:
            detail = ", ".join(f"{f}={v}" for f, v in entries)
            failures.append(
                f"  TCE {tce_id!r}: period_days values differ by "
                f"{max_v - min_v:.2e} d > tolerance {_PERIOD_TOLERANCE_DAYS:.0e} d\n"
                f"    Sources: {detail}"
            )

    assert not failures, (
        "Cross-fixture period_days inconsistency detected.\n"
        "All fixture files reporting the same tce_id must agree on period_days:\n"
        + "\n".join(failures)
    )


@pytest.mark.no_network
def test_cross_fixture_depth_ppm_consistent():
    """
    Any tce_id present in multiple fixture files must have the same depth_ppm
    (within 5 ppm tolerance for integer rounding).

    Catches the KIC 11904151.01 defect: job.json had 176, chat.json had 154.
    The correct value is 176 (from TLS on the committed golden FITS).

    Source of truth for KIC 11904151.01:
      TLS on data/golden/kepler10_q3_long.fits → depth ≈ 175.8 ppm → 176 ppm.
    """
    by_tce = _collect_tce_params_from_fixtures()

    failures = []
    for tce_id, fields in by_tce.items():
        entries = fields.get("depth_ppm", [])
        if len(entries) < 2:
            continue  # only one source — nothing to cross-check
        values = [v for _, v in entries]
        min_v, max_v = min(values), max(values)
        if max_v - min_v > _DEPTH_TOLERANCE_PPM:
            detail = ", ".join(f"{f}={v}" for f, v in entries)
            failures.append(
                f"  TCE {tce_id!r}: depth_ppm values differ by "
                f"{max_v - min_v:.1f} ppm > tolerance {_DEPTH_TOLERANCE_PPM:.0f} ppm\n"
                f"    Sources: {detail}\n"
                f"    Source of truth: TLS on data/golden/kepler10_q3_long.fits"
            )

    assert not failures, (
        "Cross-fixture depth_ppm inconsistency detected.\n"
        "All fixture files reporting the same tce_id must agree on depth_ppm:\n"
        + "\n".join(failures)
    )
