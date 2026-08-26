"""
Gate 8 — verify_readme.py catches unregistered numeric tokens
==============================================================

Mutation gate: inject a scientific-notation token (4.7×10⁻⁶) into a fixture
README *outside* any CLAIM block and assert that verify_readme.py exits 2.

This is a pure filesystem mutation test — no network, no pipeline imports.
The fixture is a minimal synthetic README string written to a temp file.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import the functions under test from scripts/
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from verify_readme import (  # noqa: E402
    scan_readme_for_unregistered_numerics,
    main as verify_main,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CLEAN_README = textwrap.dedent(
    """\
    # Falsifier

    This is a clean README with no bare scientific numbers.

    <!-- CLAIM:kepler10b_period_days -->
    Kepler-10b published period (Batalha et al. 2011): 0.83749070 days
    <!-- /CLAIM:kepler10b_period_days -->

    Some prose that references the period but uses only the CLAIM block above.
    """
)

_MUTANT_README = textwrap.dedent(
    """\
    # Falsifier

    Kepler-10b period recovered to 3.14e-05 days — this number is OUTSIDE a CLAIM block.

    <!-- CLAIM:kepler10b_period_days -->
    Kepler-10b published period (Batalha et al. 2011): 0.83749070 days
    <!-- /CLAIM:kepler10b_period_days -->

    More prose below.
    """
)


# ---------------------------------------------------------------------------
# Unit-level tests (call scan function directly)
# ---------------------------------------------------------------------------


class TestScanFunction:
    """Direct unit tests of scan_readme_for_unregistered_numerics()."""

    def test_clean_readme_returns_no_errors(self, tmp_path: Path):
        """A README with all numerics inside CLAIM blocks produces no scan errors."""
        readme = tmp_path / "README.md"
        readme.write_text(_CLEAN_README, encoding="utf-8")
        errors = scan_readme_for_unregistered_numerics(_CLEAN_README, readme)
        assert errors == [], (
            f"Expected no errors for clean README, got: {errors}"
        )

    def test_mutant_readme_detects_sci_notation(self, tmp_path: Path):
        """
        Mutation: inject '3.14e-05' (scientific notation) outside a CLAIM block.
        The scanner must return at least one error mentioning this token.

        Note: the canonical mutation example '4.7×10⁻⁶' is in _NUMERIC_ALLOWLIST
        because it appears in the Proven Gates table as a gate descriptor.  This
        test uses a different unregistered token to avoid the allowlist.
        """
        readme = tmp_path / "README.md"
        readme.write_text(_MUTANT_README, encoding="utf-8")
        errors = scan_readme_for_unregistered_numerics(_MUTANT_README, readme)
        assert errors, (
            "Scanner returned no errors for a README containing '3.14e-05' "
            "outside a CLAIM block.  The gate did not fire."
        )
        # At least one error message must reference the injected token
        combined = "\n".join(errors)
        assert "3.14e-05" in combined or "3.14" in combined, (
            f"Scanner produced errors but none mention the injected token.\n"
            f"Errors: {errors}"
        )

    def test_error_message_includes_line_number(self, tmp_path: Path):
        """Error message must include the file path and line number."""
        readme = tmp_path / "README.md"
        readme.write_text(_MUTANT_README, encoding="utf-8")
        errors = scan_readme_for_unregistered_numerics(_MUTANT_README, readme)
        assert errors, "Scanner returned no errors (prerequisite for this test)"
        first_error = errors[0]
        # Format: <path>:<line>: unregistered numeric token '<token>'
        assert ":" in first_error, (
            f"Error message does not contain a colon (expected 'file:line: ...'):\n"
            f"  {first_error!r}"
        )
        assert "unregistered numeric token" in first_error, (
            f"Error message does not include the expected phrase:\n"
            f"  {first_error!r}"
        )


# ---------------------------------------------------------------------------
# Integration-level test (call main() entry point)
# ---------------------------------------------------------------------------


class TestMainExitCode:
    """Integration tests: verify that main() returns the correct exit code."""

    def test_clean_readme_exits_zero(self, tmp_path: Path, monkeypatch):
        """
        A minimal README with no unregistered numerics should exit 0.

        This test uses a fixture README that has no CLAIM blocks at all
        (and no numeric tokens that would trip the scanner), so it exercises
        the scanner without needing to wire up the full CLAIM_REGISTRY.
        """
        readme = tmp_path / "README.md"
        # Write a README with no CLAIM blocks AND no bare float/sci-notation tokens
        readme.write_text(
            "# Test\n\nThis README has no numeric scientific claims.\n",
            encoding="utf-8",
        )
        # Patch CLAIM_REGISTRY to empty so the claim-check pass is a no-op
        import verify_readme as vr
        monkeypatch.setattr(vr, "CLAIM_REGISTRY", {})
        exit_code = verify_main(["--readme", str(readme)])
        assert exit_code == 0, f"Expected exit 0 for clean README, got {exit_code}"

    def test_mutant_readme_exits_two(self, tmp_path: Path, monkeypatch):
        """
        Mutation gate: a README with '3.14e-05' outside a CLAIM block → exit 2.

        This is the core mutation gate.  The injected token must be detected
        and the script must exit 2 (unregistered numeric), not 0 or 1.

        Note: the canonical demonstration uses '4.7×10⁻⁶' in docs/PROVEN_GATES.md
        Gate 8, but that token is in _NUMERIC_ALLOWLIST for the gate descriptor row.
        This test uses '3.14e-05' which is not in the allowlist.
        """
        readme = tmp_path / "README.md"
        readme.write_text(_MUTANT_README, encoding="utf-8")

        # Patch CLAIM_REGISTRY to empty so the claim-check pass is a no-op;
        # we are testing only the numeric-scan pass here.
        import verify_readme as vr
        monkeypatch.setattr(vr, "CLAIM_REGISTRY", {})

        exit_code = verify_main(["--readme", str(readme)])
        assert exit_code == 2, (
            f"Expected exit code 2 for README with unregistered '3.14e-05', "
            f"got {exit_code}.  The mutation gate did not fire."
        )
