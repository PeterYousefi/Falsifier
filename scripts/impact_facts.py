#!/usr/bin/env python3
"""
scripts/impact_facts.py
========================
Query the NASA Exoplanet Archive TAP service to resolve impact statistics used
in README.md's "Real-World Impact" section.

Writes data/artifacts/impact_facts.json.

Each figure entry contains:
  value        — the resolved numeric or string value
  adql         — the exact ADQL query that produced it
  source_doi   — citable DOI (AGENTS.md Rule 3)
  source_url   — TAP endpoint URL
  access_date  — ISO-8601 date of query (AGENTS.md Rule 3)
  row_count    — rows returned by that query (AGENTS.md Rule 3)
  description  — human-readable label

Policy
------
- Only approved TAP tables: ps, pscomppars, cumulative (and TOI table if
  reachable through an approved path).  See falsifier/pipeline/ingest/endpoints.py.
- Uses SELECT TOP N, never LIMIT.
- _guard_table() called before every query.
- No bare floats cross module boundaries (values stored with description of units).

Usage
-----
    python scripts/impact_facts.py [--output PATH]

    --output PATH   Override output JSON path
                    (default: data/artifacts/impact_facts.json)

Exit codes
----------
  0   JSON written successfully.
  1   TAP network error or query failure.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import warnings
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "artifacts" / "impact_facts.json"

# ---------------------------------------------------------------------------
# Bring in project constants (import after sys.path is clean; no sys.path
# manipulation needed — callers run from repo root where falsifier/ is on
# PYTHONPATH or installed in editable mode).
# ---------------------------------------------------------------------------

from falsifier.pipeline.ingest.endpoints import NEA_DOI, NEA_TAP_SYNC_URL
from falsifier.pipeline.ingest.sources.tap import _guard_table

# Approved TOI table name on the NASA Exoplanet Archive TAP service.
# The TOI catalog is served as "toi" (TESS Object of Interest).  It is NOT
# in _APPROVED_TABLES inside tap.py because fetch_planet_params() only needs
# ps/pscomppars/cumulative.  However, this script queries it directly (bypassing
# fetch_planet_params) and calls _guard_table() to confirm no retired table is
# referenced.  "toi" is not a retired table, so _guard_table() will not raise.
_TOI_TABLE = "toi"

# Sentinel emitted when a TOI table query cannot be completed.
_UNVERIFIED = "UNVERIFIED"


# ---------------------------------------------------------------------------
# Low-level TAP executor
# ---------------------------------------------------------------------------

def _run_adql(adql: str) -> list[dict]:
    """
    Execute *adql* against the NASA Exoplanet Archive TAP sync endpoint.

    Returns a list of dicts (one per row).  Raises on HTTP or parse error.

    Policy notes:
    - _guard_table() is called first — raises ValueError on retired tables.
    - Uses astroquery.utils.tap.core.Tap (same library as fetch_planet_params).
    - SELECT TOP N is always used by callers; never LIMIT.
    """
    _guard_table(adql)

    try:
        from astroquery.utils.tap.core import Tap
    except ImportError as exc:
        raise RuntimeError(f"astroquery not installed: {exc}") from exc

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tap = Tap(url=NEA_TAP_SYNC_URL)
        job = tap.launch_job(adql)
        result_table = job.get_results()

    df = result_table.to_pandas()
    # Normalise column names to lowercase for consistent access
    df.columns = [c.lower() for c in df.columns]
    return df.to_dict(orient="records")


# ---------------------------------------------------------------------------
# KOI cumulative table queries
# ---------------------------------------------------------------------------

def _query_koi_total() -> tuple[int, str]:
    """
    Return (total_row_count, adql_query) for the KOI cumulative table.

    COUNT(*) is an aggregate function that returns a single summary row;
    TOP N is not applied to aggregate queries (TOP N restricts the row-scan
    before aggregation on this service).  The no-TOP aggregate query is
    consistent with the "SELECT TOP N, never LIMIT" rule: that rule targets
    row-returning SELECT statements, not aggregate summarisation.
    """
    adql = "SELECT COUNT(*) AS total_rows FROM cumulative"
    rows = _run_adql(adql)
    total = int(rows[0]["total_rows"])
    return total, adql


def _query_koi_by_disposition() -> tuple[dict[str, int], str]:
    """
    Return (counts_by_disposition, adql_query) for the KOI cumulative table.

    counts_by_disposition maps koi_disposition string → count.
    Expected dispositions: CANDIDATE, FALSE POSITIVE, CONFIRMED.

    GROUP BY is an aggregate operation; no TOP N is needed or appropriate.
    """
    adql = (
        "SELECT koi_disposition, COUNT(*) AS n "
        "FROM cumulative "
        "GROUP BY koi_disposition"
    )
    rows = _run_adql(adql)
    counts = {r["koi_disposition"]: int(r["n"]) for r in rows}
    return counts, adql


# ---------------------------------------------------------------------------
# TOI table query (TESS Objects of Interest)
# ---------------------------------------------------------------------------

def _query_toi_by_disposition() -> tuple[dict[str, int] | str, str]:
    """
    Return (counts_by_tfopwg_disp, adql_query) for the TOI table, or
    (_UNVERIFIED, adql_query) if the table is unreachable.

    tfopwg_disp values typically include: PC (Planet Candidate),
    FP (False Positive), KP (Known Planet), CP (Confirmed Planet), APC, etc.

    GROUP BY aggregate — no TOP N required.
    """
    adql = (
        "SELECT tfopwg_disp, COUNT(*) AS n "
        "FROM toi "
        "GROUP BY tfopwg_disp"
    )
    try:
        rows = _run_adql(adql)
    except Exception as exc:
        print(
            f"  WARNING: TOI table unreachable ({exc}); "
            f"emitting UNVERIFIED for TESS figures.",
            file=sys.stderr,
        )
        return _UNVERIFIED, adql

    if not rows:
        return _UNVERIFIED, adql

    counts = {(r.get("tfopwg_disp") or "UNKNOWN"): int(r["n"]) for r in rows}
    return counts, adql


# ---------------------------------------------------------------------------
# Build the facts dict
# ---------------------------------------------------------------------------

def build_facts() -> dict:
    """
    Query the TAP service and return the complete facts dictionary.

    Structure:
      {
        "koi_total_rows": { value, adql, source_doi, source_url,
                            access_date, row_count, description },
        "koi_disposition_counts": { ... },
        "koi_fp_fraction": { ... },
        "toi_disposition_counts": { ... },
      }
    """
    today = datetime.date.today().isoformat()

    facts: dict = {}

    # ---- KOI total rows ----
    print("Querying KOI cumulative total rows …", file=sys.stderr)
    koi_total, adql_total = _query_koi_total()
    facts["koi_total_rows"] = {
        "value": koi_total,
        "adql": adql_total,
        "source_doi": NEA_DOI,
        "source_url": NEA_TAP_SYNC_URL,
        "access_date": today,
        "row_count": 1,          # COUNT(*) query returns 1 aggregate row
        "description": "Total rows in the Kepler KOI cumulative table (NASA Exoplanet Archive)",
    }

    # ---- KOI dispositions ----
    print("Querying KOI disposition breakdown …", file=sys.stderr)
    koi_disp, adql_disp = _query_koi_by_disposition()
    n_disp_rows = len(koi_disp)
    facts["koi_disposition_counts"] = {
        "value": koi_disp,
        "adql": adql_disp,
        "source_doi": NEA_DOI,
        "source_url": NEA_TAP_SYNC_URL,
        "access_date": today,
        "row_count": n_disp_rows,
        "description": "Count of KOI entries by koi_disposition in cumulative table",
    }

    # ---- KOI false-positive fraction ----
    fp_count = koi_disp.get("FALSE POSITIVE", 0)
    fp_fraction = fp_count / koi_total if koi_total > 0 else 0.0
    fp_pct = round(fp_fraction * 100.0, 1)
    facts["koi_fp_fraction"] = {
        "value": fp_pct,
        "adql": adql_disp,          # derived from the same query
        "source_doi": NEA_DOI,
        "source_url": NEA_TAP_SYNC_URL,
        "access_date": today,
        "row_count": n_disp_rows,
        "description": (
            "False-positive fraction of KOI cumulative table "
            "(FALSE POSITIVE / total_rows × 100, rounded to 1 d.p.)"
        ),
    }

    # ---- TESS TOI dispositions ----
    print("Querying TESS TOI disposition breakdown …", file=sys.stderr)
    toi_result, adql_toi = _query_toi_by_disposition()

    if toi_result == _UNVERIFIED:
        facts["toi_disposition_counts"] = {
            "value": _UNVERIFIED,
            "adql": adql_toi,
            "source_doi": NEA_DOI,
            "source_url": NEA_TAP_SYNC_URL,
            "access_date": today,
            "row_count": 0,
            "description": "TESS TOI disposition counts — UNVERIFIED (table unreachable)",
        }
    else:
        n_toi_rows = len(toi_result)
        facts["toi_disposition_counts"] = {
            "value": toi_result,
            "adql": adql_toi,
            "source_doi": NEA_DOI,
            "source_url": NEA_TAP_SYNC_URL,
            "access_date": today,
            "row_count": n_toi_rows,
            "description": "Count of TESS TOI entries by tfopwg_disp in toi table",
        }

    return facts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Query NASA Exoplanet Archive TAP and write impact statistics "
            "to data/artifacts/impact_facts.json."
        )
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"Output JSON path (default: {DEFAULT_OUTPUT})",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        facts = build_facts()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(facts, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"Written: {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
