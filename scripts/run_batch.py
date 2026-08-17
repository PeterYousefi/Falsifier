#!/usr/bin/env python3
"""
scripts/run_batch.py
=====================
CLI entry point for the offline retrieve+screen batch pipeline.

Usage
-----
    python scripts/run_batch.py [OPTIONS]

Options
-------
  --targets PATH       Path to curated_targets.json
                       (default: data/targets/curated_targets.json)
  --output PATH        Root directory for batch artifacts
                       (default: data/artifacts/batch/)
  --planet NAME        Process only this planet (repeatable)
  --force              Re-run even if cached artifacts exist
  --dry-run            Validate target list; do not run any stages
  --quiet              Suppress per-target progress output

Exit codes
----------
  0   All targets processed successfully (ok or cached)
  1   One or more targets failed; see BATCH_MANIFEST.json for details
  2   Input error (missing target list, schema error)

Exploratory status
------------------
This script runs the exploratory retrieve+screen pipeline.
Output is NOT validated against ground truth.
See README §Exploratory Modules.

Non-claim
---------
This project is not a biosignature detector.
No exoplanet biosignature has ever been confirmed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Offline retrieve+screen batch pipeline over a curated target list.  "
            "EXPLORATORY — not validated against ground truth."
        )
    )
    p.add_argument(
        "--targets",
        type=Path,
        default=REPO_ROOT / "data" / "targets" / "curated_targets.json",
        help="Path to curated_targets.json",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "data" / "artifacts" / "batch",
        help="Root directory for batch artifacts",
    )
    p.add_argument(
        "--planet",
        action="append",
        dest="planets",
        metavar="NAME",
        help="Process only this planet (repeatable)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-run even if cached artifacts exist",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate target list; do not run any stages",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-target progress output",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    print(
        "[run_batch] EXPLORATORY module — not validated against ground truth.\n"
        "[run_batch] No exoplanet biosignature has ever been confirmed.\n"
        "[run_batch] Source flux ratios are screening metrics only.",
        flush=True,
    )

    if not args.targets.exists():
        print(
            f"ERROR: Target list not found: {args.targets}\n"
            "Populate data/targets/curated_targets.json before running.",
            file=sys.stderr,
        )
        return 2

    try:
        from falsifier.pipeline.batch.runner import run_batch
    except ImportError as exc:
        print(
            f"ERROR: Cannot import batch runner: {exc}\n"
            "Install with: pip install -e '.[dev]'",
            file=sys.stderr,
        )
        return 2

    try:
        results = run_batch(
            target_list_path=args.targets,
            artifact_dir=args.output,
            force=args.force,
            dry_run=args.dry_run,
            planet_filter=args.planets,
            verbose=not args.quiet,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    n_failed = sum(1 for r in results if r.status == "failed")
    n_ok = sum(1 for r in results if r.status in ("ok", "cached"))

    print(
        f"\n[run_batch] {n_ok}/{len(results)} targets ok, "
        f"{n_failed} failed.",
        flush=True,
    )
    if n_failed:
        print(
            f"[run_batch] See data/artifacts/batch/BATCH_MANIFEST.json for details.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
