"""
falsifier.pipeline.classify.__main__
=======================================
UNIT-TEST FIXTURE ONLY — not the real training entry point.

Running ``python -m falsifier.pipeline.classify`` exercises the infrastructure
(GroupShuffleSplit, write_split_indices, XGBoost fit) against a **synthetic**
dataset.  It is used by ``tests/pipeline/contracts/test_classify_pipeline.py``
to verify the training machinery without a network call.

This script MUST NOT be used to generate the committed
``data/splits/classify_split_indices.json``.  That file must come from a real
Kepler DR25 training run.  See ``scripts/train_classifier_dr25.py`` for the
real training entry point and its prerequisites.

If you run this script outside a test context, it will exit 1 with an
explanation rather than writing to the committed split path.

Synthetic data characteristics
-------------------------------
40 VetOutput records, 10 host stars (8 candidate, 2 false-positive EB),
4 TCEs per star, deterministic seed 42.  All seven vetting metrics are
pseudo-random floats — they do not represent any real observation.
"""

from __future__ import annotations

import datetime
import hashlib
import random
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from falsifier.pipeline.contracts.manifest import ArtifactRef, DatasetProvenance, StageManifest
from falsifier.pipeline.contracts.vet import (
    VETTING_TEST_ORDER,
    VetInput,
    VetOutput,
    VettingTestResult,
)
from falsifier.pipeline.contracts.manifest import UnitedArray
from falsifier.pipeline.classify.train import run_training
from falsifier.pipeline.classify.split import DEFAULT_SPLIT_PATH

_DR25_DOI = "10.3847/1538-4365/aab4f9"
_ACCESS_DATE = datetime.date(2024, 1, 1)
_SENTINEL_PATH = _ROOT / "data" / "golden" / "kepler10_q3_long.fits"
_SENTINEL_SHA256 = "0" * 64


def _make_ref(run_id: str) -> ArtifactRef:
    """
    Build a synthetic ``ArtifactRef`` for the golden fixture path.

    Parameters
    ----------
    run_id : str
        Synthetic run identifier (e.g. ``"synth-1-0"``).

    Returns
    -------
    ArtifactRef
        Points to the sentinel golden FITS path with an all-zero SHA-256.
    """
    return ArtifactRef(path=_SENTINEL_PATH, sha256=_SENTINEL_SHA256,
                       stage="vet", pipeline_run_id=run_id)


def _make_manifest(run_id: str, ref: ArtifactRef) -> StageManifest:
    """
    Build a synthetic ``StageManifest`` for unit-test use.

    Parameters
    ----------
    run_id : str
        Synthetic run identifier.
    ref : ArtifactRef
        Artifact reference to embed in the manifest.

    Returns
    -------
    StageManifest
        Manifest labelled ``"vet"`` with a deterministic input hash derived
        from *run_id* and provenance noting synthetic data.
    """
    return StageManifest(
        stage="vet", code_version="0.0.0-synthetic",
        input_hash=hashlib.sha256(run_id.encode()).hexdigest(),
        wall_time_seconds=0.0,
        provenance=[DatasetProvenance(source_doi=_DR25_DOI, access_date=_ACCESS_DATE,
                                      row_count=40,
                                      description="Synthetic fixture — not real DR25 data")],
        artifact=ref,
    )


def _all_pass(rng: random.Random) -> list[VettingTestResult]:
    """
    Generate seven PASS ``VettingTestResult`` objects with random metrics.

    Parameters
    ----------
    rng : random.Random
        Seeded random instance for reproducibility.

    Returns
    -------
    list[VettingTestResult]
        One PASS result per test in ``VETTING_TEST_ORDER``.
    """
    return [VettingTestResult(test_name=n, outcome="PASS",  # type: ignore[arg-type]
                              metric_value=round(rng.uniform(0.0, 1.0), 4),
                              metric_unit="dimensionless",
                              reason=f"{n} passed nominal threshold.")
            for n in VETTING_TEST_ORDER]


def _odd_even_fail(rng: random.Random) -> list[VettingTestResult]:
    """
    Generate seven ``VettingTestResult`` objects where ``odd_even_depth``
    is FAIL and the remaining six are PASS.

    Parameters
    ----------
    rng : random.Random
        Seeded random instance for reproducibility.

    Returns
    -------
    list[VettingTestResult]
        One result per test in ``VETTING_TEST_ORDER``.  The ``odd_even_depth``
        result has an elevated metric value (3.5–8.0) and a FAIL outcome.
    """
    results = []
    for n in VETTING_TEST_ORDER:
        if n == "odd_even_depth":
            results.append(VettingTestResult(
                test_name=n, outcome="FAIL",  # type: ignore[arg-type]
                metric_value=round(rng.uniform(3.5, 8.0), 4),
                metric_unit="dimensionless",
                reason="Odd/even depth ratio exceeds 3-sigma threshold."))
        else:
            results.append(VettingTestResult(
                test_name=n, outcome="PASS",  # type: ignore[arg-type]
                metric_value=round(rng.uniform(0.0, 1.0), 4),
                metric_unit="dimensionless",
                reason=f"{n} passed nominal threshold."))
    return results


def build_synthetic_vet_outputs() -> list[VetOutput]:
    """
    Build 40 synthetic VetOutput records for unit-test use only.

    Returns the list — does NOT write any file.  Callers that need a real
    training set must use ``scripts/train_classifier_dr25.py``.
    """
    rng = random.Random(42)
    records: list[VetOutput] = []
    for star_idx in range(1, 9):        # 8 candidate stars
        host_id = f"KIC-SYNTH-{star_idx:04d}"
        for tce_idx in range(4):
            run_id = f"synth-{star_idx}-{tce_idx}"
            ref = _make_ref(run_id)
            tce_id = f"{host_id}-{tce_idx:02d}"
            results = _all_pass(rng)
            records.append(VetOutput(
                input=VetInput(search_artifact=ref, tce_id=tce_id, pipeline_run_id=run_id),
                tce_id=tce_id, host_star_id=host_id, test_results=results,
                disposition="candidate", triggering_test=None, triggering_reason=None,
                manifest=_make_manifest(run_id, ref), artifact=ref,
            ))
    for star_idx in range(9, 11):       # 2 EB false-positive stars
        host_id = f"KIC-SYNTH-{star_idx:04d}"
        for tce_idx in range(4):
            run_id = f"synth-{star_idx}-{tce_idx}"
            ref = _make_ref(run_id)
            tce_id = f"{host_id}-{tce_idx:02d}"
            results = _odd_even_fail(rng)
            records.append(VetOutput(
                input=VetInput(search_artifact=ref, tce_id=tce_id, pipeline_run_id=run_id),
                tce_id=tce_id, host_star_id=host_id, test_results=results,
                disposition="false_positive", triggering_test="odd_even_depth",
                triggering_reason="Odd/even depth ratio exceeds 3-sigma threshold.",
                manifest=_make_manifest(run_id, ref), artifact=ref,
            ))
    return records


def main() -> None:
    """
    Run a training cycle against synthetic data and write results to a
    TEMPORARY directory — never to the committed split path.

    This entry point is useful for smoke-testing the training infrastructure
    (import chain, GroupShuffleSplit, XGBoost fit, artifact writing) without
    touching committed data.

    Exit 1 if called with ``--commit``, which is intentionally not implemented.
    """
    if "--commit" in sys.argv:
        print(
            "ERROR: --commit is not implemented.\n"
            "The committed data/splits/classify_split_indices.json must be\n"
            "generated from real Kepler DR25 data via:\n"
            "  python scripts/train_classifier_dr25.py\n"
            "See that script for network and data prerequisites.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Synthetic fixture run — results go to a temp directory, not data/splits/")
    vet_outputs = build_synthetic_vet_outputs()
    n_hosts = len({v.host_star_id for v in vet_outputs})
    n_fp = sum(1 for v in vet_outputs if v.disposition == "false_positive")
    n_cand = len(vet_outputs) - n_fp
    print(f"  Records: {len(vet_outputs)} ({n_cand} candidates, {n_fp} false positives)")
    print(f"  Host stars: {n_hosts}")

    with tempfile.TemporaryDirectory() as tmp:
        split_path = Path(tmp) / "classify_split_indices.json"
        result = run_training(vet_outputs, output_dir=Path(tmp), split_path=split_path,
                              draw_diagram=False)
        print(f"  Split written to (temp): {result.split_indices_path}")
        print(f"  Model version: {result.model_version}")
        m = result.eval_metrics
        print(f"  Precision: {m.precision:.3f}  Recall: {m.recall:.3f}")
        print(f"  Brier: {m.brier_score:.4f}  ECE: {m.ece:.4f}")

    print("Done. No committed files were modified.")


if __name__ == "__main__":
    main()
