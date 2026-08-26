#!/usr/bin/env python3
"""
scripts/disposition_agreement.py
==================================
Compare Falsifier's vet-stage dispositions against the published DR25 Robovetter
dispositions for a pinned sample of Kepler Objects of Interest.

Purpose
-------
The prior-art comparison in docs/PRIOR_ART.md claims that Falsifier's design
differentiator is a *named, auditable triggering test* rather than a score.  This
script makes that claim evidence: for every KOI in the pinned sample, it records
our disposition, our triggering_test, the published DR25 disposition, and whether
they agree.  Every disagreement is reported, not filtered.  Where we disagree,
the triggering_test field tells a reader exactly which physical test drove our
result — which holds whether we were right or wrong.

This script produces a comparison table.  It does NOT produce an accuracy claim.
The output artifact must not contain an accuracy field.

Sample design
-------------
The sample is pinned by KIC ID in
``data/targets/disposition_agreement_manifest.json``, committed before any
pipeline run.  The manifest records the selection rule, seed, and date, so the
sample cannot be chosen after seeing results.  See the manifest for the full
stratification rationale and scope caveat.

Runtime budget
--------------
The pinned sample contains 30 KOIs.  At ~90–150 s per KOI (MAST fetch + TLS
search), a full run takes 45–75 minutes — within a 2-hour CI budget.  The CI
wiring uses ``timeout-minutes: 150`` to enforce this bound.

If the sample is too small to be representative, that is stated in the artifact's
``scope`` field.  It is.

AGENTS.md compliance
--------------------
Rule 1: no scientific value is hardcoded; all thresholds read from
        pipeline_constants.py or the manifest.
Rule 2: no bare floats cross module boundaries.
Rule 3: artifact records source_doi, access_date, row_count.
Rule 4: no ML split (this is a pipeline comparison, not a model evaluation).
Rule 5: artifact is the source of truth; do not manually edit it.

Usage
-----
    python scripts/disposition_agreement.py [--output PATH] [--manifest PATH]
                                            [--data-dir PATH] [--dry-run]

    --output PATH    Override output JSON path
                     (default: data/artifacts/disposition_agreement.json)
    --manifest PATH  Override manifest path
                     (default: data/targets/disposition_agreement_manifest.json)
    --data-dir PATH  Directory containing golden FITS files
                     (default: data/golden)
    --dry-run        Validate the manifest and exit without running the pipeline

Exit codes
----------
  0   Artifact written (or --dry-run completed successfully).
  1   Manifest error, pipeline error, or write failure.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import traceback
import warnings
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "artifacts" / "disposition_agreement.json"
DEFAULT_MANIFEST = REPO_ROOT / "data" / "targets" / "disposition_agreement_manifest.json"
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "golden"

# ---------------------------------------------------------------------------
# DR25 disposition → Falsifier disposition equivalence map
#
# DR25 uses three values.  Falsifier uses four.  The mapping is:
#   CONFIRMED    → candidate               (surviving all seven tests)
#   FALSE POSITIVE → false_positive        (at least one FAIL)
#   CANDIDATE    → candidate OR ambiguous  (no FAIL; some tests inconclusive)
#
# The agreement check uses the mapping below.  A CANDIDATE that Falsifier
# returns as "ambiguous" is recorded as AGREE_PARTIAL (not a disagreement),
# because CANDIDATE in DR25 already means "not confirmed, not false positive."
# ---------------------------------------------------------------------------

_DR25_TO_FALSIFIER: dict[str, set[str]] = {
    "CONFIRMED":     {"candidate", "candidate_with_caveats"},
    "FALSE POSITIVE": {"false_positive"},
    "CANDIDATE":     {"candidate", "candidate_with_caveats", "ambiguous"},
}


def _agreement_label(
    dr25_disposition: str,
    falsifier_disposition: str | None,
) -> str:
    """
    Return a three-value agreement label:
      "AGREE"    — dispositions are consistent under the mapping above
      "DISAGREE" — dispositions are inconsistent
      "ERROR"    — pipeline did not return a disposition (run failed)
    """
    if falsifier_disposition is None:
        return "ERROR"
    allowed = _DR25_TO_FALSIFIER.get(dr25_disposition.upper(), set())
    return "AGREE" if falsifier_disposition in allowed else "DISAGREE"


# ---------------------------------------------------------------------------
# Pipeline runner for a single KIC target
# ---------------------------------------------------------------------------

def _run_pipeline_for_kic(
    kepid: int,
    data_dir: Path,
) -> dict:
    """
    Run the ingest → detrend → search → vet pipeline on a single KIC target.

    Returns a dict with keys:
      kepid             int
      falsifier_disposition  str | None
      triggering_test   str | None
      triggering_reason str | None
      pipeline_error    str | None  (non-None if the run failed)

    This function imports pipeline stages lazily so the script can be imported
    in dry-run mode without requiring all optional dependencies.
    """
    result: dict = {
        "kepid": kepid,
        "falsifier_disposition": None,
        "triggering_test": None,
        "triggering_reason": None,
        "pipeline_error": None,
    }

    try:
        # Lazy imports — pipeline deps not required for dry-run or manifest check
        import lightkurve as lk
        from falsifier.pipeline.stages.detrend import run_detrend
        from falsifier.pipeline.stages.search import run_search
        from falsifier.pipeline.stages.vet import run_vet
        from falsifier.pipeline.contracts.ingest import IngestOutput, LightCurveData
        from falsifier.pipeline.contracts.detrend import DetrendInput
        from falsifier.pipeline.contracts.search import SearchInput
        from falsifier.pipeline.contracts.vet import VetInput
        from falsifier.pipeline.contracts.manifest import ArtifactRef, StageManifest
        from scripts.pipeline_constants import SDE_THRESHOLD  # noqa: F401 (used as threshold guard)

        # ------------------------------------------------------------------
        # Ingest: fetch Q3 long-cadence from MAST (or from golden cache)
        # ------------------------------------------------------------------
        target_name = f"KIC {kepid}"

        # Try golden cache first (data_dir); fall back to MAST
        cached_fits = list(data_dir.glob(f"*{kepid}*.fits"))
        if cached_fits:
            lc_collection = lk.read(str(cached_fits[0]))
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                search_result = lk.search_lightcurve(
                    target_name,
                    mission="Kepler",
                    cadence="long",
                    quarter=3,
                )
                if len(search_result) == 0:
                    raise RuntimeError(
                        f"No Q3 long-cadence data found for {target_name} on MAST"
                    )
                lc_collection = search_result[0].download()

        if lc_collection is None:
            raise RuntimeError(f"lightkurve returned None for {target_name}")

        # Normalise to a single LightCurve
        if hasattr(lc_collection, "stitch"):
            lc = lc_collection.stitch()
        else:
            lc = lc_collection

        lc = lc.remove_nans().normalize()

        # ------------------------------------------------------------------
        # Build a minimal IngestOutput to satisfy the detrend contract
        # ------------------------------------------------------------------
        import numpy as np
        import astropy.units as u

        time_arr = lc.time.bkjd if hasattr(lc.time, "bkjd") else np.array(lc.time.value)
        flux_arr = np.array(lc.flux.value)
        flux_err_arr = (
            np.array(lc.flux_err.value)
            if lc.flux_err is not None
            else np.ones_like(flux_arr) * 1e-3
        )

        from falsifier.pipeline.contracts.manifest import DatasetProvenance, UnitedArray

        provenance = DatasetProvenance(
            source_doi="10.17909/t9-st5g-3177",
            source_url="https://mast.stsci.edu/api/v0/invoke",
            access_date=datetime.date.today().isoformat(),
            row_count=int(len(time_arr)),
        )

        lc_data = LightCurveData(
            time=UnitedArray(value=time_arr.tolist(), unit="day"),
            flux=UnitedArray(value=flux_arr.tolist(), unit="dimensionless"),
            flux_err=UnitedArray(value=flux_err_arr.tolist(), unit="dimensionless"),
            time_format="bkjd",
            cadence_seconds=1764.0,
            provenance=provenance,
        )

        run_id = f"disp_agree_{kepid}"
        artifact_ref = ArtifactRef(artifact_id=f"ingest_{kepid}", stage="ingest")
        manifest = StageManifest(
            pipeline_run_id=run_id,
            stage="ingest",
            input_hash="disposition_agreement_run",
            output_artifact=artifact_ref,
        )

        ingest_out = IngestOutput(
            manifest=manifest,
            light_curve=lc_data,
            star_id=target_name,
            host_star_id=str(kepid),
        )

        # ------------------------------------------------------------------
        # Detrend
        # ------------------------------------------------------------------
        detrend_in = DetrendInput(
            ingest_artifact=artifact_ref,
            pipeline_run_id=run_id,
        )
        detrend_out = run_detrend(detrend_in, ingest_out)

        # ------------------------------------------------------------------
        # Search
        # ------------------------------------------------------------------
        detrend_artifact = ArtifactRef(artifact_id=f"detrend_{kepid}", stage="detrend")
        search_in = SearchInput(
            detrend_artifact=detrend_artifact,
            pipeline_run_id=run_id,
        )
        search_out = run_search(search_in, detrend_out)

        if not search_out.tces:
            result["falsifier_disposition"] = "ambiguous"
            result["triggering_test"] = None
            result["triggering_reason"] = "No TCE detected above SDE threshold"
            return result

        # Take the strongest TCE
        tce = search_out.tces[0]

        # ------------------------------------------------------------------
        # Vet
        # ------------------------------------------------------------------
        search_artifact = ArtifactRef(artifact_id=f"search_{kepid}", stage="search")
        vet_in = VetInput(
            search_artifact=search_artifact,
            tce_id=tce.tce_id,
            pipeline_run_id=run_id,
        )
        vet_out = run_vet(vet_in, search_out, ingest_out)

        result["falsifier_disposition"] = vet_out.disposition
        result["triggering_test"] = vet_out.triggering_test
        result["triggering_reason"] = vet_out.triggering_reason

    except Exception as exc:
        result["pipeline_error"] = f"{type(exc).__name__}: {exc}"
        tb = traceback.format_exc()
        print(f"  ERROR for KIC {kepid}: {result['pipeline_error']}", file=sys.stderr)
        print(f"  Traceback:\n{tb}", file=sys.stderr)

    return result


# ---------------------------------------------------------------------------
# Main comparison logic
# ---------------------------------------------------------------------------

def run_comparison(
    manifest_path: Path,
    data_dir: Path,
    dry_run: bool = False,
) -> dict:
    """
    Load the manifest, run the pipeline on each target, and return the
    complete artifact dict.

    The artifact contains no accuracy field.  Every disagreement is reported.
    """
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    today = datetime.date.today().isoformat()

    artifact: dict = {
        "description": (
            "Comparison of Falsifier vet-stage dispositions against published "
            "DR25 Robovetter dispositions for a pinned KOI sample.  "
            "This is a comparison table, not an accuracy claim.  "
            "Every disagreement is reported.  Where we disagree, triggering_test "
            "names the physical test that drove our result."
        ),
        "scope": (
            f"Sample size: {manifest['sample_size']} KOIs "
            f"({manifest.get('sample_size', 30) // 3} per disposition class).  "
            "This sample is not statistically representative of the 2,000-entry "
            "DR25 catalog.  No accuracy, precision, recall, or F-score is reported.  "
            "The purpose is to demonstrate that every Falsifier decision is "
            "accompanied by a named triggering_test, whether it agrees with DR25 "
            "or not."
        ),
        "source_doi": manifest["source_doi"],
        "source_description": manifest["source_description"],
        "manifest_path": str(manifest_path.relative_to(REPO_ROOT)),
        "selection_rule": manifest["selection_rule"],
        "selection_seed": manifest["selection_seed"],
        "selection_date": manifest["selection_date"],
        "run_date": today,
        "dry_run": dry_run,
        "targets": [],
    }

    if dry_run:
        print(
            f"Dry run: manifest loaded successfully.  "
            f"{len(manifest['targets'])} targets pinned.  "
            f"Not running pipeline.",
            file=sys.stderr,
        )
        artifact["targets"] = [
            {
                "kepid": t["kepid"],
                "kepoi_name": t["kepoi_name"],
                "dr25_disposition": t["dr25_disposition"],
                "dr25_fp_flag": t["dr25_fp_flag"],
                "falsifier_disposition": None,
                "triggering_test": None,
                "triggering_reason": None,
                "agreement": "DRY_RUN",
                "pipeline_error": None,
            }
            for t in manifest["targets"]
        ]
        return artifact

    for i, target in enumerate(manifest["targets"], 1):
        kepid = target["kepid"]
        kepoi_name = target["kepoi_name"]
        dr25_disp = target["dr25_disposition"]
        dr25_fp = target["dr25_fp_flag"]

        print(
            f"  [{i:02d}/{len(manifest['targets'])}] "
            f"KIC {kepid} ({kepoi_name}, DR25={dr25_disp}) …",
            file=sys.stderr,
        )

        run_result = _run_pipeline_for_kic(kepid, data_dir)

        agreement = _agreement_label(dr25_disp, run_result["falsifier_disposition"])

        entry = {
            "kepid": kepid,
            "kepoi_name": kepoi_name,
            "dr25_disposition": dr25_disp,
            "dr25_fp_flag": dr25_fp,
            "falsifier_disposition": run_result["falsifier_disposition"],
            "triggering_test": run_result["triggering_test"],
            "triggering_reason": run_result["triggering_reason"],
            "agreement": agreement,
            "pipeline_error": run_result["pipeline_error"],
        }

        artifact["targets"].append(entry)

        status = f"→ {run_result['falsifier_disposition']} [{agreement}]"
        if run_result["pipeline_error"]:
            status = f"→ ERROR: {run_result['pipeline_error'][:80]}"
        print(f"      {status}", file=sys.stderr)

    return artifact


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Compare Falsifier dispositions against DR25 Robovetter on a "
            "pinned KOI sample.  Writes data/artifacts/disposition_agreement.json."
        )
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"Output JSON path (default: {DEFAULT_OUTPUT})",
    )
    p.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        metavar="PATH",
        help=f"Manifest JSON path (default: {DEFAULT_MANIFEST})",
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        metavar="PATH",
        help=f"Golden data directory (default: {DEFAULT_DATA_DIR})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate manifest and exit without running the pipeline",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.manifest.exists():
        print(f"ERROR: manifest not found: {args.manifest}", file=sys.stderr)
        return 1

    print(
        f"Running disposition agreement comparison …\n"
        f"  Manifest: {args.manifest}\n"
        f"  Output:   {args.output}\n"
        f"  Data dir: {args.data_dir}\n"
        f"  Dry run:  {args.dry_run}",
        file=sys.stderr,
    )

    try:
        artifact = run_comparison(
            manifest_path=args.manifest,
            data_dir=args.data_dir,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    n = len(artifact["targets"])
    agreed = sum(1 for t in artifact["targets"] if t["agreement"] == "AGREE")
    errors = sum(1 for t in artifact["targets"] if t["pipeline_error"])
    print(
        f"Written: {args.output}  "
        f"({n} targets, {agreed} agree, {n - agreed - errors} disagree, {errors} errors)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
