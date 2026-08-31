#!/usr/bin/env python3
"""
scripts/judge_memory_moment.py
================================
The Judge Memory Moment: demonstrates the pipeline catching a known eclipsing
binary (KIC 6965293) that a shape-only classifier would pass.

Runs KIC 6965293 through the real falsifier pipeline (detrend → search → vet)
and prints the transit depth (the dip a shape-only classifier sees) and the
vetting disposition with the triggering test that kills it.

Results are written to data/artifacts/judge_memory_moment.json so that
verify_readme.py can regenerate the CLAIM blocks sourced from this script.

Usage
-----
    python3 scripts/judge_memory_moment.py

Policy compliance
-----------------
AGENTS.md Rule 1: all numeric claims are read from the pipeline output artifact,
not hardcoded.  Rule 2: physical quantities carry units inside pipeline
contracts (UnitedArray).  Rule 3: manifest entry committed in provenance sidecar.

No network access is required — uses the committed golden FITS file.
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
GOLDEN_FITS = REPO_ROOT / "data" / "golden" / "kic6965293_q3_long.fits"
GOLDEN_PROVENANCE = REPO_ROOT / "data" / "golden" / "kic6965293_q3_long.provenance.json"
OUTPUT_PATH = REPO_ROOT / "data" / "artifacts" / "judge_memory_moment.json"

# Pipeline parameters — configuration constants, not scientific claims.
DETREND_WINDOW_DAYS = 2.0
BREAK_TOLERANCE_DAYS = 0.5
TLS_PERIOD_MIN_DAYS = 1.0
TLS_PERIOD_MAX_DAYS = 10.0


def run() -> None:
    if not GOLDEN_FITS.exists():
        print(
            f"ERROR: Golden FITS not found: {GOLDEN_FITS}\n"
            "Run scripts/fetch_golden.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    # -----------------------------------------------------------------
    # Load golden FITS
    # -----------------------------------------------------------------
    with fits.open(GOLDEN_FITS) as hdul:
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

    # -----------------------------------------------------------------
    # Build pipeline objects
    # -----------------------------------------------------------------
    sys.path.insert(0, str(REPO_ROOT))
    from falsifier.pipeline.contracts import (
        ArtifactRef, DatasetProvenance, DetrendInput, IngestInput,
        IngestOutput, LightCurveSegment, SearchInput, StageManifest,
        UnitedArray, VetInput,
    )
    from falsifier.pipeline.stages.detrend import run_detrend
    from falsifier.pipeline.stages.search import run_search
    from falsifier.pipeline.stages.vet import run_vet

    run_id = "judge-memory-moment"
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
        path=GOLDEN_FITS,
        sha256="0" * 64,
        stage="ingest",
        pipeline_run_id=run_id,
    )
    provenance = DatasetProvenance(
        source_doi="10.1088/0004-6256/141/3/83",
        access_date=datetime.date(2026, 8, 26),
        row_count=int(len(time)),
        description="KIC 6965293 Q3 long-cadence — judge memory moment fixture",
    )
    ingest_out = IngestOutput(
        input=IngestInput(
            tic_id="KIC 6965293",
            sectors=[3],
            cadence="long",
            pipeline_run_id=run_id,
        ),
        segments=[seg],
        host_star_id="KIC 6965293",
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
        window_length=UnitedArray(values=[DETREND_WINDOW_DAYS], unit="day"),
        break_tolerance=UnitedArray(values=[BREAK_TOLERANCE_DAYS], unit="day"),
        pipeline_run_id=run_id,
    )
    search_input = SearchInput(
        detrend_artifact=dummy_ref,
        period_min=UnitedArray(values=[TLS_PERIOD_MIN_DAYS], unit="day"),
        period_max=UnitedArray(values=[TLS_PERIOD_MAX_DAYS], unit="day"),
        snr_threshold=7.0,
        pipeline_run_id=run_id,
    )

    # -----------------------------------------------------------------
    # Run pipeline
    # -----------------------------------------------------------------
    print("Running detrend...", flush=True)
    detrend_out = run_detrend(detrend_input, ingest_output=ingest_out)
    print("Running search...", flush=True)
    search_out = run_search(search_input, detrend_output=detrend_out)

    if not search_out.tces:
        print("ERROR: No TCEs found in KIC 6965293.", file=sys.stderr)
        sys.exit(1)

    best_tce = max(search_out.tces, key=lambda t: t.sde)
    vet_input = VetInput(
        search_artifact=dummy_ref,
        tce_id=best_tce.tce_id,
        pipeline_run_id=run_id,
    )
    print("Running vet...", flush=True)
    vet_out = run_vet(vet_input, search_output=search_out, tce=best_tce)

    depth_ppm = round(best_tce.depth.values[0])
    depth_pct = round(best_tce.depth.values[0] / 10_000, 2)  # ppm → percent
    odd_even_mismatch = round(best_tce.odd_even_mismatch, 2)
    disposition = vet_out.disposition
    triggering_test = vet_out.triggering_test

    # -----------------------------------------------------------------
    # Write artifact
    # -----------------------------------------------------------------
    artifact = {
        "schema_version": "1",
        "produced_at": datetime.datetime.utcnow().isoformat() + "Z",
        "target": "KIC 6965293",
        "source_doi": "10.1088/0004-6256/141/3/83",
        "access_date": "2026-08-26",
        "depth_ppm": depth_ppm,
        "depth_pct": depth_pct,
        "odd_even_mismatch": odd_even_mismatch,
        "disposition": disposition,
        "triggering_test": triggering_test,
        "triggering_reason": vet_out.triggering_reason,
        "notes": (
            "Produced by scripts/judge_memory_moment.py from the committed "
            "KIC 6965293 Q3 golden FITS. Depth and mismatch are pipeline-measured "
            "values from the best TLS TCE."
        ),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
    print(f"Artifact written: {OUTPUT_PATH}")

    # -----------------------------------------------------------------
    # Human-readable summary
    # -----------------------------------------------------------------
    print(f"\n=== Judge Memory Moment: KIC 6965293 ===")
    print(f"Transit depth:       {depth_ppm} ppm ({depth_pct}%)")
    print(f"Odd/even mismatch:   {odd_even_mismatch}")
    print(f"Disposition:         {disposition}")
    print(f"Triggering test:     {triggering_test}")
    print(f"Triggering reason:   {vet_out.triggering_reason}")


if __name__ == "__main__":
    run()
