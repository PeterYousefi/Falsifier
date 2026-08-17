"""
falsifier.api.chat.session
===========================
Conversation state management and tool-call loop.

The session drives the LLM interaction:
  1. Build the system prompt (system_prompt.build_system_prompt).
  2. Send user message + history to the model with tool schemas.
  3. If the model emits a tool_use block, dispatch to tools.TOOL_REGISTRY.
  4. Append the tool result to the conversation and call the model again.
  5. Repeat until the model emits a text response (no pending tool calls).
  6. Screen the final text through guardian.screen().
  7. Return ChatResponse.

Degradation
-----------
If no LLM API key is set (OPENAI_API_KEY, ANTHROPIC_API_KEY, WATSONX_API_KEY)
the session runs in "offline" mode: it calls the requested tools directly and
assembles a templated answer from stage_explanations.json without contacting
any hosted model.

AGENTS.md enforcement
---------------------
Rule 1: numbers are only injected into responses from tool call results.
The offline path also satisfies this: it reads from tools, never from memory.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .guardian import GuardianVerdict, screen
from .system_prompt import build_system_prompt
from .tools import TOOL_REGISTRY, TOOL_SCHEMAS

REPO_ROOT = Path(__file__).parent.parent.parent.parent
_EXPLANATIONS_PATH = (
    REPO_ROOT / "data" / "artifacts" / "explanations" / "stage_explanations.json"
)

# Maximum tool-call iterations per turn to prevent infinite loops
_MAX_TOOL_ITERATIONS = 8


# ---------------------------------------------------------------------------
# ChatMessage — one turn in the conversation
# ---------------------------------------------------------------------------

@dataclass
class ChatMessage:
    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None


# ---------------------------------------------------------------------------
# ChatResponse — returned by run_turn()
# ---------------------------------------------------------------------------

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
    """True when no LLM API key was available and offline degradation was used."""


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

    Used when no LLM key is available.  Numbers come only from tool_calls_made
    results; template text comes from stage_explanations.json.
    """
    expl = _load_explanations()
    non_claims = expl.get("non_claims", [])

    lines = [
        "**Offline mode** — no LLM API key configured.  "
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
# LLM client (minimal, provider-agnostic)
# ---------------------------------------------------------------------------

def _detect_api_key() -> tuple[str, str] | None:
    """
    Return (provider, api_key) for the first available LLM provider.

    Checks: OPENAI_API_KEY, ANTHROPIC_API_KEY, WATSONX_API_KEY.
    Returns None if none are set.
    """
    for env_var, provider in [
        ("OPENAI_API_KEY", "openai"),
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("WATSONX_API_KEY", "watsonx"),
    ]:
        key = os.environ.get(env_var, "").strip()
        if key:
            return provider, key
    return None


def _call_llm_openai(
    api_key: str,
    messages: list[dict],
    tools: list[dict],
) -> dict:
    """
    Call the OpenAI chat completions API.

    Returns the raw API response dict.  Raises on HTTP errors.
    """
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "model": "gpt-4o-mini",
        "messages": messages,
        "tools": [{"type": "function", "function": t} for t in tools],
        "tool_choice": "auto",
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _call_llm_anthropic(
    api_key: str,
    messages: list[dict],
    tools: list[dict],
    system: str,
) -> dict:
    """
    Call the Anthropic Messages API.

    Returns a normalised response dict with keys "content" and "stop_reason".
    """
    import urllib.request

    # Anthropic uses a separate system parameter
    ant_tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in tools
    ]
    payload = json.dumps({
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 1024,
        "system": system,
        "messages": [m for m in messages if m["role"] != "system"],
        "tools": ant_tools,
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def _dispatch_tool(name: str, arguments: dict) -> dict:
    """
    Call the named tool with the given arguments.

    Returns the tool result dict.  Any exception is caught and returned as
    {"error": str} so the LLM can report it rather than crashing the session.
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
    Execute one user turn: send message to LLM, dispatch tool calls, screen.

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
    api_info = _detect_api_key()
    system_text = build_system_prompt(job_id)
    tool_calls_made: list[dict] = []

    # Build message list for the LLM
    messages: list[dict] = [{"role": "system", "content": system_text}]
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    # -----------------------------------------------------------------------
    # Offline degradation — no API key available
    # -----------------------------------------------------------------------
    if api_info is None:
        # Run obvious tools implied by the message context for the summary
        if job_id:
            # Always try to surface job summary
            from .tools import get_vetting_results, get_planet_params
            report_record = _get_record_summary(job_id)
            if report_record:
                for tce_id in report_record.get("tce_ids", []):
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
    # Live LLM path — tool-call loop
    # -----------------------------------------------------------------------
    provider, api_key = api_info
    final_text = ""

    for _iteration in range(_MAX_TOOL_ITERATIONS):
        try:
            if provider == "openai":
                response = _call_llm_openai(api_key, messages, TOOL_SCHEMAS)
                choice = response["choices"][0]
                msg = choice["message"]
                finish_reason = choice.get("finish_reason", "stop")

                if finish_reason == "tool_calls" and msg.get("tool_calls"):
                    # Append assistant message with tool_calls
                    messages.append(msg)
                    for tc in msg["tool_calls"]:
                        fn_name = tc["function"]["name"]
                        try:
                            fn_args = json.loads(tc["function"]["arguments"])
                        except json.JSONDecodeError:
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
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(result),
                        })
                    continue  # call LLM again with tool results

                # Text response
                final_text = msg.get("content", "") or ""
                break

            elif provider == "anthropic":
                response = _call_llm_anthropic(
                    api_key, messages, TOOL_SCHEMAS, system_text
                )
                stop_reason = response.get("stop_reason", "end_turn")
                content_blocks = response.get("content", [])

                if stop_reason == "tool_use":
                    # Extract tool use blocks and text blocks
                    tool_results = []
                    for block in content_blocks:
                        if block.get("type") == "tool_use":
                            fn_name = block["name"]
                            fn_args = block.get("input", {})
                            result = _dispatch_tool(fn_name, fn_args)
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
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block["id"],
                                "content": json.dumps(result),
                            })

                    # Append assistant turn and tool results
                    messages.append({
                        "role": "assistant",
                        "content": content_blocks,
                    })
                    messages.append({
                        "role": "user",
                        "content": tool_results,
                    })
                    continue

                # Text response
                for block in content_blocks:
                    if block.get("type") == "text":
                        final_text = block.get("text", "")
                        break
                break

            else:
                # Unknown provider — offline fallback
                final_text = _offline_response(job_id, message, tool_calls_made)
                break

        except Exception as exc:  # noqa: BLE001
            # LLM call failed — fall back to offline response
            final_text = (
                f"[LLM call failed: {type(exc).__name__}: {exc}]\n\n"
                + _offline_response(job_id, message, tool_calls_made)
            )
            break
    else:
        final_text = (
            "[Reached maximum tool-call iterations without a text response.]\n\n"
            + _offline_response(job_id, message, tool_calls_made)
        )

    # -----------------------------------------------------------------------
    # Guardian screening
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


import re as _re

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
