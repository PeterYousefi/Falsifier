"""
falsifier.api.routes.chat
==========================
POST /chat endpoint.

Request body
------------
{
  "job_id":  "string or null",
  "message": "string",
  "history": [{"role": "user"|"assistant", "content": "string"}, ...]
}

Response body
-------------
{
  "reply":            "string",      // screened text safe to display
  "tool_calls":       [...],         // tools called this turn
  "sources":          [...],         // [source: ...] citations in reply
  "guardian_verdict": {...},         // {safe, risk_label, model_used, confidence}
  "offline_mode":     bool           // true when no LLM key is set
}

The /chat endpoint never hardcodes any scientific value.  Every number in
"reply" must originate from a tool call result that reads from a pipeline
artifact.  The Guardian screens all LLM output before it is placed in "reply".
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..queue import enqueue_job
from ..chat.session import run_turn

router = APIRouter(prefix="/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class HistoryMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    job_id: str | None = None
    """
    Pipeline job to discuss.  When provided, tool calls use this job_id by
    default.  Null is valid for general questions about the pipeline.
    """

    message: str
    """The user's message for this turn."""

    history: list[HistoryMessage] = Field(default_factory=list)
    """Prior conversation turns, oldest first."""


class ChatResponseBody(BaseModel):
    reply: str
    """Guardian-screened text safe to display to the user."""

    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    """Each tool called this turn: {tool, args, result}."""

    sources: list[str] = Field(default_factory=list)
    """[source: tool(args)] citation strings extracted from reply."""

    guardian_verdict: dict[str, Any] = Field(default_factory=dict)
    """{safe, risk_label, model_used, confidence} from the heuristic screener."""

    offline_mode: bool = False
    """True when no OpenAI API key was configured; response is templated."""


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("", response_model=ChatResponseBody)
async def chat(req: ChatRequest) -> ChatResponseBody:
    """
    Execute one chat turn.

    The server calls the pipeline tools, assembles a response, and screens
    it through the Guardian before returning.  If no OpenAI API key is
    configured, the response is assembled from committed artifact text only
    (offline degradation).
    """
    result = await run_turn(
        job_id=req.job_id,
        message=req.message,
        history=[h.model_dump() for h in req.history],
        enqueue_fn=enqueue_job,
    )
    return ChatResponseBody(
        reply=result.reply,
        tool_calls=result.tool_calls,
        sources=result.sources,
        guardian_verdict=result.guardian_verdict,
        offline_mode=result.offline_mode,
    )
