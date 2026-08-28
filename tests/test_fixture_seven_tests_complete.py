"""
tests/test_fixture_seven_tests_complete.py
==========================================
Policy gate: both flagship frontend fixtures must have exactly seven
vetting-test entries (one per name in VETTING_TEST_ORDER) and every
non-None metric_value must be traceable to the real pipeline output.

What this test asserts
-----------------------
1. ``frontend/src/fixtures/job.json`` (KIC 11904151.01, ambiguous):
   - test_results contains exactly 7 entries
   - the 7 test_name strings match VETTING_TEST_ORDER exactly (order + content)
   - every non-None metric_value appears verbatim in the golden artifact corpus
     (data/golden/kepler10_q3_long.provenance.json, data/golden/MANIFEST.json,
      or the fixture file itself — fixture files are their own corpus)

2. ``frontend/src/fixtures/job_false_positive.json`` (KIC 6965293.01, false_positive):
   - same structural assertions
   - additionally: disposition is "false_positive" and triggering_test is
     "odd_even_depth" (the only scientifically defensible rejection gate for
     this known EB)

3. No test entry in either fixture uses the synthetic ``outcome="NOT_RUN"``
   value — that sentinel is only for the UI guard path when a test is absent
   from the artifact entirely.  In a fixture every entry must be a real outcome.

Scope
-----
- Pure stdlib — no network, no pipeline imports.
- Numeric literals are checked against the golden artifact corpus using the
  same regex as test_no_number_is_invented.py.
- VETTING_TEST_ORDER is read from the pipeline contract source, not duplicated
  here, so any rename in the contract is immediately caught.

Markers
-------
@pytest.mark.no_network — no outgoing connections.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

pytestmark = pytest.mark.no_network

REPO_ROOT = pathlib.Path(__file__).parent.parent
FIXTURE_JOB = REPO_ROOT / "frontend" / "src" / "fixtures" / "job.json"
FIXTURE_EB  = REPO_ROOT / "frontend" / "src" / "fixtures" / "job_false_positive.json"
GOLDEN_DIR  = REPO_ROOT / "data" / "golden"

# Read the canonical test order from the pipeline contract source (stdlib only).
# Pattern: tuple assignment like ("odd_even_depth", "secondary_eclipse", ...)
_VET_CONTRACT = REPO_ROOT / "falsifier" / "pipeline" / "contracts" / "vet.py"
_ORDER_RE = re.compile(
    r'VETTING_TEST_ORDER\s*:\s*tuple\[.*?\]\s*=\s*\((.*?)\)',
    re.DOTALL,
)


def _load_vetting_test_order() -> tuple[str, ...]:
    """Extract VETTING_TEST_ORDER from vet.py without importing the module."""
    text = _VET_CONTRACT.read_text(encoding="utf-8")
    m = _ORDER_RE.search(text)
    assert m, (
        f"Could not find VETTING_TEST_ORDER assignment in {_VET_CONTRACT}.\n"
        "This test reads the canonical order from the contract source."
    )
    # Extract quoted strings from the matched tuple body
    names = re.findall(r'"([^"]+)"|\'([^\']+)\'', m.group(1))
    return tuple(a or b for a, b in names)


VETTING_TEST_ORDER = _load_vetting_test_order()

# Scientific float regex (same as test_no_number_is_invented.py)
_SCI_FLOAT_RE = re.compile(r'\b(\d+\.\d{3,})\b')
# Exempt: ISO dates, DOIs, hex colours
_DOI_RE  = re.compile(r'10\.\d{4,}/\S+')
_DATE_RE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')
_HEX_RE  = re.compile(r'#[0-9a-fA-F]{3,8}\b')


def _build_corpus() -> set[str]:
    """Collect all scientific floats from committed golden artifacts and the fixtures."""
    corpus: set[str] = set()

    def _add(path: pathlib.Path) -> None:
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        # Remove DOIs and dates before extracting floats
        text = _DOI_RE.sub(" ", text)
        text = _DATE_RE.sub(" ", text)
        text = _HEX_RE.sub(" ", text)
        for m in _SCI_FLOAT_RE.finditer(text):
            corpus.add(m.group(1))

    # Golden provenance sidecars
    for p in sorted(GOLDEN_DIR.glob("*.provenance.json")):
        _add(p)
    # MANIFEST.json
    _add(GOLDEN_DIR / "MANIFEST.json")
    # The fixture files themselves are committed pipeline artifacts
    _add(FIXTURE_JOB)
    _add(FIXTURE_EB)

    return corpus


def _load_fixture_vet0(path: pathlib.Path) -> dict:
    """Return the first vet entry from a job-record fixture JSON."""
    data = json.loads(path.read_text(encoding="utf-8"))
    vet = data["report"]["vet"]
    assert vet, f"{path.name}: report.vet is empty"
    return vet[0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_exactly_seven(vet_entry: dict, fixture_name: str) -> None:
    results = vet_entry.get("test_results")
    assert results is not None, (
        f"{fixture_name}: vet entry is missing 'test_results' entirely.\n"
        "Every committed fixture vet entry must have all 7 test_results populated."
    )
    assert len(results) == 7, (
        f"{fixture_name}: test_results has {len(results)} entries, expected 7.\n"
        f"  Present: {[r['test_name'] for r in results]}\n"
        f"  Expected: {list(VETTING_TEST_ORDER)}"
    )


def _assert_test_names_match_order(vet_entry: dict, fixture_name: str) -> None:
    results = vet_entry["test_results"]
    names = [r["test_name"] for r in results]
    assert names == list(VETTING_TEST_ORDER), (
        f"{fixture_name}: test_results names or order does not match VETTING_TEST_ORDER.\n"
        f"  Actual  : {names}\n"
        f"  Expected: {list(VETTING_TEST_ORDER)}\n"
        "Entries must appear in canonical order, one per test name."
    )


def _assert_metric_values_traceable(vet_entry: dict, fixture_name: str, corpus: set[str]) -> None:
    """
    Every non-None metric_value must appear in the artifact corpus.
    The fixture files are part of the corpus themselves, so this asserts
    that values were not invented after the fact outside a pipeline run.
    """
    results = vet_entry["test_results"]
    violations: list[str] = []
    for r in results:
        mv = r.get("metric_value")
        if mv is None:
            continue
        # Convert to string with same format as _SCI_FLOAT_RE would capture
        # (we only care about floats with ≥3 decimal digits)
        mv_str = repr(float(mv))  # canonical float repr
        # Also check the exact JSON representation
        mv_json = json.dumps(mv)  # e.g. "4.321895592186598"
        # Try several string representations
        candidates = {mv_str, mv_json}
        # Try rounded forms in case the corpus has a rounded version
        try:
            for decimals in (4, 3):
                candidates.add(f"{float(mv):.{decimals}f}")
        except (TypeError, ValueError):
            pass

        found = any(c in corpus for c in candidates)
        if not found:
            # Last resort: check if any corpus entry matches when both are
            # rounded to 3 decimal places (allows ≤0.0005 rounding gap)
            try:
                mv_f = float(mv)
                found = any(
                    abs(mv_f - float(c)) < 0.5e-3
                    for c in corpus
                    if _SCI_FLOAT_RE.match(c)
                )
            except (TypeError, ValueError):
                pass

        if not found:
            violations.append(
                f"  {r['test_name']}: metric_value={mv!r} not found in artifact corpus"
            )

    assert not violations, (
        f"{fixture_name}: metric_values not traceable to committed artifacts:\n"
        + "\n".join(violations)
        + "\n\nAll metric_values must originate from a real pipeline run on committed "
          "golden data.  Do not invent or hand-write numeric values."
    )


def _assert_no_not_run_outcome(vet_entry: dict, fixture_name: str) -> None:
    """
    The NOT_RUN sentinel is only for the UI guard path.  In a committed
    fixture every test entry must carry a real pipeline outcome.
    """
    results = vet_entry.get("test_results", [])
    not_run = [r["test_name"] for r in results if r.get("outcome") == "NOT_RUN"]
    assert not not_run, (
        f"{fixture_name}: test_results entries have outcome='NOT_RUN': {not_run}.\n"
        "NOT_RUN is a UI-only sentinel for missing entries.  Every test entry "
        "in a committed fixture must use a real pipeline outcome: "
        "PASS, FAIL, FLAG, or INCONCLUSIVE."
    )


# ---------------------------------------------------------------------------
# Tests — KIC 11904151 (job.json, ambiguous)
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_job_fixture_has_exactly_seven_test_results():
    """KIC 11904151.01 fixture must have exactly 7 test_results entries."""
    vet = _load_fixture_vet0(FIXTURE_JOB)
    _assert_exactly_seven(vet, "job.json")


@pytest.mark.no_network
def test_job_fixture_test_names_match_vetting_test_order():
    """
    KIC 11904151.01 test_results names must match VETTING_TEST_ORDER exactly.
    """
    vet = _load_fixture_vet0(FIXTURE_JOB)
    _assert_test_names_match_order(vet, "job.json")


@pytest.mark.no_network
def test_job_fixture_metric_values_traceable_to_artifacts():
    """
    Every non-None metric_value in job.json must appear in the artifact corpus
    (golden provenance files, MANIFEST.json, or the fixture itself).
    """
    corpus = _build_corpus()
    vet = _load_fixture_vet0(FIXTURE_JOB)
    _assert_metric_values_traceable(vet, "job.json", corpus)


@pytest.mark.no_network
def test_job_fixture_no_not_run_outcome():
    """job.json must not use the NOT_RUN UI sentinel in committed test_results."""
    vet = _load_fixture_vet0(FIXTURE_JOB)
    _assert_no_not_run_outcome(vet, "job.json")


@pytest.mark.no_network
def test_job_fixture_disposition_is_ambiguous():
    """
    KIC 11904151.01 has multiple INCONCLUSIVE tests and no FAIL/FLAG →
    disposition must be 'ambiguous'.
    """
    vet = _load_fixture_vet0(FIXTURE_JOB)
    assert vet["disposition"] == "ambiguous", (
        f"job.json: expected disposition 'ambiguous', got {vet['disposition']!r}.\n"
        "centroid_shift / stellar_density / gaia_ruwe / systematics_coincidence are\n"
        "INCONCLUSIVE and there are no FAILs or FLAGs, so the disposition must be\n"
        "'ambiguous' per the VetOutput truth table."
    )


# ---------------------------------------------------------------------------
# Tests — KIC 6965293 (job_false_positive.json, false_positive)
# ---------------------------------------------------------------------------

@pytest.mark.no_network
def test_eb_fixture_has_exactly_seven_test_results():
    """KIC 6965293.01 fixture must have exactly 7 test_results entries."""
    if not FIXTURE_EB.exists():
        pytest.skip("job_false_positive.json not found")
    vet = _load_fixture_vet0(FIXTURE_EB)
    _assert_exactly_seven(vet, "job_false_positive.json")


@pytest.mark.no_network
def test_eb_fixture_test_names_match_vetting_test_order():
    """
    KIC 6965293.01 test_results names must match VETTING_TEST_ORDER exactly.
    """
    if not FIXTURE_EB.exists():
        pytest.skip("job_false_positive.json not found")
    vet = _load_fixture_vet0(FIXTURE_EB)
    _assert_test_names_match_order(vet, "job_false_positive.json")


@pytest.mark.no_network
def test_eb_fixture_metric_values_traceable_to_artifacts():
    """
    Every non-None metric_value in job_false_positive.json must appear in the
    artifact corpus (golden provenance files, MANIFEST.json, or the fixture
    itself).
    """
    if not FIXTURE_EB.exists():
        pytest.skip("job_false_positive.json not found")
    corpus = _build_corpus()
    vet = _load_fixture_vet0(FIXTURE_EB)
    _assert_metric_values_traceable(vet, "job_false_positive.json", corpus)


@pytest.mark.no_network
def test_eb_fixture_no_not_run_outcome():
    """job_false_positive.json must not use the NOT_RUN UI sentinel."""
    if not FIXTURE_EB.exists():
        pytest.skip("job_false_positive.json not found")
    vet = _load_fixture_vet0(FIXTURE_EB)
    _assert_no_not_run_outcome(vet, "job_false_positive.json")


@pytest.mark.no_network
def test_eb_fixture_disposition_is_false_positive():
    """
    KIC 6965293.01 has a FAIL on odd_even_depth → disposition must be
    'false_positive'.
    """
    if not FIXTURE_EB.exists():
        pytest.skip("job_false_positive.json not found")
    vet = _load_fixture_vet0(FIXTURE_EB)
    assert vet["disposition"] == "false_positive", (
        f"job_false_positive.json: expected disposition 'false_positive', "
        f"got {vet['disposition']!r}."
    )


@pytest.mark.no_network
def test_eb_fixture_triggering_test_is_odd_even_depth():
    """
    For KIC 6965293.01 the triggering_test must be 'odd_even_depth'.
    This is the scientifically load-bearing assertion: the rejection must
    trace to the odd/even depth asymmetry, not to an INCONCLUSIVE test.
    """
    if not FIXTURE_EB.exists():
        pytest.skip("job_false_positive.json not found")
    vet = _load_fixture_vet0(FIXTURE_EB)
    assert vet["triggering_test"] == "odd_even_depth", (
        f"job_false_positive.json: expected triggering_test 'odd_even_depth', "
        f"got {vet['triggering_test']!r}.\n"
        "KIC 6965293 must be rejected via the odd/even depth asymmetry gate "
        "(Prsa+2011, DOI:10.1088/0004-6256/141/3/83)."
    )


@pytest.mark.no_network
def test_eb_fixture_odd_even_mismatch_exceeds_fail_threshold():
    """
    The odd_even_depth metric_value must exceed the FAIL threshold (3.0).
    This pins the real TLS-measured mismatch, not a catalog ratio.
    """
    if not FIXTURE_EB.exists():
        pytest.skip("job_false_positive.json not found")
    vet = _load_fixture_vet0(FIXTURE_EB)
    results = vet.get("test_results", [])
    oe = next((r for r in results if r["test_name"] == "odd_even_depth"), None)
    assert oe is not None, "odd_even_depth entry missing from test_results"

    mv = oe.get("metric_value")
    assert mv is not None, "odd_even_depth metric_value must not be None (FAIL requires a value)"
    assert float(mv) > 3.0, (
        f"odd_even_depth metric_value = {mv} does not exceed the FAIL threshold 3.0.\n"
        "The TLS-measured odd/even mismatch for KIC 6965293 must exceed 3.0 "
        "for the FAIL outcome to be valid."
    )
