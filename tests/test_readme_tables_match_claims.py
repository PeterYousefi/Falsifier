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
