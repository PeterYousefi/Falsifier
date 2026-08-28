#!/usr/bin/env python3
"""
scripts/check_watsonx_connection.py
=====================================
Verify that the WATSONX_APIKEY, WATSONX_URL, and WATSONX_PROJECT_ID values
in the local .env file can authenticate and connect to IBM watsonx.ai.

This script is COMPLETELY independent of Vercel, the frontend, and the
deployed /api/chat endpoint.  It constructs a raw ModelInference client from
the three credentials, sends one minimal chat message, and reports success or
failure with enough detail to identify which credential is wrong.

For end-to-end smoke-testing of the deployed /api/chat route instead, see
scripts/check_chat_api.py.
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# ANSI colour helpers (no external dependency)
# ---------------------------------------------------------------------------
_GREEN = "\033[32m"
_RED   = "\033[31m"
_RESET = "\033[0m"

_ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")


# ---------------------------------------------------------------------------
# .env loader — python-dotenv if available, stdlib fallback otherwise
# ---------------------------------------------------------------------------

def _load_dotenv(path: str) -> None:
    """Load key=value pairs from *path* into os.environ (best-effort)."""
    try:
        from dotenv import load_dotenv  # type: ignore[import]
        load_dotenv(dotenv_path=path, override=False)
        return
    except ImportError:
        pass

    # stdlib fallback: manual parse
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        pass  # no .env is fine — env vars may already be set


# ---------------------------------------------------------------------------
# Credential validation
# ---------------------------------------------------------------------------

def _require_env() -> dict:
    """
    Return {api_key, url, project_id, model_id} from the environment.
    Print a red FAIL and exit(1) if any required variable is missing.
    """
    required = {
        "WATSONX_APIKEY":      "api_key",
        "WATSONX_URL":         "url",
        "WATSONX_PROJECT_ID":  "project_id",
    }
    config: dict = {}
    missing = []
    for env_var, key in required.items():
        val = os.environ.get(env_var, "").strip()
        if not val:
            missing.append(env_var)
        else:
            config[key] = val

    if missing:
        for var in missing:
            print(f"{_RED}✗ FAIL{_RESET}  {var} is missing or empty in the environment / .env file.")
        sys.exit(1)

    config["model_id"] = (
        os.environ.get("WATSONX_MODEL_ID", "ibm/granite-3-3-8b-instruct").strip()
        or "ibm/granite-3-3-8b-instruct"
    )
    return config


# ---------------------------------------------------------------------------
# Connection check
# ---------------------------------------------------------------------------

def _check(config: dict) -> int:
    """Build a WatsonxAdapter, fire one chat message, print result."""
    # Import here to avoid pulling in ibm_watsonx_ai at module scope.
    from falsifier.api.chat._adapters.watsonx import WatsonxAdapter

    adapter = WatsonxAdapter(config)
    messages = [{"role": "user", "content": "Hello, are you working?"}]

    try:
        response = adapter.chat(messages=messages, tools=[])
    except Exception as exc:
        msg = str(exc)
        msg_lower = msg.lower()

        if "api_key" in msg_lower or "apikey" in msg_lower or "unauthorized" in msg_lower or "401" in msg:
            hint = "WATSONX_APIKEY appears to be invalid or revoked."
        elif "project" in msg_lower or "403" in msg or "forbidden" in msg_lower:
            hint = "WATSONX_PROJECT_ID appears to be invalid or inaccessible."
        elif "url" in msg_lower or "connect" in msg_lower or "timeout" in msg_lower or "resolve" in msg_lower:
            hint = "WATSONX_URL appears to be wrong or unreachable."
        else:
            hint = "Check all three credentials (WATSONX_APIKEY, WATSONX_URL, WATSONX_PROJECT_ID)."

        print(f"{_RED}✗ FAIL{_RESET}  {hint}")
        print(f"  SDK error: {exc}")
        return 1

    # Extract reply text from the ModelInference chat response dict.
    try:
        reply = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        reply = str(response)

    print(f"{_GREEN}✓ PASS{_RESET}  watsonx.ai authenticated and responded successfully.")
    print(f"  Model:  {config['model_id']}")
    print(f"  Reply:  {reply!r}")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    _load_dotenv(_ENV_FILE)
    config = _require_env()
    return _check(config)


if __name__ == "__main__":
    sys.exit(main())
