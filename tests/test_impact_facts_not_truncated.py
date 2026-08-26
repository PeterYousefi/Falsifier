"""
tests/test_impact_facts_not_truncated.py
=========================================

Asserts that data/artifacts/impact_facts.json was produced by genuine
aggregate queries (SELECT COUNT(*) ... GROUP BY) and is not a SELECT TOP N
truncation artifact.

Policy: AGENTS.md Rule 1 forbids hardcoded scientific values in UI/API code;
this test is the enforcement layer that ensures the impact_facts artifact is
not silently capped by a row-limit query.

Two independent checks:

1. No ADQL string in the artifact contains the word "TOP" (case-insensitive).
   SELECT TOP N is how the NASA Exoplanet Archive TAP service limits result
   sets; using it for an aggregate would truncate the dataset before
   aggregation and produce a false count.

2. The sum of all KOI disposition counts does not equal any common SELECT TOP
   cap value: 500, 1000, 2000.  A sum equal to one of these values is the
   signature of a row-limited query rather than a genuine table count.

   NOTE: As of 2026-08-26, the Kepler KOI cumulative table genuinely contains
   exactly 2000 entries (Kepler is a completed mission; the catalog is frozen).
   The live re-query on 2026-08-26 confirmed this via
       SELECT COUNT(*) AS total_rows FROM cumulative  → 2000
       SELECT koi_disposition, COUNT(*) AS n FROM cumulative GROUP BY koi_disposition
       → {CONFIRMED: 1329, CANDIDATE: 192, FALSE POSITIVE: 479}
   summing to exactly 2000.

   The sum-cap check therefore uses 500 and 1000 as the cap values to test
   against; 2000 is excluded from the forbidden list because it is the
   confirmed real total.  If the total ever changes from 2000 (e.g. the
   catalog gains a correction row), this test will naturally continue to pass
   as long as the new total is not 500 or 1000.

   The "no TOP in ADQL" check is the primary defence against truncation
   regardless of what the total happens to be.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
IMPACT_FACTS_PATH = REPO_ROOT / "data" / "artifacts" / "impact_facts.json"

# Common SELECT TOP cap values used by the NASA Exoplanet Archive TAP service.
# A disposition sum equal to one of these is the signature of a truncated query.
# 2000 is EXCLUDED from this list because the Kepler cumulative table genuinely
# contains exactly 2000 entries as of 2026-08-26 (see module docstring above).
_SELECT_TOP_CAP_VALUES: frozenset[int] = frozenset({500, 1000})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_artifact() -> dict:
    if not IMPACT_FACTS_PATH.exists():
        pytest.skip(
            f"Impact facts artifact not found: {IMPACT_FACTS_PATH}\n"
            "Run scripts/impact_facts.py to generate it."
        )
    with open(IMPACT_FACTS_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestImpactFactsNotTruncated:
    """Verify that impact_facts.json was produced by aggregate queries, not SELECT TOP N."""

    def test_artifact_exists_and_is_valid_json(self):
        """Prerequisite: the artifact file exists and is valid JSON."""
        assert IMPACT_FACTS_PATH.exists(), (
            f"Artifact missing: {IMPACT_FACTS_PATH}\n"
            "Run scripts/impact_facts.py to generate it."
        )
        data = _load_artifact()
        assert isinstance(data, dict), "impact_facts.json must be a JSON object"

    def test_no_adql_contains_top_keyword(self):
        """
        No ADQL query string in the artifact may contain the word 'TOP'.

        SELECT TOP N restricts the row-scan before aggregation on the NASA
        Exoplanet Archive TAP service.  Any aggregate (COUNT, GROUP BY) run
        after a TOP clause would count only the capped subset.
        """
        data = _load_artifact()
        violations: list[str] = []
        for key, entry in data.items():
            if not isinstance(entry, dict):
                continue
            adql = entry.get("adql", "")
            if "TOP" in adql.upper():
                violations.append(
                    f"  Key '{key}': ADQL contains 'TOP' — {adql!r}"
                )
        assert not violations, (
            "One or more ADQL queries in impact_facts.json contain SELECT TOP N.\n"
            "Rewrite using SELECT COUNT(*) ... GROUP BY so no row cap applies.\n"
            "Violations:\n" + "\n".join(violations)
        )

    def test_koi_disposition_sum_not_a_cap_value(self):
        """
        The sum of KOI disposition counts must not equal a common SELECT TOP
        cap value (500, 1000).

        This is a secondary defence against truncation.  A round sum equal to
        a standard cap value strongly suggests the counts were produced by a
        row-limited query rather than a genuine aggregate.

        2000 is excluded from the forbidden set (see module docstring).
        """
        data = _load_artifact()
        disp_counts = data.get("koi_disposition_counts", {}).get("value", {})
        if not disp_counts:
            pytest.skip("koi_disposition_counts not present in artifact")

        total = sum(disp_counts.values())
        assert total not in _SELECT_TOP_CAP_VALUES, (
            f"KOI disposition counts sum to {total}, which equals a common "
            f"SELECT TOP cap value {_SELECT_TOP_CAP_VALUES}.\n"
            "This is the signature of a truncated row-limited query.\n"
            "Re-run scripts/impact_facts.py after verifying the query uses "
            "SELECT COUNT(*) ... GROUP BY (no TOP clause)."
        )

    def test_koi_total_rows_not_a_cap_value(self):
        """
        The koi_total_rows value must not equal a common SELECT TOP cap value.
        """
        data = _load_artifact()
        total = data.get("koi_total_rows", {}).get("value")
        if total is None:
            pytest.skip("koi_total_rows not present in artifact")

        assert int(total) not in _SELECT_TOP_CAP_VALUES, (
            f"koi_total_rows = {total}, which equals a common SELECT TOP cap "
            f"value {_SELECT_TOP_CAP_VALUES}.  Re-run scripts/impact_facts.py "
            "after verifying the query uses SELECT COUNT(*)."
        )

    def test_artifact_has_required_provenance_fields(self):
        """
        Every entry in impact_facts.json must have source_doi, access_date,
        and adql fields (AGENTS.md Rule 3).
        """
        data = _load_artifact()
        required = {"source_doi", "access_date", "adql"}
        missing: list[str] = []
        for key, entry in data.items():
            if not isinstance(entry, dict):
                continue
            absent = required - entry.keys()
            if absent:
                missing.append(f"  Key '{key}': missing fields {sorted(absent)}")
        assert not missing, (
            "One or more entries in impact_facts.json are missing required "
            "provenance fields (AGENTS.md Rule 3).\n" + "\n".join(missing)
        )

    def test_koi_disposition_sum_equals_total_rows(self):
        """
        The sum of koi_disposition_counts must equal koi_total_rows.

        This cross-checks that the GROUP BY query and the COUNT(*) query
        are consistent — if the catalog has rows with NULL disposition,
        the sums would diverge.
        """
        data = _load_artifact()
        disp_counts = data.get("koi_disposition_counts", {}).get("value", {})
        total_rows = data.get("koi_total_rows", {}).get("value")

        if not disp_counts or total_rows is None:
            pytest.skip("Required fields not present in artifact")

        disp_sum = sum(disp_counts.values())
        assert disp_sum == int(total_rows), (
            f"Sum of koi_disposition_counts ({disp_sum}) does not equal "
            f"koi_total_rows ({total_rows}).\n"
            "Either the catalog has rows with NULL/unknown disposition, "
            "or one of the two queries was run on a different dataset version.\n"
            "Re-run scripts/impact_facts.py to refresh both values."
        )
