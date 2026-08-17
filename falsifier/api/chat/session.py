"""
falsifier.api.chat.session
===========================
Conversation state management and tool-call loop.

OpenAI backend
--------------
This module uses OpenAI chat completions as the inference backend.

Configuration (all from environment — nothing hardcoded):
  OPENAI_API_KEY   — OpenAI API key (required for live inference)
  OPENAI_MODEL_ID  — model to use
                     (default: gpt-4o-mini)

Degradation
-----------
If OPENAI_API_KEY is not set the session runs in "offline" mode: it calls
the requested tools directly and assembles a templated answer from
stage_explanations.json without contacting any model.
The endpoint never raises on a missing key.

Guardian
--------
Guardian (guardian.py) runs locally with local_files_only=True.
It is never routed through OpenAI and makes no network call.
It is called on every response including offline mode.

AGENTS.md enforcement
---------------------
Rule 1: numbers are injected into responses only from tool call results.
"""

from __future__ import annotations

import json
import os
import urllib.error
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

# Default model
_DEFAULT_MODEL_ID = "gpt-4o-mini"
_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


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
    """True when no OpenAI API key was available."""


# ---------------------------------------------------------------------------
# Credential detection
# ---------------------------------------------------------------------------

def _detect_openai_config() -> dict | None:
    """
    Return OpenAI config dict if OPENAI_API_KEY is set, else None.

    Required: OPENAI_API_KEY
    Optional: OPENAI_MODEL_ID (default: gpt-4o-mini)
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    return {
        "api_key": api_key,
        "model_id": os.environ.get("OPENAI_MODEL_ID", _DEFAULT_MODEL_ID),
    }


# ---------------------------------------------------------------------------
# OpenAI chat call
# ---------------------------------------------------------------------------

def _call_openai(
    config: dict,
    messages: list[dict],
    tools: list[dict],
) -> dict:
    """
    Call the OpenAI /v1/chat/completions endpoint.

    Auth: Bearer API key from config["api_key"].

    Returns the raw response dict.
    Raises urllib.error.URLError / HTTPError on failure.
    """
    payload = json.dumps({
        "model": config["model_id"],
        "messages": messages,
        "tools": [{"type": "function", "function": t} for t in tools],
        "tool_choice": "auto",
        "max_tokens": 1024,
    }).encode()

    req = urllib.request.Request(
        _OPENAI_CHAT_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config['api_key']}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _extract_openai_turn(response: dict) -> tuple[str, list[dict]]:
    """
    Parse an OpenAI chat completions response into (text, tool_calls).

    OpenAI response shape:
      response["choices"][0]["message"] with:
        - "content": str | None  (text response)
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

    Used when no OpenAI API key is available.  Numbers come only from
    tool_calls_made results; template text comes from stage_explanations.json.
    """
    expl = _load_explanations()
    non_claims = expl.get("non_claims", [])

    lines = [
        "**Offline mode** — no OpenAI API key configured.  "
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
    Execute one user turn: send message to OpenAI, dispatch tool calls, screen.

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
    config = _detect_openai_config()
    system_text = build_system_prompt(job_id)
    tool_calls_made: list[dict] = []

    # Build message list (OpenAI-compatible format)
    messages: list[dict] = [{"role": "system", "content": system_text}]
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    # -----------------------------------------------------------------------
    # Offline degradation — no OpenAI API key
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
    # Live OpenAI path — tool-call loop
    # -----------------------------------------------------------------------
    final_text = ""

    for _iteration in range(_MAX_TOOL_ITERATIONS):
        try:
            response = _call_openai(config, messages, TOOL_SCHEMAS)
            text, raw_tool_calls = _extract_openai_turn(response)

            if raw_tool_calls:
                # Append the assistant message with tool_calls
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

                    # Inject tool result
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
                f"[OpenAI call failed: {type(exc).__name__}: {exc}]\n\n"
                + _offline_response(job_id, message, tool_calls_made)
            )
            break
    else:
        final_text = (
            "[Reached maximum tool-call iterations without a text response.]\n\n"
            + _offline_response(job_id, message, tool_calls_made)
        )

    # -----------------------------------------------------------------------
    # Guardian screening — always local, never routed through OpenAI
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
