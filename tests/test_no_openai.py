"""
tests/test_no_openai.py
========================
Architecture tests: OpenAI must never be re-introduced.

Policy
------
OpenAI was removed in favour of IBM watsonx.ai Granite as the chat backend.
These tests are a permanent CI gate that fires loudly if OpenAI ever comes back.

Two assertions are enforced:
  1. No Python module inside ``falsifier/`` imports ``openai`` (at any depth).
  2. No file in the repo (excluding .git, __pycache__, .venv, and a narrow
     changelog allowlist) contains the string "OPENAI" or "gpt-4o".

Acceptance criteria (from AGENTS.md task spec):
  `grep -rin "openai|gpt-4o" . --exclude-dir=.git` returns nothing outside
  a changelog entry; these tests must fail loudly if the constraint is violated.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent

# Files / directories that are never scanned for the string-level check.
# Only add paths here with an explicit, reviewed reason.
_STRING_SCAN_EXCLUDES: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "node_modules",
        ".pytest_cache",
        "falsifier.egg-info",
        # test_no_openai.py itself — it must contain the strings to check for them
        "test_no_openai.py",
    }
)

# ---------------------------------------------------------------------------
# 1. No module inside falsifier/ imports openai
# ---------------------------------------------------------------------------

def _collect_python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _imports_openai(source_path: Path) -> list[str]:
    """
    Parse source_path with ast and return all import targets that match 'openai'.
    Returns an empty list if the file has no openai import.
    """
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []

    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openai" or alias.name.startswith("openai."):
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "openai" or module.startswith("openai."):
                hits.append(module)
    return hits


@pytest.mark.no_network
def test_no_openai_import_in_falsifier():
    """
    No module inside falsifier/ may import openai.

    OpenAI has been removed in favour of IBM watsonx.ai Granite.  If this test
    fails it means OpenAI was re-introduced — which is a policy violation.
    """
    falsifier_root = REPO_ROOT / "falsifier"
    violations: list[str] = []

    for py_file in _collect_python_files(falsifier_root):
        imports = _imports_openai(py_file)
        if imports:
            rel = py_file.relative_to(REPO_ROOT)
            violations.append(f"{rel}: imports {imports}")

    assert not violations, (
        "OpenAI import(s) detected inside falsifier/.\n"
        "OpenAI has been removed; use the IBM watsonx.ai adapter instead.\n"
        "Violations:\n" + "\n".join(f"  {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# 2. No file in the repo contains "OPENAI" or "gpt-4o"
# ---------------------------------------------------------------------------

_FORBIDDEN_STRINGS = ("OPENAI", "gpt-4o")

# Per-file allowlist: only entries with an explicit reviewed reason.
# Do NOT add new entries without a documented justification.
_STRING_ALLOWLIST: dict[str, set[str]] = {
    # This test file must reference the strings to check for them.
    # (Already excluded via _STRING_SCAN_EXCLUDES above — belt and suspenders.)
    # docs/COMPETITION_GAPS.md mentions ajdarstudio in a note about badge
    # issues — that note contains neither OPENAI nor gpt-4o, so no entry needed.
}


def _should_skip_path(path: Path) -> bool:
    """Return True if path should be excluded from the string scan."""
    for part in path.parts:
        if part in _STRING_SCAN_EXCLUDES:
            return True
    return False


@pytest.mark.no_network
def test_no_openai_string_in_repo():
    """
    No file in the repo (outside the scan excludes) may contain the literal
    string "OPENAI" or "gpt-4o".

    This catches env-var names, comments, config values, and any other form
    of OpenAI re-introduction that would not surface as a Python import.
    """
    violations: list[str] = []

    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if _should_skip_path(path.relative_to(REPO_ROOT)):
            continue

        # Skip binary files
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue

        for forbidden in _FORBIDDEN_STRINGS:
            if forbidden in text:
                # Check per-file allowlist
                allowed = _STRING_ALLOWLIST.get(str(path.relative_to(REPO_ROOT)), set())
                if forbidden not in allowed:
                    # Find the first offending line number for the error message
                    for lineno, line in enumerate(text.splitlines(), start=1):
                        if forbidden in line:
                            rel = path.relative_to(REPO_ROOT)
                            violations.append(f"{rel}:{lineno}: contains {forbidden!r}")
                            break

    assert not violations, (
        "OpenAI/gpt-4o string(s) found in repository.\n"
        "Remove all OpenAI references; the supported backend is IBM watsonx.ai.\n"
        "Violations:\n" + "\n".join(f"  {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# 3. Deterministic fallback is selected when no credential is present
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_fallback_adapter_selected_when_no_credential():
    """
    When WATSONX_APIKEY is absent, get_provider() returns a FallbackAdapter,
    not a WatsonxAdapter.
    """
    import os
    from unittest.mock import patch
    from falsifier.api.chat.provider import get_provider
    from falsifier.api.chat._adapters.fallback import FallbackAdapter

    with patch.dict(os.environ, {"WATSONX_APIKEY": ""}):
        # session._detect_watsonx_config returns None when key is empty
        provider = get_provider(watsonx_config=None)

    assert isinstance(provider, FallbackAdapter), (
        f"Expected FallbackAdapter when no credential is set, got {type(provider).__name__}"
    )


@pytest.mark.no_network
def test_fallback_adapter_refuses_out_of_artifact_questions():
    """
    When stage_explanations.json is absent, FallbackAdapter responds with a
    not_available marker rather than inventing an answer.
    """
    from unittest.mock import patch
    from falsifier.api.chat._adapters.fallback import FallbackAdapter, _EXPLANATIONS_PATH

    adapter = FallbackAdapter()

    # Simulate artifact being absent
    with patch("falsifier.api.chat._adapters.fallback._EXPLANATIONS_PATH",
               _EXPLANATIONS_PATH.parent / "__nonexistent_artifact__.json"):
        response = adapter.chat(
            messages=[{"role": "user", "content": "What is the period?"}],
            tools=[],
        )

    content = response["choices"][0]["message"]["content"]
    assert "not_available" in content, (
        "FallbackAdapter must return a 'not_available' marker when the artifact "
        f"is absent, not invent an answer.  Got: {content!r}"
    )
