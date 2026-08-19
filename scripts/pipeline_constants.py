"""
scripts/pipeline_constants.py
================================
Single source of truth for all constants shared between
scripts/adversarial_selftest.py, scripts/injection_recovery.py, and
scripts/merge_injection_recovery.py.

Rules
-----
- Every constant here has one definition and one definition only.
- No script may re-define a constant already present here; the test
  ``tests/test_pipeline_constants.py`` enforces this.
- Physical quantities carry units in their names and/or comments (AGENTS.md Rule 2).

Adding a constant
-----------------
1. Add it here with a comment explaining its units and meaning.
2. Import it in the consuming script(s) rather than defining a local copy.
3. Add the constant name to ``SHARED_CONSTANT_NAMES`` in
   ``tests/test_pipeline_constants.py`` so the no-local-copy check stays tight.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Detection threshold
# ---------------------------------------------------------------------------

# A signal is counted as detected (or as a false alarm) when the Signal
# Detection Efficiency (SDE) from TLS / BLS meets or exceeds this value.
# Units: dimensionless.
SDE_THRESHOLD: float = 9.0

# ---------------------------------------------------------------------------
# Injection-recovery grids
# ---------------------------------------------------------------------------

# Transit depth grid in parts-per-million (ppm).
#
# The two shallowest entries (50, 100 ppm) are intentionally below the TLS
# detection floor on a ~89-day Kepler quarter (~200 ppm per-cadence RMS):
# the low-depth asymptote check requires mean recovery ≤ 0.15 at the
# shallowest entry.  The Q3-only run showed 200 ppm was detectable by TLS
# (mean rate 0.267), confirming 200 ppm is above the noise floor.
DEPTH_GRID_PPM: list[int] = [50, 100, 200, 400, 800, 1500, 3000, 6000, 12000]

# Orbital period grid in days.
#
# Q3-only baseline (~89 d): max recoverable ≈ 89/3 ≈ 29.7 d → 20 d last point.
# Multi-quarter baseline (Q1–Q8, ~720 d): all cells are well-sampled; the
# high-depth asymptote is expected to reach ≥ 0.95 with TLS.
PERIOD_GRID_DAYS: list[float] = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0]

# Period-match tolerance for the recovery criterion.
# A signal is "recovered" when |P_recovered − P_injected| / P_injected ≤ this.
# Units: dimensionless fraction (0.02 = 2%).
PERIOD_MATCH_TOLERANCE: float = 0.02  # 2%

# ---------------------------------------------------------------------------
# Baseline requirements
# ---------------------------------------------------------------------------

# TLS needs at least 2 distinct transit windows to constrain the period; we
# require 3 to reduce aliasing from single-transit noise peaks.
MIN_TRANSITS_REQUIRED: int = 3

# Minimum light-curve baseline required so that the longest period in the grid
# has at least MIN_TRANSITS_REQUIRED transit windows.
# Derived at import time so the value stays consistent with PERIOD_GRID_DAYS.
# Units: days.
MIN_BASELINE_DAYS: float = PERIOD_GRID_DAYS[-1] * MIN_TRANSITS_REQUIRED  # 20 × 3 = 60 d

# ---------------------------------------------------------------------------
# Quiet-star target list
# ---------------------------------------------------------------------------

# Verified planet-free against the NASA Exoplanet Archive KOI cumulative table
# (all dispositions), 2026-08-19.  Q1-Q8 MAST coverage confirmed for every star.
#
# Replacement history:
#   KIC 3425851  → KIC 1161145 (2026-08-18): was CANDIDATE K00268.01, P=110.4d
#   KIC 5514383  → KIC 5347580 (2026-08-18): was CONFIRMED K00257.01, P=6.9d
#                → KIC 5084157 (2026-08-19): KIC 5347580 has NO Q1-Q8 MAST data
#                  (only Q9/Q13/Q17); pinned Q3 product does not exist in MAST.
#   KIC 9410930  → KIC 7347849 (2026-08-18): was CONFIRMED K00196.01, P=1.9d
#   KIC 10963065 → KIC 8867895 (2026-08-18): was CONFIRMED K01612.01, P=2.5d
#                → KIC 8935630 (2026-08-19): KIC 8867895 has only Q0/Q1 in MAST
#                  (entered safe mode after Q1); cannot produce a multi-quarter baseline.
#   KIC 7272437  → KEPT (no KOI entry, confirmed planet-free, full Q1-Q17 coverage)
#
# Replacement criteria: no KOI entry (any disposition), logg > 4.1,
# 5000 < Teff < 6200 K, Kepmag 11–12.5, full Q1-Q8 long-cadence in MAST.
# KIC data from Vizier V/133/kic; MAST coverage verified 2026-08-19.
DEFAULT_QUIET_STARS: list[str] = [
    "KIC 1161145",   # replaces KIC 3425851; Teff=5990K logg=4.32 Kepmag=12.36 — no KOI, Q1-Q8 ✓
    "KIC 5084157",   # replaces KIC 5347580; Teff=5677K logg=4.12 Kepmag=11.65 — no KOI, Q1-Q8 ✓
    "KIC 7272437",   # original; confirmed planet-free, no KOI entry, Q1-Q8 ✓
    "KIC 7347849",   # replaces KIC 9410930; Teff=5780K logg=4.44 Kepmag=12.46 — no KOI, Q1-Q8 ✓
    "KIC 8935630",   # replaces KIC 8867895; Teff=5664K logg=4.56 Kepmag=12.10 — no KOI, Q1-Q8 ✓
]
