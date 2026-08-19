"""
tests/test_pipeline_constants.py
===================================
Enforces that every shared constant is defined exactly once, in
scripts/pipeline_constants.py, and that no consuming script carries
a local redefinition.

Policy
------
- Drift between scripts/adversarial_selftest.py and
  scripts/injection_recovery.py was the direct cause of the contaminated
  adversarial run of 2026-08-19 (the original DEFAULT_QUIET_STARS list was
  never updated in adversarial_selftest.py after the replacements were
  committed to injection_recovery.py).
- This test makes that class of drift a CI failure.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
CONSTANTS_MODULE = REPO_ROOT / "scripts" / "pipeline_constants.py"

# ---------------------------------------------------------------------------
# The canonical set of names that MUST live only in pipeline_constants.py.
# Extend this list whenever a new shared constant is added to the module.
# ---------------------------------------------------------------------------
SHARED_CONSTANT_NAMES = {
    "DEFAULT_QUIET_STARS",
    "DEPTH_GRID_PPM",
    "PERIOD_GRID_DAYS",
    "PERIOD_MATCH_TOLERANCE",
    "SDE_THRESHOLD",
    "MIN_TRANSITS_REQUIRED",
    "MIN_BASELINE_DAYS",
}

# Scripts that consume shared constants (must import, not redefine them).
CONSUMING_SCRIPTS = [
    REPO_ROOT / "scripts" / "adversarial_selftest.py",
    REPO_ROOT / "scripts" / "injection_recovery.py",
    REPO_ROOT / "scripts" / "merge_injection_recovery.py",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _top_level_assignments(source: str) -> set[str]:
    """
    Return the set of names assigned at module top level in *source*.

    Handles simple ``NAME = ...`` and annotated ``NAME: type = ...``
    assignments.  Ignores names defined inside functions, classes, or
    conditional blocks so that local variables and constants don't trip
    the check.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
    return names


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPipelineConstantsModule:
    def test_constants_module_exists(self):
        assert CONSTANTS_MODULE.exists(), (
            f"scripts/pipeline_constants.py does not exist. "
            "Create it and move all shared constants there."
        )

    @pytest.mark.parametrize("name", sorted(SHARED_CONSTANT_NAMES))
    def test_constant_defined_in_module(self, name: str):
        """Every shared constant must be defined in pipeline_constants.py."""
        source = CONSTANTS_MODULE.read_text(encoding="utf-8")
        defined = _top_level_assignments(source)
        assert name in defined, (
            f"Shared constant {name!r} is not defined in scripts/pipeline_constants.py. "
            "Add it to the module and import it in the consuming scripts."
        )


class TestNoLocalCopies:
    """
    No consuming script may re-define a shared constant at module top level.

    A re-definition is detected by finding a bare ``NAME = ...`` or
    ``NAME: type = ...`` assignment at module scope in the script.
    Importing from pipeline_constants is fine; re-assigning the name locally
    is not.
    """

    @pytest.mark.parametrize(
        "script,name",
        [
            (script, name)
            for script in CONSUMING_SCRIPTS
            for name in sorted(SHARED_CONSTANT_NAMES)
        ],
    )
    def test_no_local_redefinition(self, script: Path, name: str):
        if not script.exists():
            pytest.skip(f"{script.name} does not exist")
        source = script.read_text(encoding="utf-8")
        local_names = _top_level_assignments(source)
        assert name not in local_names, (
            f"{script.name} re-defines {name!r} at module scope. "
            f"Remove the local definition and import from "
            f"scripts.pipeline_constants instead."
        )


class TestImportsSharedConstants:
    """
    Each consuming script must import the shared constants it uses.

    This test checks for a ``from scripts.pipeline_constants import`` block
    that names each shared constant present in the script's import list.
    It does NOT require every script to import every constant — only that
    whatever shared constant a script uses is imported from the module.
    """

    _IMPORT_RE = re.compile(
        r'from\s+scripts\.pipeline_constants\s+import\s+(.*?)(?=\n(?!\s)|\Z)',
        re.DOTALL,
    )

    def _imported_names(self, source: str) -> set[str]:
        matches = self._IMPORT_RE.findall(source)
        names: set[str] = set()
        for block in matches:
            # Strip parentheses and comments
            block = re.sub(r'[()]', '', block)
            block = re.sub(r'#[^\n]*', '', block)
            for tok in re.split(r'[,\s]+', block):
                tok = tok.strip()
                if tok:
                    names.add(tok)
        return names

    @pytest.mark.parametrize("script", CONSUMING_SCRIPTS)
    def test_has_import_block(self, script: Path):
        """Consuming scripts must have a 'from scripts.pipeline_constants import' block."""
        if not script.exists():
            pytest.skip(f"{script.name} does not exist")
        source = script.read_text(encoding="utf-8")
        assert self._IMPORT_RE.search(source), (
            f"{script.name} does not import from scripts.pipeline_constants. "
            "Add the import block."
        )

    @pytest.mark.parametrize("script", CONSUMING_SCRIPTS)
    def test_uses_constant_names_are_imported(self, script: Path):
        """
        Any shared constant name that appears bare in a script body must be
        listed in the script's pipeline_constants import.

        This catches the case where a name is used but was accidentally
        removed from the import block (e.g. after a merge conflict).
        """
        if not script.exists():
            pytest.skip(f"{script.name} does not exist")
        source = script.read_text(encoding="utf-8")
        imported = self._imported_names(source)
        # Remove the import block itself from the search so we don't count
        # the names in the import statement as "uses".
        body = self._IMPORT_RE.sub('', source)
        for name in SHARED_CONSTANT_NAMES:
            if re.search(r'\b' + re.escape(name) + r'\b', body):
                assert name in imported, (
                    f"{script.name} uses {name!r} but does not import it "
                    f"from scripts.pipeline_constants. "
                    f"Add {name!r} to the import block."
                )
