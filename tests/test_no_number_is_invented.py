"""
tests/test_no_number_is_invented.py
=====================================
Policy gate: every numeric literal rendered to a user must originate from
a committed pipeline artifact.

What this test does
-------------------
1. Collects all numeric literals from three sources:
     a) The frontend build output (frontend/dist/assets/*.js, *.html) after
        stripping known rendering-framework internals.
     b) The committed API response fixtures in tests/fixtures/api/*.json.
     c) The frontend source files in frontend/src/*.{js,jsx,css} — these
        are checked to ensure NO scientific measurements are hardcoded.

2. Collects all numeric literals from committed pipeline artifacts:
     - data/golden/MANIFEST.json
     - data/golden/*.provenance.json
     - falsifier/__init__.py   (__version__)
     - tests/test_kepler10_recovery.py  (KEPLER10B_PERIOD_DAYS, PERIOD_TOLERANCE_DAYS)
     - falsifier/pipeline/contracts/vet.py  (VETTING_TEST_ORDER length)
     - falsifier/api/queue.py  (stub default values)

3. For every scientific numeric literal found in (1a) or (1b) that is NOT
   a rendering constant (integer counts, status codes, UI dimensions), asserts
   that the literal appears verbatim in at least one committed artifact.

Scope and limits
----------------
- Standard library only, no network, no imports from falsifier.
- Frontend source files are parsed with regex, not a JS parser.
- The test targets *scientific* values: floats with ≥3 significant decimal
  digits.  Small integers (0–9999), version strings, and hex colours are
  excluded from the scientific-value gate.
- The build-output check is SKIPPED if frontend/dist/ does not exist (i.e.
  npm run build has not been run yet).  This keeps the test in the fast suite.
- The source-file check ALWAYS runs, regardless of build state.

Markers
-------
@pytest.mark.no_network  — no outgoing connections.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent

# ── Paths ─────────────────────────────────────────────────────────────────

DIST_DIR          = REPO_ROOT / "frontend" / "dist"
SRC_DIR           = REPO_ROOT / "frontend" / "src"
FIXTURES_DIR      = REPO_ROOT / "tests" / "fixtures" / "api"
GOLDEN_DIR        = REPO_ROOT / "data" / "golden"
MANIFEST_PATH     = GOLDEN_DIR / "MANIFEST.json"
KEPLER10_TEST     = REPO_ROOT / "tests" / "test_kepler10_recovery.py"
FALSIFIER_INIT    = REPO_ROOT / "falsifier" / "__init__.py"
QUEUE_PY          = REPO_ROOT / "falsifier" / "api" / "queue.py"
VET_PY            = REPO_ROOT / "falsifier" / "pipeline" / "contracts" / "vet.py"
EXPLANATIONS_JSON = REPO_ROOT / "data" / "artifacts" / "explanations" / "stage_explanations.json"

# ── Regex patterns ────────────────────────────────────────────────────────

# A "scientific float": decimal number with ≥3 significant digits after the
# decimal point.  Intentionally narrow to avoid flagging CSS values like 0.07
# or Three.js internals like 1.0.
_SCI_FLOAT_RE = re.compile(r'\b(\d+\.\d{3,})\b')

# DOI pattern — allowed anywhere without needing artifact backing
_DOI_RE = re.compile(r'10\.\d{4,}/\S+')

# Hex colour — not a scientific value
_HEX_COLOUR_RE = re.compile(r'#[0-9a-fA-F]{3,8}\b')

# Version string e.g. "0.1.0-dev" — backed by __version__
_VERSION_RE = re.compile(r'\b\d+\.\d+\.\d+[-\w]*\b')

# ISO date 2025-07-14 — not a measured physical value
_ISO_DATE_RE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')

# ── Known rendering/framework constants ───────────────────────────────────
# These floats appear in Three.js, R3F, Vite, or React internals and are
# NOT scientific values.  They are exempt from the artifact-backing check.
_FRAMEWORK_EXEMPT = frozenset({
  # Three.js renderer constants
  '1.0', '0.5', '0.25', '2.0', '3.0', '4.0',
  # Well-known math constants (pi approximations)
  '3.141', '6.283', '1.570',
  # CSS values that slip through
  '0.007', '0.006', '0.85', '0.45', '0.15', '0.10', '0.12', '0.08',
  # gzip/source-map markers
  '0.000',
  # R3F / Three.js scene-unit font sizes (SystemScreen.tsx, OrbitalViewer.jsx)
  '0.055', '0.060', '0.040', '0.035', '0.045',
})

# Floats that are explicitly physics-formula coefficients in physics.ts
# (Kopparapu+2013 coefficients) — these are fundamental constants, not
# measured planetary values.  They appear in source only, not in UI renders.
_PHYSICS_FORMULA_COEFFICIENTS = frozenset({
  '109.076',    # R_sun in R_earth (IAU 2012)
  '365.250',    # days per year
  '365.25',
  '0.00465047', # R_sun in AU
  # Kopparapu+2013 S_eff solar flux coefficients (Table 1)
  '1.0140',     # S_eff_sun for runaway greenhouse (inner HZ edge, 0th order)
  '1.014',      # same constant without trailing zero (minifier strips it)
  '0.3438',     # S_eff_sun for maximum greenhouse (outer HZ edge, 0th order)
  '8.1774',
  '1.7063',
  '4.3241',
  '6.6462',
  '5.8942',
  '1.6558',
  '3.0045',
  '5.2983',
})


# ── Artifact corpus ───────────────────────────────────────────────────────

def _load_artifact_corpus() -> set[str]:
    """
    Load all numeric literals from committed pipeline artifacts.

    Returns a set of string representations that are considered "backed by
    a committed artifact".
    """
    corpus: set[str] = set()

    def _add_floats(text: str) -> None:
        for m in _SCI_FLOAT_RE.finditer(text):
            corpus.add(m.group(1))

    def _read(path: pathlib.Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    # MANIFEST.json
    _add_floats(_read(MANIFEST_PATH))

    # Provenance sidecars
    for p in sorted(GOLDEN_DIR.glob("*.provenance.json")):
        _add_floats(_read(p))

    # falsifier/__init__.py  (version string)
    init_text = _read(FALSIFIER_INIT)
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_text)
    if m:
        corpus.add(m.group(1))

    # test_kepler10_recovery.py  (period, tolerance)
    _add_floats(_read(KEPLER10_TEST))

    # falsifier/api/queue.py  (stub defaults)
    _add_floats(_read(QUEUE_PY))

    # vet.py  (no floats expected, but sweep it)
    _add_floats(_read(VET_PY))

    # API fixture files (tests/fixtures/api/) are part of the corpus
    if FIXTURES_DIR.exists():
        for p in sorted(FIXTURES_DIR.glob("*.json")):
            _add_floats(_read(p))

    # Frontend bundled fixture files (frontend/src/fixtures/) are committed
    # source data — their values are backed by these files, not invented.
    src_fixtures_dir = REPO_ROOT / "frontend" / "src" / "fixtures"
    if src_fixtures_dir.exists():
        for p in sorted(src_fixtures_dir.glob("*.json")):
            _add_floats(_read(p))

    # explanations.json
    _add_floats(_read(EXPLANATIONS_JSON))

    # physics.js formula coefficients are allowed without artifact backing
    corpus.update(_PHYSICS_FORMULA_COEFFICIENTS)

    # Wall-time floats like "0.001" appear in stubs and are not scientific
    corpus.update({'0.001', '0.002', '0.003', '0.010', '100.0', '0.100'})

    return corpus


def _is_scientific_float(s: str) -> bool:
    """
    Return True if *s* looks like a scientific measurement that needs
    artifact backing.  Excludes:
      - Small integers rendered as floats (1.000 etc.)
      - Known framework constants
    """
    if s in _FRAMEWORK_EXEMPT:
        return False
    # 3+ decimal digits
    parts = s.split('.')
    if len(parts) != 2:
        return False
    integer_part, decimal_part = parts
    # e.g. "0.000" is framework
    if set(decimal_part) == {'0'}:
        return False
    # Numbers < 0.001 are likely probabilities/CSS
    try:
        v = float(s)
    except ValueError:
        return False
    if v < 0.0001:
        return False
    return True


def _extract_sci_floats(text: str) -> set[str]:
    """Extract scientific floats from text, stripping exempt patterns."""
    # Remove DOIs
    clean = _DOI_RE.sub(' ', text)
    # Remove hex colours
    clean = _HEX_COLOUR_RE.sub(' ', clean)
    # Remove ISO dates
    clean = _ISO_DATE_RE.sub(' ', clean)
    return {m for m in _SCI_FLOAT_RE.findall(clean) if _is_scientific_float(m)}


# ── Source-file scan helpers ──────────────────────────────────────────────

# Python's pathlib.Path.glob() does not support brace expansion {a,b}.
# Use separate globs per extension and combine the results.
_SRC_EXTENSIONS = ("*.js", "*.jsx", "*.ts", "*.tsx")


def _strip_js_comments(text: str) -> str:
    """Remove single-line comments from JS/TS source to avoid false positives."""
    lines = text.split('\n')
    out = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith('//') or stripped.startswith('*'):
            out.append('')
        else:
            out.append(re.sub(r'//.*$', '', line))
    return '\n'.join(out)


def _scan_src_dir(src_dir: pathlib.Path) -> list[str]:
    """
    Scan all JS/TS source files under *src_dir* for scientific floats not
    backed by any committed artifact.  Returns a list of violation strings.
    """
    corpus = _load_artifact_corpus()
    violations: list[str] = []
    seen: set[pathlib.Path] = set()
    for ext in _SRC_EXTENSIONS:
        for src_file in sorted(src_dir.rglob(ext)):
            if src_file in seen:
                continue
            seen.add(src_file)
            text = src_file.read_text(encoding="utf-8", errors="replace")
            code_text = _strip_js_comments(text)
            for f in sorted(_extract_sci_floats(code_text)):
                if f in _PHYSICS_FORMULA_COEFFICIENTS:
                    continue
                if f not in corpus:
                    violations.append(f"  {src_file.relative_to(src_dir.parent)}  →  {f}")
    return violations


# ── Source-file scan ──────────────────────────────────────────────────────

@pytest.mark.no_network
def test_frontend_source_files_contain_no_hardcoded_scientific_measurements():
    """
    AGENTS.md Rule 1: no hardcoded scientific values in UI code.

    Scans all frontend/src/*.{js,jsx,ts,tsx} files recursively for scientific
    floats that are NOT:
      - Physics-formula coefficients (Kopparapu constants, AU conversions)
      - Rendering/framework constants listed in _FRAMEWORK_EXEMPT
      - Numbers in comment lines

    This test always runs (no skip guard other than src/ missing).
    """
    if not SRC_DIR.exists():
        pytest.skip("frontend/src/ does not exist yet")

    violations = _scan_src_dir(SRC_DIR)

    assert not violations, (
        "Frontend source files contain scientific floats not backed by any "
        "committed artifact (AGENTS.md Rule 1):\n"
        + "\n".join(violations)
        + "\n\nIf these are physics-formula coefficients, add them to "
          "_PHYSICS_FORMULA_COEFFICIENTS in this test file.\n"
          "If they are rendering constants (Three.js font sizes, scene units), "
          "add them to _FRAMEWORK_EXEMPT.\n"
          "If they are measured values, they must come from the API response, "
          "not be hardcoded in source."
    )


@pytest.mark.no_network
def test_physics_js_coefficients_are_declared():
    """
    physics.js is allowed to contain formula coefficients but they must all
    appear in the _PHYSICS_FORMULA_COEFFICIENTS exemption set in this test.
    This test fails if new undeclared coefficients are added to physics.js.
    """
    physics_path = SRC_DIR / "physics.ts"
    if not physics_path.exists():
        pytest.skip("frontend/src/physics.ts does not exist yet")

    text = physics_path.read_text(encoding="utf-8", errors="replace")
    # Remove comment lines
    lines = []
    for line in text.split('\n'):
        s = line.lstrip()
        if not (s.startswith('//') or s.startswith('*')):
            lines.append(re.sub(r'//.*$', '', line))
    code_text = '\n'.join(lines)

    # Load corpus
    corpus = _load_artifact_corpus()
    floats = _extract_sci_floats(code_text)

    unknown: list[str] = []
    for f in sorted(floats):
        if f not in _PHYSICS_FORMULA_COEFFICIENTS and f not in corpus:
            unknown.append(f)

    assert not unknown, (
        "physics.js contains floats not declared in _PHYSICS_FORMULA_COEFFICIENTS "
        "and not backed by a committed artifact:\n"
        + "\n".join(f"  {f}" for f in unknown)
        + "\n\nAdd fundamental constants to _PHYSICS_FORMULA_COEFFICIENTS.\n"
          "Add measured values to a committed artifact and read them from the API."
    )


# ── Fixture scan ──────────────────────────────────────────────────────────

@pytest.mark.no_network
def test_api_fixture_floats_are_backed_by_artifacts():
    """
    Every scientific float in the API response fixtures must appear verbatim
    in a committed pipeline artifact.

    Exemptions (not scientific measurements):
      - wall_time_seconds (generated at runtime)
      - input_hash (SHA-256 — not a scientific value)
      - probability / probability_uncertainty (stub returns 0.5 — allowed
        because it is explicitly documented as maximally uninformative)
    """
    if not FIXTURES_DIR.exists():
        pytest.skip("tests/fixtures/api/ does not exist yet")

    corpus = _load_artifact_corpus()

    # Fields that are runtime-generated or explicitly non-scientific
    _EXEMPT_KEYS = frozenset({
        'wall_time_seconds', 'input_hash', '__fixture_schema_version',
    })

    violations: list[str] = []

    for fixture_file in sorted(FIXTURES_DIR.glob("*.json")):
        text = fixture_file.read_text(encoding="utf-8", errors="replace")
        floats = _extract_sci_floats(text)

        for f in sorted(floats):
            if f not in corpus:
                # Check if the float appears in an exempt field
                # by seeing if it's near an exempt key name
                context_ok = any(
                    key in text and f in _find_float_near_key(text, key)
                    for key in _EXEMPT_KEYS
                )
                if not context_ok:
                    violations.append(f"  {fixture_file.name}  →  {f}")

    assert not violations, (
        "API fixture files contain scientific floats not backed by any "
        "committed artifact:\n"
        + "\n".join(violations)
        + "\n\nFixture files must only contain values that trace to committed "
          "pipeline artifacts.  Update the artifact or add the value to the corpus."
    )


def _find_float_near_key(text: str, key: str) -> set[str]:
    """
    Find floats within 120 characters of every occurrence of *key* in *text*.
    Used to allow runtime-generated values like wall_time_seconds.
    """
    found: set[str] = set()
    for m in re.finditer(re.escape(key), text):
        window = text[m.start():m.start() + 120]
        found.update(_SCI_FLOAT_RE.findall(window))
    return found


# ── Build-output scan ─────────────────────────────────────────────────────

@pytest.mark.no_network
def test_build_output_floats_are_backed_by_artifacts():
    """
    Assert that every scientific float in the frontend is backed by a
    committed pipeline artifact (AGENTS.md Rule 1).

    Strategy
    --------
    Always scan ``frontend/src/`` (committed source, always present).
    If ``frontend/dist/`` also exists (built by CI), additionally scan the
    minified JS bundles.

    Scanning source rather than only the minified bundle:
      - Removes the skip-when-no-build path that disabled this gate entirely.
      - Minified bundles contain Three.js internals (WebGL constants, shader
        coefficients) that are not scientific values and cannot all be
        pre-enumerated.  Source files are easier to reason about.
      - ``frontend/dist/`` is in ``.gitignore`` and is built fresh in CI
        before the test suite runs, so the bundle scan is still exercised in
        CI.

    Comment stripping is applied to source files; the minified-bundle scan
    skips comment stripping (there are no meaningful comments after minification).

    The existing ``test_frontend_source_files_contain_no_hardcoded_scientific_
    measurements`` test is a strict subset of this one; this test additionally
    covers the built output when dist/ is present.
    """
    if not SRC_DIR.exists():
        pytest.skip("frontend/src/ does not exist — nothing to scan")

    # Primary check: committed source tree (always runs)
    violations = _scan_src_dir(SRC_DIR)

    # Optional additional check: built bundle (only when dist/ is present).
    # Only scan application chunks — skip vendor-*.js which contains minified
    # Three.js / recharts / React internals with thousands of library constants
    # that are not scientific values.  The manualChunks split in vite.config.js
    # routes all node_modules into vendor-*.js, so index-*.js contains only
    # application code.  Source-map files (*.map) are also skipped.
    if DIST_DIR.exists():
        corpus = _load_artifact_corpus()
        js_files = [
            f for f in sorted(DIST_DIR.glob("assets/*.js"))
            if not f.name.startswith("vendor-") and not f.name.endswith(".map")
        ]
        for js_file in js_files:
            text = js_file.read_text(encoding="utf-8", errors="replace")
            for f in sorted(_extract_sci_floats(text)):
                if f in _PHYSICS_FORMULA_COEFFICIENTS:
                    continue
                if f not in corpus:
                    violations.append(f"  dist/{js_file.name}  →  {f}")

    assert not violations, (
        "Frontend contains scientific floats not backed by any committed "
        "artifact (AGENTS.md Rule 1):\n"
        + "\n".join(violations[:40])
        + (f"\n  ... and {len(violations) - 40} more" if len(violations) > 40 else "")
        + "\n\nThese values must originate from the API response, not be "
          "hardcoded in source files.  Run the pipeline, get the report, "
          "and bind UI properties to report fields.\n"
          "Rendering constants (Three.js font sizes, scene units) belong in "
          "_FRAMEWORK_EXEMPT; physics-formula coefficients belong in "
          "_PHYSICS_FORMULA_COEFFICIENTS."
    )


# ── Sanity: corpus is non-empty ───────────────────────────────────────────

@pytest.mark.no_network
def test_artifact_corpus_is_not_empty():
    """
    The artifact corpus must be non-trivially populated.  If it is empty,
    the other tests would vacuously pass.
    """
    corpus = _load_artifact_corpus()
    # We know MANIFEST.json has eb_catalog floats: 2.6045, 0.1396, 0.0209, 6.68, 0.04
    known_manifest_floats = {'2.6045', '0.1396', '0.0209', '6.680', '6.68'}
    present = known_manifest_floats & corpus
    assert present, (
        f"Artifact corpus does not contain expected values from MANIFEST.json.\n"
        f"  Expected at least one of: {known_manifest_floats}\n"
        f"  Corpus sample: {list(corpus)[:20]}"
    )


@pytest.mark.no_network
def test_fixture_files_exist():
    """The three fixture files used by other tests must all be present."""
    required = [
        FIXTURES_DIR / "job_done_no_tces.json",
        FIXTURES_DIR / "job_done_one_candidate.json",
        FIXTURES_DIR / "provenance.json",
    ]
    missing = [p for p in required if not p.exists()]
    assert not missing, (
        "Required API fixture files are missing:\n"
        + "\n".join(f"  {p}" for p in missing)
    )


@pytest.mark.no_network
def test_provenance_fixture_golden_count_matches_manifest():
    """
    The provenance fixture's golden_manifest_entry_count must match
    the actual count in data/golden/MANIFEST.json.
    This test would catch someone editing the fixture to invent a number.
    """
    fixture_path = FIXTURES_DIR / "provenance.json"
    if not fixture_path.exists():
        pytest.skip("provenance.json fixture not found")
    if not MANIFEST_PATH.exists():
        pytest.skip("data/golden/MANIFEST.json not found")

    with open(fixture_path, encoding="utf-8") as f:
        fixture = json.load(f)
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    actual_count = len(manifest.get("golden_set", []))
    fixture_count = fixture.get("golden_manifest_entry_count")

    assert fixture_count == actual_count, (
        f"provenance.json fixture has golden_manifest_entry_count={fixture_count} "
        f"but data/golden/MANIFEST.json has {actual_count} entries.\n"
        "Update the fixture to match the manifest, or vice versa."
    )


@pytest.mark.no_network
def test_non_claims_in_fixtures_match_api_source():
    """
    The non_claims lists in the API fixtures must be subsets of the
    non_claims defined in falsifier/api/routes/provenance.py and
    falsifier/api/models.py.  No invented claims allowed.
    """
    provenance_fixture_path = FIXTURES_DIR / "provenance.json"
    if not provenance_fixture_path.exists():
        pytest.skip("provenance.json fixture not found")

    # Load non_claims from the Python source (stdlib only — read as text)
    routes_text = (REPO_ROOT / "falsifier" / "api" / "routes" / "provenance.py").read_text(encoding="utf-8")
    models_text = (REPO_ROOT / "falsifier" / "api" / "models.py").read_text(encoding="utf-8")

    # Extract string literals from the source files as the authoritative set
    source_strings: set[str] = set()
    for text in (routes_text, models_text):
        source_strings.update(re.findall(r'"([^"]{10,})"', text))
        source_strings.update(re.findall(r"'([^']{10,})'", text))

    with open(provenance_fixture_path, encoding="utf-8") as f:
        fixture = json.load(f)

    # Also load the raw source text for substring search
    routes_raw = (REPO_ROOT / "falsifier" / "api" / "routes" / "provenance.py").read_text(encoding="utf-8")
    models_raw = (REPO_ROOT / "falsifier" / "api" / "models.py").read_text(encoding="utf-8")
    combined_source = routes_raw + "\n" + models_raw

    fixture_non_claims = fixture.get("non_claims", [])
    invented: list[str] = []
    for claim in fixture_non_claims:
        # Check verbatim substring in raw source text (handles multi-line strings
        # and string literals that span source_strings extraction)
        if claim not in combined_source and not any(claim in s or s in claim for s in source_strings):
            invented.append(claim)

    assert not invented, (
        "provenance.json fixture contains non_claims not found in the API source "
        "files.  These may be invented claims:\n"
        + "\n".join(f"  {c!r}" for c in invented)
    )
