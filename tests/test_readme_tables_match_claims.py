"""
tests/test_readme_tables_match_claims.py

Bidirectional gate: the README gate-summary table row count must equal the integer
value in the CLAIM:n_proven_gates block.

Fails in TWO directions:
  (a) A gate row is deleted from the table → row count drops below CLAIM value.
  (b) The CLAIM block is hand-edited to a wrong number → CLAIM value diverges
      from the live _regen_n_proven_gates() count (caught by verify_readme.py --strict),
      AND it diverges from the prose table here (caught by this test).

No falsifier import. No network. Pure stdlib.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_README = _REPO_ROOT / "README.md"
_PROVEN_GATES_DOC = _REPO_ROOT / "docs" / "PROVEN_GATES.md"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLAIM_BLOCK_RE = re.compile(
    r"<!--\s*CLAIM:(?P<name>\w+)\s*-->\n"
    r"(?P<content>[^\n]*)\n"
    r"<!--\s*/CLAIM:(?P=name)\s*-->",
    re.MULTILINE,
)


def _parse_claim_integer(readme_text: str, claim_name: str) -> int:
    """Return the integer embedded in a CLAIM block, e.g. '...7...' → 7."""
    for m in _CLAIM_BLOCK_RE.finditer(readme_text):
        if m.group("name") == claim_name:
            content = m.group("content")
            numbers = re.findall(r"\d+", content)
            if not numbers:
                raise ValueError(
                    f"CLAIM:{claim_name} block contains no integer: {content!r}"
                )
            return int(numbers[0])
    raise KeyError(f"CLAIM:{claim_name} not found in README.md")


def _count_gate_table_rows(readme_text: str) -> int:
    """
    Count data rows in the README gate-summary table.

    The table is identified by its header line containing 'Gate' and 'What it catches'.
    Data rows are pipe-delimited lines that are NOT the header or separator rows.
    """
    in_table = False
    data_rows = 0
    for line in readme_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue
        # Detect the header row of the gate-summary table
        if "Gate" in stripped and "What it catches" in stripped:
            in_table = True
            continue
        if in_table:
            # Skip the separator row (|---|---|...)
            if re.match(r"^\|[-| :]+\|$", stripped):
                continue
            # Count non-empty data rows
            if stripped != "|":
                data_rows += 1
    return data_rows


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_gate_table_row_count_equals_n_proven_gates_claim() -> None:
    """
    The README gate-summary table must have exactly as many data rows as the
    integer in CLAIM:n_proven_gates.

    Fails if a row is deleted from the table (row count < claim).
    Fails if the CLAIM is hand-edited upward (claim > row count).
    """
    readme_text = _README.read_text(encoding="utf-8")

    claim_value = _parse_claim_integer(readme_text, "n_proven_gates")
    table_rows = _count_gate_table_rows(readme_text)

    assert table_rows == claim_value, (
        f"README gate-summary table has {table_rows} data row(s), "
        f"but CLAIM:n_proven_gates says {claim_value}.\n"
        f"Either a row was deleted from the table (add it back), "
        f"or CLAIM:n_proven_gates was hand-edited (revert it — "
        f"the value must come from _regen_n_proven_gates() via verify_readme.py)."
    )

def test_period_recovery_multiplier_matches_constants() -> None:
    """
    The multiplier claimed in README.md prose (e.g. "19× tighter than the 1e-4 day tolerance")
    must equal round(PERIOD_TOLERANCE_DAYS / |RECOVERED_PERIOD_DAYS - KEPLER10B_PERIOD_DAYS|).

    Source of truth: tests/test_kepler10_recovery.py constants.
    Prose text searched in README.md.

    This test fires if the README prose is manually edited to a stale or invented number.
    """
    import re
    from pathlib import Path

    repo_root = Path(__file__).parent.parent
    test_file = repo_root / "tests" / "test_kepler10_recovery.py"
    readme_file = repo_root / "README.md"

    test_text = test_file.read_text(encoding="utf-8")
    readme_text = readme_file.read_text(encoding="utf-8")

    # Extract constants from the test file
    m_rec = re.search(r'RECOVERED_PERIOD_DAYS\s*=\s*([0-9.]+)', test_text)
    m_pub = re.search(r'KEPLER10B_PERIOD_DAYS\s*=\s*([0-9.]+)', test_text)
    m_tol = re.search(r'PERIOD_TOLERANCE_DAYS\s*=\s*([0-9eE+\-\.]+)', test_text)
    assert m_rec, "RECOVERED_PERIOD_DAYS not found in test_kepler10_recovery.py"
    assert m_pub, "KEPLER10B_PERIOD_DAYS not found in test_kepler10_recovery.py"
    assert m_tol, "PERIOD_TOLERANCE_DAYS not found in test_kepler10_recovery.py"

    rec = float(m_rec.group(1))
    pub = float(m_pub.group(1))
    tol = float(m_tol.group(1))
    expected_mult = round(tol / abs(rec - pub))

    # Find the prose multiplier in README.md — look for "N× tighter than the 1e-4 day tolerance"
    m_prose = re.search(r'(\d+)×\s+tighter\s+than\s+the\s+1e-4\s+day\s+tolerance', readme_text)
    assert m_prose, (
        "README.md does not contain the expected 'N× tighter than the 1e-4 day tolerance' prose. "
        "Add or restore the prose in the 'Why this distribution produces accurate results' section."
    )
    actual_mult = int(m_prose.group(1))

    assert actual_mult == expected_mult, (
        f"README.md multiplier ({actual_mult}×) does not match the value computed from "
        f"test_kepler10_recovery.py constants ({expected_mult}×).\n"
        f"  PERIOD_TOLERANCE_DAYS      = {tol}\n"
        f"  RECOVERED_PERIOD_DAYS      = {rec}\n"
        f"  KEPLER10B_PERIOD_DAYS      = {pub}\n"
        f"  |Δ|                        = {abs(rec - pub):.2e} days\n"
        f"  round(tol / |Δ|)           = {expected_mult}\n"
        "Update the README prose to match this computed value. "
        "Do not hand-edit the constant files."
    )

