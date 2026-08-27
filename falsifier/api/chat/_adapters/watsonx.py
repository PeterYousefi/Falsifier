"""
falsifier.api.chat._adapters.watsonx
======================================
IBM watsonx.ai ModelInference adapter.

This is the only module where the vendor SDK (ibm_watsonx_ai) is imported.
No call site outside this file may import or reference ibm_watsonx_ai directly.
Credentials come exclusively from the ``config`` dict (populated from environment
variables by session._detect_watsonx_config — nothing is hardcoded here).
"""

from __future__ import annotations


class WatsonxAdapter:
    """LLMProvider backed by IBM watsonx.ai ModelInference chat."""

    def __init__(self, config: dict) -> None:
        """
        Parameters
        ----------
        config : dict
            Must contain keys: api_key, url, project_id, model_id.
            All values come from environment variables — never hardcoded.
        """
        self._config = config
        self._client = None  # lazy-loaded on first call

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """
        Call watsonx.ai ModelInference.chat and return the raw response dict.

        tools is forwarded as ``[{"type": "function", "function": t} for t in tools]``.
        Raises on HTTP / credential failure; session.py catches and falls back.
        """
        client = self._get_client()
        watsonx_tools = [{"type": "function", "function": t} for t in tools]
        return client.chat(
            messages=messages,
            tools=watsonx_tools,
            tool_choice_option="auto",
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_client(self):
        """Lazy-load the ModelInference client (avoids import at module scope)."""
        if self._client is None:
            from ibm_watsonx_ai import Credentials
            from ibm_watsonx_ai.foundation_models import ModelInference

            credentials = Credentials(
                url=self._config["url"],
                api_key=self._config["api_key"],
            )
            self._client = ModelInference(
                model_id=self._config["model_id"],
                credentials=credentials,
                project_id=self._config["project_id"],
            )
        return self._client
