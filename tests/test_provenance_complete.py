"""
tests/test_provenance_complete.py
===================================
Provenance completeness audit — standard library and json only, no network.

Walks every JSON sidecar in data/golden/ and the ingest cache (if present)
and asserts that none is missing:

  - source_doi / reference_doi  (non-empty string)
  - access_date                 (ISO-8601 date string)
  - row_count                   (positive integer)
  - source_url / mast_uri       (non-empty string for FITS artifacts)

Also walks every *.provenance.json file in data/golden/ and applies the
same checks.

This test is the enforcement point for AGENTS.md Rule 3:
  "Every ingested dataset records source DOI, access date, and row count
   in its manifest."

Implementation constraints
--------------------------
  - Standard library + json only.  No third-party imports.
  - No network access.
  - No imports from falsifier (so the test runs even before the package
    is installable).
"""

import datetime
import json
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent

# Directories that contain sidecar manifests
SIDECAR_DIRS = [
    REPO_ROOT / "data" / "golden",
    # Cache dir (may not exist before first ingest run)
    pathlib.Path.home() / ".falsifier" / "cache" / "ingest",
]

# Patterns for sidecar files
SIDECAR_GLOB_PATTERNS = [
    "**/*.manifest.json",   # cache sidecars
    "**/*.provenance.json", # golden file sidecars
]

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_sidecars() -> list[pathlib.Path]:
    """Find all sidecar JSON files in configured directories."""
    sidecars: list[pathlib.Path] = []
    for base_dir in SIDECAR_DIRS:
        if not base_dir.exists():
            continue
        for pattern in SIDECAR_GLOB_PATTERNS:
            sidecars.extend(base_dir.glob(pattern))
    return sorted(set(sidecars))


def _is_fits_sidecar(path: pathlib.Path) -> bool:
    """Return True if this sidecar likely describes a FITS artifact."""
    stem = path.name
    # cache sidecars: <hash>.fits.manifest.json
    # golden sidecars: <name>.provenance.json in data/golden/
    return ".fits" in stem or path.parent.name == "golden"


def _validate_sidecar(path: pathlib.Path) -> list[str]:
    """
    Load a sidecar JSON and return a list of field-level violation messages.
    Empty list means the sidecar is compliant.
    """
    violations: list[str] = []

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        return [f"Invalid JSON: {exc}"]

    # Detect pre-fetch sentinel — SHA-256 not yet filled in
    sha = data.get("sha256", "")
    is_prefetch_sentinel = sha == "__FILL_AFTER_FETCH__"

    # 1. source_doi — non-empty string.
    # Accept "source_doi" (cache sidecars) or "reference_doi"
    # (golden provenance sidecars, which use the manifest schema).
    doi = data.get("source_doi") or data.get("reference_doi", "")
    if not isinstance(doi, str) or not doi.strip():
        violations.append(
            "source_doi (or reference_doi) is missing or empty (AGENTS.md Rule 3)"
        )

    # 2. access_date — ISO-8601 date string
    access_date = data.get("access_date", "")
    if not isinstance(access_date, str) or not ISO_DATE_RE.match(access_date):
        violations.append(
            f"access_date is missing or not ISO-8601 date: {access_date!r}"
        )
    else:
        try:
            datetime.date.fromisoformat(access_date)
        except ValueError:
            violations.append(f"access_date is not a valid date: {access_date!r}")

    # 3. row_count — positive integer (skip for pre-fetch sentinels)
    if not is_prefetch_sentinel:
        row_count = data.get("row_count")
        if not isinstance(row_count, int) or row_count < 1:
            violations.append(
                f"row_count is missing or not a positive integer: {row_count!r}"
            )

    # 4. source_url / mast_uri — non-empty for FITS sidecars (skip sentinels)
    if _is_fits_sidecar(path) and not is_prefetch_sentinel:
        source_url = data.get("source_url") or data.get("mast_uri", "")
        if not isinstance(source_url, str) or not source_url.strip():
            violations.append(
                "source_url (or mast_uri) is missing or empty for FITS artifact sidecar"
            )

    return violations


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_provenance_sidecars_exist_for_golden_files():
    """
    Every committed golden FITS file must have a provenance sidecar.

    Structural check only — does not require the SHA-256 to be filled.
    """
    golden_dir = REPO_ROOT / "data" / "golden"
    if not golden_dir.exists():
        pytest.skip("data/golden/ does not exist yet")

    fits_files = list(golden_dir.glob("*.fits"))
    if not fits_files:
        pytest.skip("No .fits files in data/golden/ yet")

    missing_sidecars: list[str] = []
    for fits_path in fits_files:
        # Sidecar naming: foo.fits → foo.provenance.json
        prov_path = fits_path.parent / (fits_path.stem + ".provenance.json")
        if not prov_path.exists():
            missing_sidecars.append(fits_path.name)

    assert not missing_sidecars, (
        "FITS files without provenance sidecars:\n"
        + "\n".join(f"  {f}" for f in missing_sidecars)
        + "\nEach .fits file must have a <stem>.provenance.json sidecar."
    )


@pytest.mark.no_network
def test_all_sidecars_have_required_provenance_fields():
    """
    Every sidecar in data/golden/ and the ingest cache must contain
    source_doi, access_date (ISO-8601), and row_count (positive int).

    This is the enforcement point for AGENTS.md Rule 3.
    """
    sidecars = _collect_sidecars()

    if not sidecars:
        pytest.skip("No sidecar files found yet (golden files not committed)")

    failures: dict[str, list[str]] = {}
    for sidecar_path in sidecars:
        violations = _validate_sidecar(sidecar_path)
        if violations:
            # Use relative path when possible, absolute otherwise
            try:
                key = str(sidecar_path.relative_to(REPO_ROOT))
            except ValueError:
                key = str(sidecar_path)
            failures[key] = violations

    if failures:
        lines = ["Provenance violations found (AGENTS.md Rule 3):"]
        for file_path, viols in sorted(failures.items()):
            lines.append(f"\n  {file_path}:")
            for v in viols:
                lines.append(f"    - {v}")
        pytest.fail("\n".join(lines))


@pytest.mark.no_network
def test_manifest_json_in_golden_is_valid():
    """The golden MANIFEST.json must be valid JSON with required top-level keys."""
    manifest_path = REPO_ROOT / "data" / "golden" / "MANIFEST.json"
    if not manifest_path.exists():
        pytest.skip("data/golden/MANIFEST.json not found")

    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)

    assert "golden_set" in data, "MANIFEST.json must have a 'golden_set' key"
    assert isinstance(data["golden_set"], list), "'golden_set' must be a list"

    required_entry_keys = {
        "kic_id", "fits_filename", "provenance_filename",
        "reference_doi", "mast_product_id",
    }
    for i, entry in enumerate(data["golden_set"]):
        missing = required_entry_keys - set(entry.keys())
        assert not missing, (
            f"golden_set[{i}] (kic_id={entry.get('kic_id', '?')!r}) "
            f"is missing keys: {missing}"
        )


@pytest.mark.no_network
def test_no_retired_tap_table_sql_in_codebase():
    """
    Scan all .py files under falsifier/ for SQL FROM/JOIN references to
    retired TAP tables.  Retired table names appearing in comments and
    docstrings are acceptable (they explain the policy); only SQL usage is
    flagged.

    Matches: ``FROM exoplanet``, ``JOIN exomultpars``, etc. (case-insensitive).

    Opt-out: add ``# retired-table-ref-ok`` to a line to suppress the check
    for that line (used in the guard code itself in sources/tap.py).
    """
    falsifier_dir = REPO_ROOT / "falsifier"
    if not falsifier_dir.exists():
        pytest.skip("falsifier/ package not found")

    # Only match actual SQL FROM/JOIN syntax, not bare mentions in comments
    RETIRED_SQL_RE = re.compile(
        r"\b(FROM|JOIN)\s+(exoplanet|exomultpars|compositepars)\b",
        re.IGNORECASE,
    )
    EXCEPTION_MARKER = "# retired-table-ref-ok"

    violations: list[str] = []
    for py_file in sorted(falsifier_dir.rglob("*.py")):
        with open(py_file, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if EXCEPTION_MARKER in line:
                    continue
                if RETIRED_SQL_RE.search(line):
                    violations.append(
                        f"{py_file.relative_to(REPO_ROOT)}:{lineno}: {line.rstrip()}"
                    )

    assert not violations, (
        "SQL queries referencing retired TAP tables found in codebase:\n"
        + "\n".join(f"  {v}" for v in violations)
        + "\nUse 'ps' or 'pscomppars' instead."
    )
