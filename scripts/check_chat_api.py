#!/usr/bin/env python3
"""
scripts/check_chat_api.py
==========================
Smoke-test the deployed /api/chat endpoint end-to-end.

Purpose
-------
Verifies that the endpoint is reachable, returns a valid JSON response, and
is actually backed by a live watsonx.ai call (not degrading to offline/
templated mode because a required env var is missing on the server).

Usage
-----
    python scripts/check_chat_api.py [BASE_URL]

  BASE_URL   Root URL of the deployment (default: https://falsifier.vercel.app)

Examples
--------
    python scripts/check_chat_api.py
    python scripts/check_chat_api.py http://localhost:3000

Exit codes
----------
  0   Green PASS — endpoint reachable, watsonx.ai was reached (offline_mode=false).
  1   Yellow WARNING — endpoint reachable but running in offline/templated mode.
  1   Red FAIL — HTTP error, connection error, or unexpected response shape.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# ANSI colour helpers (no external dependency)
# ---------------------------------------------------------------------------
_RED    = "\033[31m"
_YELLOW = "\033[33m"
_GREEN  = "\033[32m"
_RESET  = "\033[0m"

_DEFAULT_BASE_URL = "https://falsifier.vercel.app"
_REQUEST_BODY = {"job_id": None, "message": "Hello, are you working?", "history": []}
_TIMEOUT = 30  # seconds


def _check(base_url: str) -> int:
    url = base_url.rstrip("/") + "/api/chat"
    payload = json.dumps(_REQUEST_BODY).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            status = resp.status
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        print(f"{_RED}✗ FAIL{_RESET}  HTTP {exc.code} from {url}")
        print(f"  {exc.reason}")
        return 1
    except OSError as exc:
        print(f"{_RED}✗ FAIL{_RESET}  Connection error: {exc}")
        return 1

    if status < 200 or status >= 300:
        print(f"{_RED}✗ FAIL{_RESET}  Non-2xx status {status} from {url}")
        return 1

    try:
        data: dict = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"{_RED}✗ FAIL{_RESET}  Response is not valid JSON: {exc}")
        return 1

    reply     = data.get("reply", "<no reply>")
    offline   = data.get("offline_mode", True)   # default True = safe/pessimistic
    remaining = data.get("remaining", "?")

    if offline:
        print(f"{_YELLOW}⚠ WARNING{_RESET}  Endpoint responded but is in offline/templated mode.")
        print(f"  WATSONX_APIKEY or another required env var is likely not set on the server.")
        print(f"  Reply: {reply!r}")
        return 1

    print(f"{_GREEN}✓ PASS{_RESET}  watsonx.ai reached successfully.")
    print(f"  Reply:     {reply!r}")
    print(f"  Remaining: {remaining}")
    return 0


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_BASE_URL
    return _check(base_url)


if __name__ == "__main__":
    sys.exit(main())
