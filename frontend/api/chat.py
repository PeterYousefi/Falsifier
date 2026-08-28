"""
frontend/api/chat.py
====================
Vercel Python serverless function — wraps falsifier.api.chat.session.run_turn.

Accepts:  POST  { job_id: str | null, message: str, history: [{role, content}] }
Returns:  { reply, tool_calls, sources, guardian_verdict, offline_mode, remaining }

Rate limit
----------
3 live watsonx calls per session, enforced here server-side via Upstash Redis
(HTTP REST — no extra SDK; only the standard library + requests is required).

Session identity: an httpOnly / Secure / SameSite=Lax cookie ``_fx_sid`` that
the browser cannot read, so client-side clearing of state does not reset the
budget.

Credentials (Vercel project env vars — server-side only, never VITE_* prefixed):
  WATSONX_APIKEY
  WATSONX_URL
  WATSONX_PROJECT_ID
  WATSONX_MODEL_ID      (optional)
  UPSTASH_REDIS_REST_URL
  UPSTASH_REDIS_REST_TOKEN
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# ---------------------------------------------------------------------------
# Make the repo root importable so `import falsifier` works inside Vercel's
# Python runtime.  The serverless function lives at frontend/api/chat.py;
# the repo root is two levels up.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parent.parent.parent  # frontend/api → frontend → repo root
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Rate-limit constants
# ---------------------------------------------------------------------------
_LIMIT = 3          # max live calls per session
_TTL_SECONDS = 86400  # 24 hours — gives a fresh 3 questions each day
_COOKIE_NAME = "_fx_sid"
_RATE_LIMIT_REPLY = (
    "You've used your 3 questions for this demo session. "
    "Clone the repo and run the pipeline backend locally for unlimited access — see README."
)


# ---------------------------------------------------------------------------
# Upstash Redis helpers (plain HTTP — no SDK dependency)
# ---------------------------------------------------------------------------

def _redis_request(method: str, path: str, body: dict | None = None) -> dict | None:
    """
    Make a single request to the Upstash Redis REST API.
    Returns the parsed JSON response, or None on any failure.
    """
    base_url = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not base_url or not token:
        return None  # Redis not configured — rate limiting disabled
    url = f"{base_url}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:  # noqa: BLE001
        return None


def _get_count(session_id: str) -> int:
    """Return current call count for session_id, or 0 on Redis unavailability."""
    result = _redis_request("GET", f"/get/chat_count:{session_id}")
    if result is None:
        return 0
    try:
        val = result.get("result")
        return int(val) if val is not None else 0
    except (TypeError, ValueError):
        return 0


def _increment_count(session_id: str) -> int:
    """Increment the counter, set TTL on first write, return new value."""
    result = _redis_request("POST", "/pipeline", [
        ["INCR", f"chat_count:{session_id}"],
        ["EXPIRE", f"chat_count:{session_id}", _TTL_SECONDS],
    ])
    if result is None:
        return 1  # Redis unavailable — allow call but don't count
    try:
        # pipeline returns list of results; first is INCR result
        return int(result["result"][0]["result"])
    except Exception:  # noqa: BLE001
        return 1


# ---------------------------------------------------------------------------
# Vercel handler
# ---------------------------------------------------------------------------

class handler(BaseHTTPRequestHandler):  # noqa: N801 — Vercel expects lowercase

    def do_POST(self) -> None:  # noqa: N802
        # ── Parse body ──────────────────────────────────────────────────────
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid JSON"})
            return

        job_id = payload.get("job_id")
        message = payload.get("message", "")
        history = payload.get("history", [])

        if not isinstance(message, str) or not message.strip():
            self._respond(400, {"error": "message is required"})
            return

        # ── Session cookie / ID ─────────────────────────────────────────────
        cookie_header = self.headers.get("Cookie", "")
        session_id = _parse_cookie(cookie_header, _COOKIE_NAME)
        is_new_session = not session_id
        if is_new_session:
            session_id = secrets.token_hex(16)

        # ── Rate-limit check ────────────────────────────────────────────────
        current_count = _get_count(session_id)

        if current_count >= _LIMIT:
            body = {
                "reply": _RATE_LIMIT_REPLY,
                "tool_calls": [],
                "sources": [],
                "guardian_verdict": {
                    "safe": True,
                    "risk_label": "safe",
                    "model_used": "rate_limit",
                    "confidence": None,
                },
                "offline_mode": False,
                "remaining": 0,
            }
            self._respond(200, body, session_id=session_id if is_new_session else None)
            return

        # ── Increment before calling model (counts the attempt) ─────────────
        new_count = _increment_count(session_id)
        remaining = max(0, _LIMIT - new_count)

        # ── Call run_turn ───────────────────────────────────────────────────
        try:
            from falsifier.api.chat.session import run_turn
            response = asyncio.run(run_turn(job_id, message, history))
            body = {
                "reply": response.reply,
                "tool_calls": response.tool_calls,
                "sources": response.sources,
                "guardian_verdict": response.guardian_verdict,
                "offline_mode": response.offline_mode,
                "remaining": remaining,
            }
            self._respond(200, body, session_id=session_id if is_new_session else None)
        except Exception as exc:  # noqa: BLE001
            self._respond(500, {"error": str(exc)})

    def _respond(
        self,
        status: int,
        body: dict,
        session_id: str | None = None,
    ) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        if session_id:
            # httpOnly + Secure + SameSite=Lax — not readable by client JS
            self.send_header(
                "Set-Cookie",
                f"{_COOKIE_NAME}={session_id}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={_TTL_SECONDS}",
            )
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: D102
        pass  # suppress default stderr logging in Vercel


# ---------------------------------------------------------------------------
# Cookie parser (stdlib only)
# ---------------------------------------------------------------------------

def _parse_cookie(header: str, name: str) -> str:
    """Return the value of `name` from a Cookie header, or empty string."""
    for part in header.split(";"):
        part = part.strip()
        if part.startswith(f"{name}="):
            return part[len(name) + 1:]
    return ""
