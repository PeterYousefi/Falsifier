#!/usr/bin/env python3
"""
scripts/mcp_server.py
======================
Stdio MCP server exposing three verification-gate tools for use from Bob
sessions.  No network access, no credentials required.

Tools
-----
verify_readme
    Runs ``scripts/verify_readme.py --strict`` and returns the exit code plus
    the full drift report.

run_golden_tests
    Runs the two golden regressions (test_kepler10_recovery.py and
    test_known_eb_rejected.py) and returns pass/fail per test together with
    the EXPECTED_TRIGGERING_TEST name asserted in test_known_eb_rejected.py.

check_invented_numbers
    Runs ``tests/test_no_number_is_invented.py`` and returns any float token
    that failed to trace to a committed artifact.

Wiring
------
Register this server in ``.bob/mcp.json`` (workspace scope) so that it is
available from inside a Bob session:

    {
      "mcpServers": {
        "falsifier-gates": {
          "command": "python3",
          "args": ["scripts/mcp_server.py"]
        }
      }
    }

Policy
------
AGENTS.md rules apply to this server:
  Rule 1 — no hardcoded scientific values in the response payloads.
  Rule 5 — claims cited in responses come from committed artifacts only.

This server makes no network calls and requires no API credentials.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# MCP message I/O helpers (stdio transport)
# ---------------------------------------------------------------------------

def _write_message(msg: dict) -> None:
    line = json.dumps(msg)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _read_message() -> dict | None:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        return json.loads(line.strip())
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _tool_verify_readme(_args: dict) -> dict:
    """
    Run scripts/verify_readme.py --strict.

    Returns exit_code (int) and output (str).
    """
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "verify_readme.py"), "--strict"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    combined = (result.stdout + result.stderr).strip()
    return {
        "exit_code": result.returncode,
        "output": combined,
        "passed": result.returncode == 0,
    }


def _tool_run_golden_tests(_args: dict) -> dict:
    """
    Run the two golden regression tests.

    Returns pass/fail per test and the EXPECTED_TRIGGERING_TEST name
    asserted in test_known_eb_rejected.py.
    """
    # Read the expected triggering test name from the test file
    eb_test_path = REPO_ROOT / "tests" / "test_known_eb_rejected.py"
    triggering_test_name: str | None = None
    if eb_test_path.exists():
        text = eb_test_path.read_text(encoding="utf-8")
        m = re.search(r'EXPECTED_TRIGGERING_TEST\s*=\s*["\']([^"\']+)["\']', text)
        if m:
            triggering_test_name = m.group(1)

    tests = {
        "test_kepler10_recovery": "tests/test_kepler10_recovery.py",
        "test_known_eb_rejected": "tests/test_known_eb_rejected.py",
    }

    results: dict[str, dict] = {}
    for name, rel_path in tests.items():
        r = subprocess.run(
            [sys.executable, "-m", "pytest", rel_path, "-v", "--tb=short", "-q"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        results[name] = {
            "exit_code": r.returncode,
            "passed": r.returncode == 0,
            "output": (r.stdout + r.stderr).strip()[-2000:],  # trim long output
        }

    return {
        "tests": results,
        "expected_triggering_test": triggering_test_name,
        "all_passed": all(v["passed"] for v in results.values()),
    }


def _tool_check_invented_numbers(_args: dict) -> dict:
    """
    Run tests/test_no_number_is_invented.py.

    Returns exit_code, whether all tests passed, and any float tokens that
    failed to trace to a committed artifact.
    """
    r = subprocess.run(
        [sys.executable, "-m", "pytest",
         "tests/test_no_number_is_invented.py",
         "-v", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    output = (r.stdout + r.stderr).strip()

    # Extract failed float tokens from pytest output (lines like "→  1.23456")
    failed_tokens: list[str] = []
    for line in output.splitlines():
        m = re.search(r'→\s+(\d+\.\d{3,})', line)
        if m:
            failed_tokens.append(m.group(1))

    return {
        "exit_code": r.returncode,
        "passed": r.returncode == 0,
        "failed_tokens": failed_tokens,
        "output": output[-2000:],  # trim long output
    }


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

_TOOLS = {
    "verify_readme": _tool_verify_readme,
    "run_golden_tests": _tool_run_golden_tests,
    "check_invented_numbers": _tool_check_invented_numbers,
}

_TOOL_SCHEMAS = [
    {
        "name": "verify_readme",
        "description": (
            "Run scripts/verify_readme.py --strict and return the exit code and drift report. "
            "Exits 0 when all CLAIM blocks in README.md match their regenerated values."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "run_golden_tests",
        "description": (
            "Run the two golden regression tests "
            "(test_kepler10_recovery.py and test_known_eb_rejected.py). "
            "Returns pass/fail per test and the EXPECTED_TRIGGERING_TEST name "
            "asserted in test_known_eb_rejected.py."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "check_invented_numbers",
        "description": (
            "Run tests/test_no_number_is_invented.py and return any float token "
            "that failed to trace to a committed artifact. "
            "A passing result means all scientific floats in frontend/src/ and "
            "API fixtures are backed by committed artifacts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# ---------------------------------------------------------------------------
# MCP request handlers
# ---------------------------------------------------------------------------

def _handle_initialize(msg: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg.get("id"),
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "falsifier-gates",
                "version": "0.1.0",
            },
        },
    }


def _handle_tools_list(msg: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": msg.get("id"),
        "result": {"tools": _TOOL_SCHEMAS},
    }


def _handle_tools_call(msg: dict) -> dict:
    params = msg.get("params", {})
    tool_name = params.get("name", "")
    tool_args = params.get("arguments", {}) or {}

    tool_fn = _TOOLS.get(tool_name)
    if tool_fn is None:
        return {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {
                "code": -32601,
                "message": f"Unknown tool: {tool_name!r}",
            },
        }

    try:
        result = tool_fn(tool_args)
        return {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2),
                    }
                ],
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {
                "code": -32603,
                "message": f"Tool {tool_name!r} error: {type(exc).__name__}: {exc}",
            },
        }


def _handle_notifications_initialized(_msg: dict) -> None:
    """Notifications have no response."""


_HANDLERS = {
    "initialize": _handle_initialize,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}

_NOTIFICATION_HANDLERS = {
    "notifications/initialized": _handle_notifications_initialized,
}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Stdio MCP server main loop.

    Reads JSON-RPC messages from stdin (one per line), dispatches to the
    appropriate handler, and writes responses to stdout.
    """
    while True:
        msg = _read_message()
        if msg is None:
            break  # stdin closed — clean exit

        method = msg.get("method", "")

        # Notifications (no id, no response)
        if "id" not in msg:
            handler = _NOTIFICATION_HANDLERS.get(method)
            if handler:
                handler(msg)
            continue

        # Requests
        handler = _HANDLERS.get(method)
        if handler is None:
            _write_message({
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method!r}",
                },
            })
            continue

        response = handler(msg)
        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    main()
