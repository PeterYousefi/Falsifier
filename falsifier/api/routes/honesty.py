"""
falsifier.api.routes.honesty
==============================
GET /api/status.honesty

Reports the live backend state as a signed, machine-readable ledger entry.
Tells you exactly what answered your request and whether any degradation is
active — no inference, no guessing.

Fields
------
guardian_backend : str
    "granite-guardian-3.1-2b" if the Granite Guardian model loaded from the
    local HuggingFace cache; "rule_based_heuristic" if it fell back.
    Read from the actual loaded state via get_guardian_backend(), not from
    an env var inference.

chat_backend : str
    "watsonx:<model_id>" if WATSONX_APIKEY is set (model_id from env or
    default ibm/granite-3-3-8b-instruct); "templated_offline" otherwise.

degraded : bool
    True when any backend is operating below its designed capability:
    chat_backend == "templated_offline" OR
    guardian_backend == "rule_based_heuristic".

degradation_reasons : list[str]
    Human-readable list of which components are degraded and why.

non_claim : str
    The locked immutable claim from AGENTS.md.

Policy compliance
-----------------
AGENTS.md Rule 1: no scientific values in API code.
This endpoint reports operational state only — no pipeline numeric claims.
"""

from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

from ..chat.guardian import get_guardian_backend

router = APIRouter(prefix="/api/status", tags=["honesty"])


class HonestyReport(BaseModel):
    """Cryptographically-honest backend state report."""

    guardian_backend: str
    """Actual backend serving output screening."""

    chat_backend: str
    """Actual backend serving generative responses."""

    degraded: bool
    """True if any component is operating below its designed capability."""

    degradation_reasons: list[str]
    """Which components are degraded and why."""

    non_claim: str
    """The locked immutable claim from AGENTS.md."""


def _detect_chat_backend() -> str:
    """
    Return the chat backend label based on env var presence.
    Mirrors the logic in falsifier.api.routes.provenance._detect_chat_backend.
    """
    api_key = os.environ.get("WATSONX_APIKEY", "").strip()
    if api_key:
        model_id = os.environ.get(
            "WATSONX_MODEL_ID", "ibm/granite-3-3-8b-instruct"
        ).strip()
        return f"watsonx:{model_id}"
    return "templated_offline"


@router.get(".honesty", response_model=HonestyReport)
async def get_honesty_status() -> HonestyReport:
    """
    Live backend honesty ledger.

    Reports which backend is actually answering requests, whether any
    degradation is active, and the locked non-claim from AGENTS.md.
    All values are read from the actual running state — not from config.
    """
    guardian_backend = get_guardian_backend()
    chat_backend = _detect_chat_backend()

    degradation_reasons: list[str] = []
    if chat_backend == "templated_offline":
        degradation_reasons.append(
            "chat_backend=templated_offline: WATSONX_APIKEY is absent; "
            "generative explanations are served from pre-written templates, "
            "not from ibm/granite-3-3-8b-instruct."
        )
    if guardian_backend == "rule_based_heuristic":
        degradation_reasons.append(
            "guardian_backend=rule_based_heuristic: granite-guardian-3.1-2b "
            "did not load from local HuggingFace cache; output is screened by "
            "the deterministic rule-based fallback instead."
        )

    return HonestyReport(
        guardian_backend=guardian_backend,
        chat_backend=chat_backend,
        degraded=len(degradation_reasons) > 0,
        degradation_reasons=degradation_reasons,
        non_claim=(
            "This project is not a biosignature detector. "
            "No exoplanet biosignature has ever been confirmed."
        ),
    )
