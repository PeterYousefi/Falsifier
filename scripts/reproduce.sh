#!/usr/bin/env bash
# =============================================================================
# scripts/reproduce.sh
# =============================================================================
# Single-command reproducibility script for the Falsifier project.
#
# AGENTS.md Rule 5:
#   "No claim appears in README unless it is produced — and kept current —
#    by the project's reproducibility script."
#
# This script:
#   1. Verifies every CLAIM block in README.md matches its committed source.
#   2. Runs the full test suite (policy + contract + no-invented-numbers + API).
#   3. Runs the fast contract-only suite to prove pydantic-only import cleanliness.
#   4. Exits non-zero if anything fails.
#
# Usage:
#   bash scripts/reproduce.sh            # standard run
#   bash scripts/reproduce.sh --fast     # skip full test suite, only claims
#   bash scripts/reproduce.sh --strict   # pass --strict to verify_readme.py
#
# Requirements:
#   pip install -e ".[dev]"   (full dev install, including pytest)
#   Python 3.11+
#
# For the golden integration tests (test_kepler10_recovery.py,
# test_known_eb_rejected.py) you additionally need the committed FITS files:
#   python scripts/fetch_golden.py
# Those tests are excluded here until the FITS files are committed.
#
# Exit codes:
#   0  All claims and tests pass.
#   1  One or more claims have drifted, or one or more tests failed.
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
FAST=0
STRICT_FLAG=""

# Parse flags
for arg in "$@"; do
  case "$arg" in
    --fast)   FAST=1 ;;
    --strict) STRICT_FLAG="--strict" ;;
  esac
done

cd "$REPO_ROOT"

echo "========================================================"
echo " Falsifier reproducibility script"
echo " Repo root : $REPO_ROOT"
echo " Python    : $($PYTHON --version)"
echo "========================================================"
echo ""

# ---------------------------------------------------------------------------
# Step 1 — Verify every README CLAIM block matches its committed source.
#
# This is the canonical enforcement of AGENTS.md Rule 5.  Any number that
# was hand-edited into a CLAIM block (instead of being regenerated from a
# committed artifact) will be caught here with exit code 1.
# ---------------------------------------------------------------------------
echo "--- Step 1: Verify README claims ---"
$PYTHON scripts/verify_readme.py $STRICT_FLAG
echo ""

if [[ "$FAST" -eq 1 ]]; then
  echo "[--fast] Skipping test suite."
  echo ""
  echo "All README claims verified OK."
  exit 0
fi

# ---------------------------------------------------------------------------
# Step 2 — No-invented-numbers policy gate (stdlib only, no falsifier import).
#
# This test scans every committed API fixture and frontend source for
# scientific floating-point literals and asserts each one traces to a
# committed pipeline artifact.  It does not require astropy or lightkurve.
# ---------------------------------------------------------------------------
echo "--- Step 2: No-invented-numbers policy gate ---"
$PYTHON -m pytest tests/test_no_number_is_invented.py -v
echo ""

# ---------------------------------------------------------------------------
# Step 3 — Provenance completeness (AGENTS.md Rule 3).
#
# Every committed provenance sidecar must have source_doi / access_date /
# row_count.  This test reads data/golden/*.provenance.json and fails on any
# missing or malformed field.
# ---------------------------------------------------------------------------
echo "--- Step 3: Provenance completeness ---"
$PYTHON -m pytest tests/test_provenance_complete.py -v
echo ""

# ---------------------------------------------------------------------------
# Step 4 — Pipeline contracts (fast pydantic-only gate).
#
# Verifies that the pipeline contracts import cleanly with pydantic + numpy
# only (no astropy, no lightkurve, no sklearn at module scope).
# ---------------------------------------------------------------------------
echo "--- Step 4: Pipeline contracts (pydantic-only) ---"
$PYTHON -m pytest tests/pipeline/contracts/ -v
echo ""

# ---------------------------------------------------------------------------
# Step 5 — Full test suite (all non-golden tests, all policy gates).
#
# Excludes:
#   test_kepler10_recovery.py  — requires committed FITS files
#   test_known_eb_rejected.py  — requires committed FITS files
#
# The full dev install (pip install -e ".[dev]") provides astropy, fastapi,
# pytest-asyncio, and the rest of the dev dependency set.
# ---------------------------------------------------------------------------
echo "--- Step 5: Full test suite ---"
$PYTHON -m pytest tests/ \
  --ignore=tests/test_kepler10_recovery.py \
  --ignore=tests/test_known_eb_rejected.py \
  -v --tb=short
echo ""

# ---------------------------------------------------------------------------
# Step 6 — Re-verify README claims after test run (belt-and-suspenders).
#
# A test could theoretically mutate a source file.  Re-running the claim
# verification after the tests catches that scenario.
# ---------------------------------------------------------------------------
echo "--- Step 6: Re-verify README claims (post-test) ---"
$PYTHON scripts/verify_readme.py $STRICT_FLAG
echo ""

echo "========================================================"
echo " All steps passed.  README claims are verified OK."
echo " This project is not a biosignature detector."
echo " No exoplanet biosignature has ever been confirmed."
echo "========================================================"
