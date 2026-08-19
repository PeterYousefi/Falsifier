#!/usr/bin/env python3
"""
scripts/merge_injection_recovery.py
=====================================
Merge per-star injection_recovery_<STAR>.json shards produced by the
parallelised GitHub Actions matrix job into a single
data/artifacts/injection_recovery.json artifact.

Each shard is a complete InjectionRecoveryArtifact with its own results and
completeness_bins.  This script concatenates the results lists, re-computes
completeness bins from the merged results, re-runs the asymptote checks, and
writes the merged artifact plus its manifest sidecar.

Usage
-----
    python scripts/merge_injection_recovery.py \
        --shard-dir data/artifacts/shards \
        --output-dir data/artifacts \
        [--no-plot]

The shard directory must contain files matching
``injection_recovery_KIC*.json``.

All shards must share the same schema_version, depth_grid_ppm,
period_grid_ppm, period_match_tolerance, sde_threshold, transit_shape, and
detection_algorithm.  A shard produced with BLS_fallback is rejected.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.pipeline_constants import (
    DEPTH_GRID_PPM,
    PERIOD_GRID_DAYS,
)
from scripts.injection_recovery import (
    InjectionParams,
    RecoveryResult,
    CompletenenessBin,
    compute_completeness_bins,
    check_asymptotes,
    report_asymptotes,
    write_completeness_plot,
)

OUTPUT_ARTIFACT_NAME = "injection_recovery.json"
COMPLETENESS_PLOT_NAME = "injection_recovery_completeness.png"


def _load_shard(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _result_from_dict(d: dict) -> RecoveryResult:
    return RecoveryResult(
        injection=InjectionParams(
            star_id=d["star_id"],
            injection_index=d["injection_index"],
            period_days=d["period_days"],
            depth_ppm=d["depth_ppm"],
            epoch_bkjd=d["epoch_bkjd"],
            duration_hours=d["duration_hours"],
        ),
        recovered=d["recovered"],
        recovered_period_days=d.get("recovered_period_days"),
        recovered_sde=d.get("recovered_sde"),
        recovered_depth_ppm=d.get("recovered_depth_ppm"),
        period_fractional_error=d.get("period_fractional_error"),
        odd_even_outcome=d.get("odd_even_outcome"),
        disposition=d.get("disposition"),
        error_message=d.get("error_message"),
    )


def _result_to_dict(r: RecoveryResult) -> dict:
    return {
        "star_id": r.injection.star_id,
        "injection_index": r.injection.injection_index,
        "period_days": r.injection.period_days,
        "depth_ppm": r.injection.depth_ppm,
        "epoch_bkjd": r.injection.epoch_bkjd,
        "duration_hours": r.injection.duration_hours,
        "recovered": r.recovered,
        "recovered_period_days": r.recovered_period_days,
        "recovered_sde": r.recovered_sde,
        "recovered_depth_ppm": r.recovered_depth_ppm,
        "period_fractional_error": r.period_fractional_error,
        "odd_even_outcome": r.odd_even_outcome,
        "disposition": r.disposition,
        "error_message": r.error_message,
    }


def main(argv: list[str] | None = None) -> int:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("merge_injection_recovery")

    p = argparse.ArgumentParser(description=__doc__.splitlines()[1].strip())
    p.add_argument("--shard-dir", type=Path, required=True,
                   help="Directory containing injection_recovery_kic*.json shards")
    p.add_argument("--output-dir", type=Path, default=Path("data/artifacts"),
                   help="Where to write the merged artifact (default: data/artifacts)")
    p.add_argument("--no-plot", action="store_true", help="Skip the completeness PNG")
    p.add_argument("--allow-bls-fallback", action="store_true",
                   help=(
                       "Allow merging BLS_fallback shards (wiring/CI tests only). "
                       "Never set this for a production artifact commit."
                   ))
    args = p.parse_args(argv)

    # Match both the old per-star pattern and the new per-(star × depth) pattern.
    # Both are anchored to injection_recovery_kic*.json (lower or upper case).
    # Manifest sidecars (.manifest.json) are excluded.
    shard_paths = sorted(
        p for p in (
            set(args.shard_dir.glob("injection_recovery_KIC*.json")) |
            set(args.shard_dir.glob("injection_recovery_kic*.json"))
        )
        if ".manifest." not in p.name
    )
    if not shard_paths:
        log.error("No shard files found in %s (tried injection_recovery_kic*.json / KIC*.json)", args.shard_dir)
        return 1

    log.info("Found %d shards: %s", len(shard_paths), [p.name for p in shard_paths])

    shards = [_load_shard(p) for p in shard_paths]

    # Validate consistency across shards
    ref = shards[0]
    for s in shards[1:]:
        for field in ("schema_version", "depth_grid_ppm", "period_grid_days",
                      "period_match_tolerance", "sde_threshold", "transit_shape",
                      "detection_algorithm", "random_seed"):
            if s.get(field) != ref.get(field):
                log.error(
                    "Shard inconsistency: field=%r  shard0=%r  shard=%r",
                    field, ref.get(field), s.get(field),
                )
                return 1

    if ref.get("detection_algorithm") != "TLS":
        if args.allow_bls_fallback:
            log.warning(
                "Shards used %r (not TLS) — proceeding because --allow-bls-fallback "
                "was set. Do NOT commit this artifact.",
                ref.get("detection_algorithm"),
            )
        else:
            log.error(
                "Shards used %r, not TLS. Re-run with TLS installed. "
                "Pass --allow-bls-fallback to merge anyway (wiring tests only).",
                ref.get("detection_algorithm"),
            )
            return 1

    # Merge results
    all_results_dicts: list[dict] = []
    for s in shards:
        all_results_dicts.extend(s["results"])

    all_results = [_result_from_dict(d) for d in all_results_dicts]
    n_total = len(all_results)
    n_completed = sum(1 for r in all_results if r.error_message is None)
    n_recovered = sum(1 for r in all_results if r.recovered)

    depth_grid = ref["depth_grid_ppm"]
    period_grid = ref["period_grid_days"]

    log.info(
        "Merged %d results from %d shards: %d completed, %d recovered (%.1f%%)",
        n_total, len(shards), n_completed, n_recovered,
        100.0 * n_recovered / n_total if n_total else 0.0,
    )

    # Re-compute completeness bins from merged results
    bins = compute_completeness_bins(all_results, period_grid, depth_grid)

    log.info("=== Completeness summary ===")
    for b in sorted(bins, key=lambda x: (x.depth_ppm, x.period_days)):
        if b.n_injected > 0:
            log.info(
                "  depth=%6d ppm  period=%5.1f d  "
                "recovered=%d/%d  rate=%.2f  68%%CI=[%.2f, %.2f]",
                int(b.depth_ppm), b.period_days,
                b.n_recovered, b.n_injected,
                b.recovery_rate,
                b.recovery_rate_lower_68, b.recovery_rate_upper_68,
            )

    asym_low, asym_high = check_asymptotes(bins, depth_grid)
    if ref.get("detection_algorithm") == "TLS":
        report_asymptotes(asym_low, asym_high)  # raises RuntimeError if either fails
    else:
        log.info("Asymptote check skipped (BLS fallback — not a production merge).")

    # Collect all quiet stars from shards
    quiet_stars: list[str] = []
    seen: set[str] = set()
    for s in shards:
        for star in s.get("quiet_stars", []):
            if star not in seen:
                quiet_stars.append(star)
                seen.add(star)

    run_id = str(uuid.uuid4())
    produced_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    payload = {
        "schema_version": ref["schema_version"],
        "script_version": ref.get("script_version", "0.1.0"),
        "run_id": run_id,
        "produced_at": produced_at,
        "random_seed": ref["random_seed"],
        "n_injections_attempted": n_total,
        "n_injections_completed": n_completed,
        "period_grid_days": period_grid,
        "depth_grid_ppm": depth_grid,
        "period_match_tolerance": ref["period_match_tolerance"],
        "sde_threshold": ref["sde_threshold"],
        "transit_shape": ref["transit_shape"],
        "quiet_stars": quiet_stars,
        "source_doi": ref["source_doi"],
        "access_date": ref["access_date"],
        "row_count": n_total,
        "detection_algorithm": ref["detection_algorithm"],
        "asymptote_low_depth": asym_low,
        "asymptote_high_depth": asym_high,
        "results": all_results_dicts,
        "completeness_bins": [
            {
                "period_days": b.period_days,
                "depth_ppm": b.depth_ppm,
                "n_injected": b.n_injected,
                "n_recovered": b.n_recovered,
                "recovery_rate": round(b.recovery_rate, 4) if not math.isnan(b.recovery_rate) else None,
                "recovery_rate_lower_68": round(b.recovery_rate_lower_68, 4),
                "recovery_rate_upper_68": round(b.recovery_rate_upper_68, 4),
            }
            for b in bins
        ],
        "plot_artifact_path": str(args.output_dir / COMPLETENESS_PLOT_NAME),
        "notes": (
            "Injection-recovery completeness for the Falsifier pipeline. "
            f"Merged from {len(shards)} per-star shards. "
            f"Overall recovery rate: {n_recovered}/{n_total} = "
            f"{100.0 * n_recovered / n_total:.1f}% (all depths and periods combined). "
            f"Detection algorithm: {ref['detection_algorithm']}. "
            "Transit shape: box (conservative). "
            "Multi-quarter stitched baseline (Q1–Q8, ~720 d). "
            "Vet stage not run in bulk injection-recovery; see adversarial_selftest.py "
            "for false-positive rates."
        ),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / OUTPUT_ARTIFACT_NAME
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    sha256 = hashlib.sha256(out_path.read_bytes()).hexdigest()
    log.info("Merged artifact: %s  (sha256: %s...)", out_path, sha256[:12])

    manifest_path = out_path.with_suffix(".manifest.json")
    manifest = {
        "artifact": str(out_path),
        "sha256": sha256,
        "source_doi": ref["source_doi"],
        "access_date": ref["access_date"],
        "row_count": n_total,
        "produced_at": produced_at,
        "run_id": run_id,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    log.info("Manifest: %s", manifest_path)

    if not args.no_plot:
        plot_path = args.output_dir / COMPLETENESS_PLOT_NAME
        write_completeness_plot(bins, period_grid, depth_grid, plot_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
