"""
falsifier.api.chat.provider
============================
Provider-neutral LLM interface.

Design
------
LLMProvider is a runtime Protocol — any object that has a ``chat`` method
matching the signature below satisfies it.  No OpenAI or vendor name appears
outside the concrete adapter modules.

Adapters registered in this module:
  WatsonxAdapter    — IBM watsonx.ai ModelInference (default when credentials present)
  FallbackAdapter   — Deterministic, reads only from committed pipeline artifacts;
                      selected when no credential is set so the demo works key-free.
                      Refuses (returns not_available=True) when the artifact does not
                      contain the answer rather than guessing.

AGENTS.md enforcement
---------------------
Rule 1: no hardcoded scientific values.
All values returned by adapters must come from tool call results or committed
pipeline artifact text — never from constants in this file.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """
    Minimal interface every LLM adapter must satisfy.

    Parameters
    ----------
    messages : list[dict]
        Conversation in the standard ``[{"role": ..., "content": ...}, ...]`` form.
    tools : list[dict]
        Tool schemas in OpenAI-function-calling format (same as TOOL_SCHEMAS).

    Returns
    -------
    dict
        A response dict with a ``choices[0].message`` structure.
        Text-only responses use ``finish_reason="stop"`` and no ``tool_calls``.
        Tool-call responses use ``finish_reason="tool_calls"`` with the list.
    """

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        ...


# ---------------------------------------------------------------------------
# Module-private helpers (called by session.py)
# ---------------------------------------------------------------------------

def get_provider(watsonx_config: dict | None) -> LLMProvider:
    """
    Return the appropriate LLMProvider for the current environment.

    If ``watsonx_config`` is not None (i.e. WATSONX_APIKEY is set and valid),
    returns a WatsonxAdapter backed by IBM watsonx.ai ModelInference.

    If ``watsonx_config`` is None, returns FallbackAdapter — the deterministic
    offline adapter that reads only from committed pipeline artifacts.  This is
    what runs key-free so the demo works without any credentials.
    """
    if watsonx_config is not None:
        from ._adapters.watsonx import WatsonxAdapter
        return WatsonxAdapter(watsonx_config)
    from ._adapters.fallback import FallbackAdapter
    return FallbackAdapter()
