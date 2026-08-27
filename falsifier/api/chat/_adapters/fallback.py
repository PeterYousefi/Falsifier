"""
falsifier.api.chat._adapters.fallback
=======================================
Deterministic, non-LLM fallback adapter.

Selected when no credential (WATSONX_APIKEY) is present, so the demo works
key-free.  All responses are assembled from committed pipeline artifacts only.
When the artifact does not contain the answer the adapter refuses rather than
guesses ("not_available" in the response).

This adapter never makes a network call and never invents a number.
AGENTS.md Rule 1 is enforced structurally: there are no numeric literals here.
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_EXPLANATIONS_PATH = (
    _REPO_ROOT / "data" / "artifacts" / "explanations" / "stage_explanations.json"
)


class FallbackAdapter:
    """
    Deterministic offline adapter — reads only from committed pipeline artifacts.

    Returns a ``choices[0].message.content`` string assembled from
    stage_explanations.json.  Returns a ``not_available`` marker when the
    artifact is absent rather than inventing an answer.
    """

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """
        Produce a deterministic text response from committed artifact text.

        Does not call any tool or model.  The last user message is used only
        to decide whether to show an "offline mode" header; the body comes
        exclusively from the committed artifact.
        """
        explanation_text = self._load_explanation()
        content = (
            "**Offline mode** — no watsonx.ai API key configured.  "
            "Showing pipeline artifact summary only.\n\n"
            + explanation_text
        )
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": None,
                },
            }]
        }

    def _load_explanation(self) -> str:
        """
        Load the non_claims list from stage_explanations.json.

        Returns a "not_available" string if the artifact is absent rather than
        inventing content.
        """
        if not _EXPLANATIONS_PATH.exists():
            return (
                "[not_available: stage_explanations.json not found.  "
                "Run the pipeline first to generate committed artifacts.]"
            )
        try:
            with open(_EXPLANATIONS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            non_claims = data.get("non_claims", [])
            if non_claims:
                return "**Non-claims (immutable):**\n" + "\n".join(
                    f"  - {c}" for c in non_claims
                )
            return "[not_available: non_claims list is empty in stage_explanations.json]"
        except Exception:  # noqa: BLE001
            return (
                "[not_available: could not read stage_explanations.json.  "
                "The artifact may be malformed.]"
            )
