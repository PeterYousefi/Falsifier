"""
falsifier.api.routes.provenance
================================
GET /provenance

Returns a ``ProvenanceReport`` describing:

  1. Live data versions — read from ``data/golden/*.provenance.json`` and
     ``data/golden/MANIFEST.json`` at request time.  No numbers are hardcoded
     in this endpoint; all values come from committed artifacts.

  2. Module status — which pipeline modules are wired vs aspirational.
     This mirrors the README §Dead Code table and is maintained here in code
     so it stays in sync with the running application rather than a document.

  3. Non-claims — verbatim statements from AGENTS.md that bound what the
     pipeline cannot assert.

Policy compliance
-----------------
AGENTS.md Rule 1: no hardcoded scientific values in API code.
Every ``data_versions`` entry is read from a committed provenance sidecar.
"""

from __future__ import annotations

import json
from pathlib import Path

import os

import falsifier
from fastapi import APIRouter
from ..models import DataVersionEntry, ModuleStatus, ProvenanceReport
from ..chat.guardian import get_guardian_backend

router = APIRouter(prefix="/provenance", tags=["provenance"])

REPO_ROOT = Path(__file__).parent.parent.parent.parent  # …/falsifier/api/routes/ → repo root

# ---------------------------------------------------------------------------
# Module wired/aspirational table
# Mirrors README §Dead / Experimental Code.
# Update this list whenever a module is wired to a live code path.
# ---------------------------------------------------------------------------

_MODULE_STATUS: list[ModuleStatus] = [
    ModuleStatus(
        module="falsifier.pipeline.stages.ingest",
        status="wired",
        note="run_ingest is called by the job queue for every detection run.",
    ),
    ModuleStatus(
        module="falsifier.pipeline.stages.detrend",
        status="aspirational",
        note="Stage body not yet implemented; queue uses a normalisation stub.",
    ),
    ModuleStatus(
        module="falsifier.pipeline.stages.search",
        status="aspirational",
        note="Stage body not yet implemented; queue uses an empty-TCE stub.",
    ),
    ModuleStatus(
        module="falsifier.pipeline.stages.vet",
        status="aspirational",
        note="Stage body not yet implemented; queue uses an all-PASS stub.",
    ),
    ModuleStatus(
        module="falsifier.pipeline.stages.classify",
        status="wired",
        note=(
            "run_classify is implemented; used when xgboost and a trained model "
            "artifact are present.  Falls back to a stub when either is absent."
        ),
    ),
    ModuleStatus(
        module="falsifier.pipeline.contracts.retrieve",
        status="aspirational",
        note="Contract written; run_retrieve not yet implemented.",
    ),
    ModuleStatus(
        module="falsifier.pipeline.contracts.disequilibrium",
        status="aspirational",
        note=(
            "Contract written; run_disequilibrium not yet implemented.  "
            "This stage is not a biosignature detector."
        ),
    ),
]

_NON_CLAIMS: list[str] = [
    "This project is not a biosignature detector.",
    "No exoplanet biosignature has ever been confirmed.",
    "The classifier probability is a ranking score only — not a verdict.",
    "Disposition is determined exclusively by the vet stage, not by the classifier.",
    "No detection rate, false-positive rate, or model score is reported here "
    "unless it is produced by scripts/reproduce.sh.",
    "The output of this pipeline is a triage list, not a detection claim.",
]


@router.get("", response_model=ProvenanceReport)
async def get_provenance() -> ProvenanceReport:
    """
    Report live data versions, module wiring status, explicit non-claims,
    and runtime backend self-report.

    All ``data_versions`` entries are read from committed provenance sidecars
    at request time.  No scientific values are hardcoded here.
    """
    data_versions = _collect_data_versions()
    golden_count = _count_golden_manifest_entries()

    return ProvenanceReport(
        falsifier_version=falsifier.__version__,
        data_versions=data_versions,
        modules=_MODULE_STATUS,
        non_claims=_NON_CLAIMS,
        golden_manifest_entry_count=golden_count,
        # Runtime self-report
        guardian_backend=get_guardian_backend(),
        chat_backend=_detect_chat_backend(),
        artifacts_present=_check_artifacts(),
        classifier_trained=False,
        classifier_blocked_reason=(
            "train/serve feature skew: the classifier reads vet-stage metric_value "
            "fields at inference but no DR25 catalogue column maps to those quantities. "
            "Training is a deliberate refusal. "
            "See docs/SKIPPED_TESTS.md and scripts/train_classifier_dr25.py."
        ),
    )


def _collect_data_versions() -> list[DataVersionEntry]:
    """
    Walk data/golden/*.provenance.json and return one entry per sidecar.
    Returns an empty list if the directory does not exist (pre-fetch state).
    """
    golden_dir = REPO_ROOT / "data" / "golden"
    entries: list[DataVersionEntry] = []

    if not golden_dir.exists():
        return entries

    for prov_path in sorted(golden_dir.glob("*.provenance.json")):
        try:
            with open(prov_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        doi = data.get("source_doi") or data.get("reference_doi", "")
        access_date = data.get("access_date", "")
        row_count = data.get("row_count")
        description = data.get("description", prov_path.stem)

        entries.append(DataVersionEntry(
            name=prov_path.stem,
            source_doi=doi,
            access_date=access_date,
            row_count=row_count if isinstance(row_count, int) else None,
            description=description,
        ))

    return entries


def _detect_chat_backend() -> str:
    """
    Return the chat backend label based on env var presence.

    "watsonx:<model_id>" if WATSONX_APIKEY is set (key present means a call
    could succeed; we cannot verify a prior success without a live call).
    "templated_offline" if WATSONX_APIKEY is absent.
    """
    api_key = os.environ.get("WATSONX_APIKEY", "").strip()
    if api_key:
        model_id = os.environ.get(
            "WATSONX_MODEL_ID", "ibm/granite-3-3-8b-instruct"
        ).strip()
        return f"watsonx:{model_id}"
    return "templated_offline"


def _check_artifacts() -> dict[str, bool]:
    """
    Check whether the two primary output artifacts exist on the filesystem.

    Both are currently absent; returns False for each rather than omitting
    the key.
    """
    artifacts_dir = REPO_ROOT / "data" / "artifacts"
    return {
        "injection_recovery": (artifacts_dir / "injection_recovery.json").exists(),
        "adversarial_selftest": (artifacts_dir / "adversarial_selftest.json").exists(),
    }


def _count_golden_manifest_entries() -> int:
    """Count entries in data/golden/MANIFEST.json. Returns 0 if absent."""
    manifest_path = REPO_ROOT / "data" / "golden" / "MANIFEST.json"
    if not manifest_path.exists():
        return 0
    try:
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
        return len(data.get("golden_set", []))
    except (json.JSONDecodeError, OSError):
        return 0
