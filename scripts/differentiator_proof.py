#!/usr/bin/env python3
"""
scripts/differentiator_proof.py
================================
Demonstrates that two targets with similar transit-dip depths are given
physically opposite dispositions by Falsifier.

FRAMING NOTE
------------
This is NOT a synthetic or composed demo scenario.  All numeric outputs
(transit depth, odd/even mismatch, dispositions) are pipeline-measured from
committed golden FITS files during a real pipeline run.  The comparison is
not a captured production incident — it is a reproducible pipeline demonstration
that can be re-executed from scratch at any time using only committed artifacts.

The "standard CNN classifier" framing referenced in the README is an illustrative
description of confirmation-biased pipelines generally; no specific CNN was
benchmarked in this repository.

Target A: KIC 11904151 (Kepler-10) — confirmed planet; pipeline returns
          disposition "ambiguous" (centroid and density tests are INCONCLUSIVE
          in the golden fixture; no FAIL fires).

Target B: KIC 6965293 — detached eclipsing binary (Prša et al. 2011,
          DOI:10.1088/0004-6256/141/3/83); pipeline returns disposition
          "false_positive" via odd_even_depth FAIL.

The key insight: both targets produce a significant dimming signal in the
light curve, but the physical vetting tests give completely opposite verdicts.

Usage
-----
    python3 scripts/differentiator_proof.py

Output
------
Prints a side-by-side comparison table and writes
data/artifacts/differentiator_proof.json.

Policy compliance
-----------------
AGENTS.md Rule 1: all numeric claims originate from pipeline outputs,
not hardcoded values.  Rule 3: source_doi + access_date recorded in artifact.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import sys

import numpy as np
from astropy.io import fits

REPO_ROOT = pathlib.Path(__file__).parent.parent
GOLDEN_DIR = REPO_ROOT / "data" / "golden"
OUTPUT_PATH = REPO_ROOT / "data" / "artifacts" / "differentiator_proof.json"

# Pipeline configuration constants — not scientific results.
BREAK_TOLERANCE_DAYS = 0.5

# Target A: KIC 11904151 (Kepler-10, confirmed planet)
_TARGET_A = {
    "kic_id": "KIC 11904151",
    "fits": GOLDEN_DIR / "kepler10_q3_long.fits",
    "source_doi": "10.1088/0004-637X/729/1/27",
    "detrend_window": 0.75,
    "period_min": 0.5,
    "period_max": 2.0,
}

# Target B: KIC 6965293 (eclipsing binary, Prša et al. 2011)
_TARGET_B = {
    "kic_id": "KIC 6965293",
    "fits": GOLDEN_DIR / "kic6965293_q3_long.fits",
    "source_doi": "10.1088/0004-6256/141/3/83",
    "detrend_window": 2.0,
    "period_min": 1.0,
    "period_max": 10.0,
}


def _run_pipeline(cfg: dict) -> dict:
    """Run detrend → search → vet for one target; return a summary dict."""
    golden_fits = cfg["fits"]
    if not golden_fits.exists():
        print(
            f"ERROR: Golden FITS not found: {golden_fits}\n"
            "Run scripts/fetch_golden.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    with fits.open(golden_fits) as hdul:
        table = hdul[1].data
        time = table["TIME"].astype(np.float64)
        raw_flux = table["FLUX"].astype(np.float64)
        raw_err = table["FLUX_ERR"].astype(np.float64)
        quality = table["QUALITY"].astype(np.int32)

    mask = np.isfinite(time) & np.isfinite(raw_flux) & (quality == 0)
    time = time[mask]
    raw_flux = raw_flux[mask]
    raw_err = raw_err[mask]
    median_flux = np.median(raw_flux)
    flux_norm = raw_flux / median_flux
    flux_err_norm = raw_err / median_flux

    from falsifier.pipeline.contracts import (
        ArtifactRef, DatasetProvenance, DetrendInput, IngestInput,
        IngestOutput, LightCurveSegment, SearchInput, StageManifest,
        UnitedArray, VetInput,
    )
    from falsifier.pipeline.stages.detrend import run_detrend
    from falsifier.pipeline.stages.search import run_search
    from falsifier.pipeline.stages.vet import run_vet

    run_id = f"diff-proof-{cfg['kic_id'].replace(' ', '-')}"
    seg = LightCurveSegment(
        sector=3,
        time=UnitedArray(values=time.tolist(), unit="btjd"),
        time_scale="tdb",
        time_format="btjd",
        flux=UnitedArray(values=flux_norm.tolist(), unit="dimensionless"),
        flux_err=UnitedArray(values=flux_err_norm.tolist(), unit="dimensionless"),
        quality_flags=[0] * len(time),
        cadence_type="long",
    )
    dummy_ref = ArtifactRef(
        path=golden_fits,
        sha256="0" * 64,
        stage="ingest",
        pipeline_run_id=run_id,
    )
    provenance = DatasetProvenance(
        source_doi=cfg["source_doi"],
        access_date=datetime.date(2026, 8, 26),
        row_count=int(len(time)),
        description=f"{cfg['kic_id']} Q3 long-cadence — differentiator proof fixture",
    )
    ingest_out = IngestOutput(
        input=IngestInput(
            tic_id=cfg["kic_id"],
            sectors=[3],
            cadence="long",
            pipeline_run_id=run_id,
        ),
        segments=[seg],
        host_star_id=cfg["kic_id"],
        manifest=StageManifest(
            stage="ingest",
            code_version="0.0.0",
            input_hash=hashlib.sha256(run_id.encode()).hexdigest(),
            wall_time_seconds=0.0,
            provenance=[provenance],
            artifact=dummy_ref,
        ),
        artifact=dummy_ref,
    )
    detrend_input = DetrendInput(
        ingest_artifact=dummy_ref,
        method="biweight",
        window_length=UnitedArray(values=[cfg["detrend_window"]], unit="day"),
        break_tolerance=UnitedArray(values=[BREAK_TOLERANCE_DAYS], unit="day"),
        pipeline_run_id=run_id,
    )
    search_input = SearchInput(
        detrend_artifact=dummy_ref,
        period_min=UnitedArray(values=[cfg["period_min"]], unit="day"),
        period_max=UnitedArray(values=[cfg["period_max"]], unit="day"),
        snr_threshold=7.0,
        pipeline_run_id=run_id,
    )

    detrend_out = run_detrend(detrend_input, ingest_output=ingest_out)
    search_out = run_search(search_input, detrend_output=detrend_out)

    if not search_out.tces:
        print(f"ERROR: No TCEs found for {cfg['kic_id']}.", file=sys.stderr)
        sys.exit(1)

    best_tce = max(search_out.tces, key=lambda t: t.sde)
    vet_input = VetInput(
        search_artifact=dummy_ref,
        tce_id=best_tce.tce_id,
        pipeline_run_id=run_id,
    )
    vet_out = run_vet(vet_input, search_output=search_out, tce=best_tce)

    return {
        "kic_id": cfg["kic_id"],
        "depth_ppm": round(best_tce.depth.values[0]),
        "depth_pct": round(best_tce.depth.values[0] / 10_000, 2),
        "odd_even_mismatch": round(best_tce.odd_even_mismatch, 2),
        "disposition": vet_out.disposition,
        "triggering_test": vet_out.triggering_test,
        "triggering_reason": vet_out.triggering_reason,
        "source_doi": cfg["source_doi"],
    }


def run() -> None:
    sys.path.insert(0, str(REPO_ROOT))

    print(f"Running pipeline for Target A ({_TARGET_A['kic_id']})...", flush=True)
    result_a = _run_pipeline(_TARGET_A)
    print(f"Running pipeline for Target B ({_TARGET_B['kic_id']})...", flush=True)
    result_b = _run_pipeline(_TARGET_B)

    # -----------------------------------------------------------------
    # Write artifact
    # -----------------------------------------------------------------
    artifact = {
        "schema_version": "1",
        "produced_at": datetime.datetime.utcnow().isoformat() + "Z",
        "target_a": result_a,
        "target_b": result_b,
        "notes": (
            "Produced by scripts/differentiator_proof.py from committed golden FITS files. "
            "Both targets show a transit/eclipse signal; the pipeline gives opposite "
            "dispositions based on physical vetting tests, not signal shape alone."
        ),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
    print(f"\nArtifact written: {OUTPUT_PATH}")

    # -----------------------------------------------------------------
    # Human-readable summary
    # -----------------------------------------------------------------
    print("\n=== Differentiator Proof ===\n")
    header = f"{'':30s}  {'Target A':>20s}  {'Target B':>20s}"
    print(header)
    print("-" * len(header))

    def row(label: str, a, b) -> str:
        return f"{label:30s}  {str(a):>20s}  {str(b):>20s}"

    print(row("KIC ID", result_a["kic_id"], result_b["kic_id"]))
    print(row("Transit depth (ppm)", result_a["depth_ppm"], result_b["depth_ppm"]))
    print(row("Transit depth (%)", result_a["depth_pct"], result_b["depth_pct"]))
    print(row("Odd/even mismatch", result_a["odd_even_mismatch"], result_b["odd_even_mismatch"]))
    print(row("Disposition", result_a["disposition"], result_b["disposition"]))
    print(row("Triggering test", result_a["triggering_test"] or "—", result_b["triggering_test"] or "—"))


if __name__ == "__main__":
    run()
