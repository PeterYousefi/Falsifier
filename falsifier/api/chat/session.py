"""
falsifier.api.chat.session
===========================
Conversation state management and tool-call loop.

IBM watsonx.ai only
-------------------
This module uses IBM watsonx.ai (Granite) as the sole inference backend.
No OpenAI, Anthropic, or other provider is supported.

Configuration (all from environment — nothing hardcoded):
  WATSONX_API_KEY    — IBM Cloud IAM API key
  WATSONX_PROJECT_ID — watsonx.ai project ID
  WATSONX_URL        — watsonx.ai instance URL
                       (default: https://us-south.ml.cloud.ibm.com)
  WATSONX_MODEL_ID   — model to use
                       (default: ibm/granite-3-3-8b-instruct)

Authentication
--------------
The IBM Cloud IAM API key is exchanged for a bearer token via:
  POST https://iam.cloud.ibm.com/identity/token
The token is cached in-process and refreshed automatically before expiry
(5 minutes before the ``expiration`` timestamp returned by IAM).

Tool calling
------------
All 8 tool schemas are sent in OpenAI-compatible format to the watsonx
/ml/v1/text/chat endpoint, which granite-3-3-8b-instruct supports natively.
Tool results are injected as role="tool" messages, matching the format
verified to round-trip through the model.

Model: ibm/granite-3-3-8b-instruct
  - Supports tool calling (function calling) natively via /ml/v1/text/chat
  - Not all Granite instruct variants support tool calling; this one does.
  - Configurable via WATSONX_MODEL_ID for future upgrades.

Degradation
-----------
If no WATSONX_API_KEY (or no WATSONX_PROJECT_ID) is set, the session runs in
"offline" mode: it calls the requested tools directly and assembles a
templated answer from stage_explanations.json without contacting any model.
The endpoint never raises on a missing key.

Guardian
--------
Guardian (guardian.py) runs locally with local_files_only=True.
It is never routed through watsonx and makes no network call.
It is called on every response including offline mode.

AGENTS.md enforcement
---------------------
Rule 1: numbers are injected into responses only from tool call results.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .guardian import GuardianVerdict, screen
from .system_prompt import build_system_prompt
from .tools import TOOL_REGISTRY, TOOL_SCHEMAS

import re as _re

REPO_ROOT = Path(__file__).parent.parent.parent.parent
_EXPLANATIONS_PATH = (
    REPO_ROOT / "data" / "artifacts" / "explanations" / "stage_explanations.json"
)

# Maximum tool-call iterations per turn to prevent infinite loops
_MAX_TOOL_ITERATIONS = 8

# Default model — granite-3-3-8b-instruct supports tool calling on watsonx.ai
_DEFAULT_MODEL_ID = "ibm/granite-3-3-8b-instruct"
_DEFAULT_WATSONX_URL = "https://us-south.ml.cloud.ibm.com"
_IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"


# ---------------------------------------------------------------------------
# ChatMessage / ChatResponse
# ---------------------------------------------------------------------------

@dataclass
class ChatMessage:
    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass
class ChatResponse:
    reply: str
    """The screened, safe-to-display text response."""

    tool_calls: list[dict] = field(default_factory=list)
    """Each tool call made during this turn: {tool, args, result}."""

    sources: list[str] = field(default_factory=list)
    """Source citations extracted from the reply text."""

    guardian_verdict: dict = field(default_factory=dict)
    """GuardianVerdict serialised to dict for the API response body."""

    offline_mode: bool = False
    """True when no watsonx credentials were available."""


# ---------------------------------------------------------------------------
# IAM bearer-token cache
# ---------------------------------------------------------------------------

@dataclass
class _IamToken:
    access_token: str
    expires_at: float  # Unix timestamp


_iam_cache: _IamToken | None = None


def _exchange_iam_token(api_key: str) -> _IamToken:
    """
    Exchange an IBM Cloud IAM API key for a bearer token.

    POST https://iam.cloud.ibm.com/identity/token
    Response: {"access_token": "...", "expiration": <unix_ts>, ...}

    Raises urllib.error.URLError on network failure.
    """
    data = urllib.parse.urlencode({
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": api_key,
    }).encode()
    req = urllib.request.Request(
        _IAM_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read())

    expires_at = float(body.get("expiration", time.time() + 3600))
    return _IamToken(
        access_token=body["access_token"],
        # Refresh 5 minutes before actual expiry
        expires_at=expires_at - 300,
    )


def _get_bearer_token(api_key: str) -> str:
    """
    Return a valid bearer token, refreshing from IAM if near expiry.

    Caches the token in-process across requests.
    """
    global _iam_cache
    now = time.time()
    if _iam_cache is None or now >= _iam_cache.expires_at:
        _iam_cache = _exchange_iam_token(api_key)
    return _iam_cache.access_token


# ---------------------------------------------------------------------------
# Credential detection
# ---------------------------------------------------------------------------

def _detect_watsonx_config() -> dict | None:
    """
    Return watsonx config dict if all required env vars are set, else None.

    Required: WATSONX_API_KEY, WATSONX_PROJECT_ID
    Optional: WATSONX_URL (default: us-south.ml.cloud.ibm.com)
              WATSONX_MODEL_ID (default: ibm/granite-3-3-8b-instruct)
    """
    api_key = os.environ.get("WATSONX_API_KEY", "").strip()
    project_id = os.environ.get("WATSONX_PROJECT_ID", "").strip()
    if not api_key or not project_id:
        return None
    return {
        "api_key": api_key,
        "project_id": project_id,
        "url": os.environ.get("WATSONX_URL", _DEFAULT_WATSONX_URL).rstrip("/"),
        "model_id": os.environ.get("WATSONX_MODEL_ID", _DEFAULT_MODEL_ID),
    }


# ---------------------------------------------------------------------------
# watsonx.ai chat call
# ---------------------------------------------------------------------------

def _build_watsonx_tools(schemas: list[dict]) -> list[dict]:
    """
    Convert TOOL_SCHEMAS (OpenAI-compatible) to the watsonx /text/chat format.

    watsonx /ml/v1/text/chat accepts tools in this shape:
      {
        "type": "function",
        "function": {
          "name": "...",
          "description": "...",
          "parameters": { <JSON Schema object> }
        }
      }
    This is identical to the OpenAI format, so no transformation is needed
    beyond wrapping each schema in {"type": "function", "function": schema}.
    """
    return [{"type": "function", "function": t} for t in schemas]


def _call_watsonx(
    config: dict,
    messages: list[dict],
    tools: list[dict],
) -> dict:
    """
    Call the watsonx.ai /ml/v1/text/chat endpoint.

    Endpoint: POST {url}/ml/v1/text/chat?version=2024-05-01
    Auth: Bearer token from IAM (exchanged from config["api_key"])

    Returns the raw response dict.
    Raises on HTTP errors.
    """
    bearer = _get_bearer_token(config["api_key"])

    payload = json.dumps({
        "model_id": config["model_id"],
        "project_id": config["project_id"],
        "messages": messages,
        "tools": _build_watsonx_tools(tools),
        "tool_choice": "auto",
        "max_tokens": 1024,
    }).encode()

    url = f"{config['url']}/ml/v1/text/chat?version=2024-05-01"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bearer}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _extract_watsonx_turn(response: dict) -> tuple[str, list[dict]]:
    """
    Parse a watsonx /text/chat response into (text, tool_calls).

    watsonx uses the same response shape as OpenAI chat completions:
      response["choices"][0]["message"] with:
        - "content": str (text response)
        - "tool_calls": list of {"id", "type", "function": {"name", "arguments"}}
      response["choices"][0]["finish_reason"]: "stop" | "tool_calls" | "length"

    Returns (text, []) for text responses and ("", tool_calls) for tool turns.
    """
    choice = response["choices"][0]
    msg = choice["message"]
    finish_reason = choice.get("finish_reason", "stop")

    if finish_reason == "tool_calls" and msg.get("tool_calls"):
        return "", msg["tool_calls"]

    return msg.get("content", "") or "", []


# ---------------------------------------------------------------------------
# Offline degradation
# ---------------------------------------------------------------------------

def _load_explanations() -> dict:
    if _EXPLANATIONS_PATH.exists():
        try:
            with open(_EXPLANATIONS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            pass
    return {"stages": {}, "non_claims": []}


def _offline_response(
    job_id: str | None,
    message: str,
    tool_calls_made: list[dict],
) -> str:
    """
    Assemble a templated response from committed artifact text.

    Used when no watsonx credentials are available.  Numbers come only from
    tool_calls_made results; template text comes from stage_explanations.json.
    """
    expl = _load_explanations()
    non_claims = expl.get("non_claims", [])

    lines = [
        "**Offline mode** — no watsonx credentials configured.  "
        "Showing pipeline artifact summary only.",
        "",
    ]

    if tool_calls_made:
        for tc in tool_calls_made:
            result = tc.get("result", {})
            if result.get("not_available"):
                lines.append(
                    f"**{tc['tool']}**: {result['reason']} "
                    f"[source: {tc['tool']}({', '.join(str(v) for v in tc['args'].values())})]"
                )
            else:
                lines.append(
                    f"**{tc['tool']}** result "
                    f"[source: {tc['tool']}({', '.join(str(v) for v in tc['args'].values())})]:"
                )
                for k, v in result.items():
                    if k not in ("source", "job_id"):
                        lines.append(f"  - {k}: {v}")
        lines.append("")

    if non_claims:
        lines.append("**Non-claims (immutable):**")
        for c in non_claims:
            lines.append(f"  - {c}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def _dispatch_tool(name: str, arguments: dict) -> dict:
    """
    Call the named tool with the given arguments.

    Returns the tool result dict.  Any exception is caught and returned as
    {"error": str} so the model can report it rather than crashing the session.
    """
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name!r}.  Available: {list(TOOL_REGISTRY)}"}
    try:
        return fn(**arguments)
    except TypeError as exc:
        return {"error": f"Tool {name!r} argument error: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Tool {name!r} raised: {type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Main turn runner
# ---------------------------------------------------------------------------

async def run_turn(
    job_id: str | None,
    message: str,
    history: list[dict],
    enqueue_fn=None,
) -> ChatResponse:
    """
    Execute one user turn: send message to watsonx, dispatch tool calls, screen.

    Parameters
    ----------
    job_id : str or None
        The pipeline job being discussed.
    message : str
        The user's message for this turn.
    history : list[dict]
        Prior conversation turns: [{"role": "user"|"assistant", "content": str}].
    enqueue_fn : async callable or None
        Async function (req: JobRequest) -> str used to enqueue a refit job.
        Required only if refit_with_params is called.

    Returns
    -------
    ChatResponse
    """
    config = _detect_watsonx_config()
    system_text = build_system_prompt(job_id)
    tool_calls_made: list[dict] = []

    # Build message list for watsonx (OpenAI-compatible format)
    messages: list[dict] = [{"role": "system", "content": system_text}]
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    # -----------------------------------------------------------------------
    # Offline degradation — no watsonx credentials
    # -----------------------------------------------------------------------
    if config is None:
        if job_id:
            from .tools import get_vetting_results, get_planet_params
            record_summary = _get_record_summary(job_id)
            if record_summary:
                for tce_id in record_summary.get("tce_ids", []):
                    vet_r = get_vetting_results(job_id, tce_id)
                    params_r = get_planet_params(job_id, tce_id)
                    tool_calls_made.append({
                        "tool": "get_vetting_results",
                        "args": {"job_id": job_id, "tce_id": tce_id},
                        "result": vet_r,
                    })
                    tool_calls_made.append({
                        "tool": "get_planet_params",
                        "args": {"job_id": job_id, "tce_id": tce_id},
                        "result": params_r,
                    })

        reply_text = _offline_response(job_id, message, tool_calls_made)
        verdict = screen(reply_text, use_model=False)
        return ChatResponse(
            reply=verdict.screened,
            tool_calls=tool_calls_made,
            sources=_extract_sources(reply_text),
            guardian_verdict=_verdict_dict(verdict),
            offline_mode=True,
        )

    # -----------------------------------------------------------------------
    # Live watsonx path — tool-call loop
    # -----------------------------------------------------------------------
    final_text = ""

    for _iteration in range(_MAX_TOOL_ITERATIONS):
        try:
            response = _call_watsonx(config, messages, TOOL_SCHEMAS)
            text, raw_tool_calls = _extract_watsonx_turn(response)

            if raw_tool_calls:
                # Append the assistant message with tool_calls (watsonx uses
                # the same OpenAI-compatible shape)
                choice_msg = response["choices"][0]["message"]
                messages.append(choice_msg)

                for tc in raw_tool_calls:
                    fn_name = tc["function"]["name"]
                    try:
                        fn_args = json.loads(tc["function"]["arguments"])
                    except (json.JSONDecodeError, KeyError):
                        fn_args = {}

                    result = _dispatch_tool(fn_name, fn_args)

                    # Handle async refit
                    if result.get("pending_enqueue") and enqueue_fn:
                        from ..models import JobRequest
                        new_req = JobRequest(**result["new_request"])
                        new_job_id = await enqueue_fn(new_req)
                        result = {
                            "new_job_id": new_job_id,
                            "status": "queued",
                            "source_job_id": result["source_job_id"],
                        }

                    tool_calls_made.append({
                        "tool": fn_name,
                        "args": fn_args,
                        "result": result,
                    })

                    # Inject tool result — watsonx /text/chat uses the same
                    # role="tool" + tool_call_id format as OpenAI
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result),
                    })

                continue  # call model again with tool results appended

            # Text response — done
            final_text = text
            break

        except Exception as exc:  # noqa: BLE001
            final_text = (
                f"[watsonx call failed: {type(exc).__name__}: {exc}]\n\n"
                + _offline_response(job_id, message, tool_calls_made)
            )
            break
    else:
        final_text = (
            "[Reached maximum tool-call iterations without a text response.]\n\n"
            + _offline_response(job_id, message, tool_calls_made)
        )

    # -----------------------------------------------------------------------
    # Guardian screening — always local, never routed through watsonx
    # -----------------------------------------------------------------------
    verdict = screen(final_text)
    return ChatResponse(
        reply=verdict.screened,
        tool_calls=tool_calls_made,
        sources=_extract_sources(verdict.screened),
        guardian_verdict=_verdict_dict(verdict),
        offline_mode=False,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_record_summary(job_id: str) -> dict | None:
    """Return a minimal summary dict for a done job, or None."""
    try:
        store = TOOL_REGISTRY["get_vetting_results"].__globals__["_get_job_store"]()
    except Exception:  # noqa: BLE001
        return None
    record = store.get(job_id)
    if record is None or record.status != "done" or record.report is None:
        return None
    return {
        "tce_ids": [v.tce_id for v in record.report.vet],
    }


_SOURCE_RE = _re.compile(r"\[source:\s*[^\]]+\]")


def _extract_sources(text: str) -> list[str]:
    """Extract all [source: ...] citation strings from text."""
    return _SOURCE_RE.findall(text)


def _verdict_dict(v: GuardianVerdict) -> dict:
    return {
        "safe": v.safe,
        "risk_label": v.risk_label,
        "model_used": v.model_used,
        "confidence": v.confidence,
    }
