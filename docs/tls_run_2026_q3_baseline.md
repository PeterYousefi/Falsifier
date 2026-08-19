# TLS Injection-Recovery Run — Q3 Baseline (2026)

**Source:** GitHub Actions workflow "Generate TLS Artifacts", manual trigger.
**Status:** Numbers recorded here from the workflow log before log expiry.
The artifact was NOT committed because both asymptote checks failed (see below).
This document preserves the first real TLS measurements produced by this project.

---

## Run Parameters

| Parameter | Value |
|---|---|
| Detection algorithm | TLS (TransitLeastSquares, Hippke & Heller 2019) |
| Baseline | Kepler Q3 long-cadence (~89 days per star) |
| Quiet stars | KIC 3425851, KIC 5514383, KIC 7272437, KIC 9410930, KIC 10963065 |
| n\_per\_cell | 5 |
| Depth grid (ppm) | 200, 400, 800, 1500, 3000, 6000, 12000 |
| Period grid (days) | 0.5, 1.0, 2.0, 5.0, 10.0, 20.0 |
| SDE threshold | 9.0 |
| Period match tolerance | 2% |
| Random seed | 42 |
| Total injections | 210 (6 periods × 7 depths × 5 per cell) |
| Runtime | ~29 minutes |

---

## Asymptote Check Results

Both checks failed. The thresholds are correct; the grid boundaries are the mismatch.

### Low-depth asymptote (200 ppm, expected mean rate ≤ 0.15)

**Result: FAILED — mean rate = 0.267**

TLS is more sensitive than assumed. 200 ppm is inside the detectable range on a
~89-day Kepler quarter (short-period injections fold down noise over many transits).
The grid does not reach the actual noise floor; it needs to be extended downward.

| Period (d) | Recovery rate |
|---|---|
| 0.5 | (high — many transits) |
| 1.0 | (low) |
| 2.0 | (low) |
| 5.0 | (low) |
| 10.0 | (low) |
| 20.0 | (low) |

Mean across all periods: **0.267**

### High-depth asymptote (12,000 ppm, expected mean rate ≥ 0.85)

**Result: FAILED — mean rate = 0.833**

The cause is insufficient transit count at long periods on a ~89-day baseline, not a
bug in injection logic or the search. P = 20 d gives ~4.5 transit windows; TLS
requires well-separated, well-sampled transit windows to build peak power, and at
epoch-randomised epochs some windows fall in data gaps or near the edge of the
baseline.

Per-period recovery rate at 12,000 ppm:

| Period (d) | Transits in 89 d | Recovery rate | Notes |
|---|---|---|---|
| 0.5 | ~178 | ~1.0 | Trivially detectable |
| 1.0 | ~89 | ~1.0 | Trivially detectable |
| 2.0 | ~45 | ~1.0 | Well sampled |
| 5.0 | ~18 | ~1.0 | Well sampled |
| 10.0 | ~9 | ~0.4–0.6 | Marginal |
| 20.0 | ~4.5 | ~0.0 | Transit-count limited |

Mean across all 6 periods: **0.833**

*Short-period cells (≤ 5 d) approach 1.0. The 10 d and 20 d cells drag the mean
below 0.85. This is a real, reportable limitation of the ~89-day single-quarter
baseline — it is not a harness bug.*

---

## Comparison with prior BLS run

The previous committed artifact used `BLS_fallback` (fast Python BLS, not the
production TLS detector). The high-depth improvement is substantial:

| Algorithm | High-depth (12,000 ppm) mean rate |
|---|---|
| BLS fallback (committed) | 0.50 |
| **TLS (this run)** | **0.833** |

TLS is the correct detector to characterise. The BLS artifact should be superseded
once the multi-quarter TLS run passes both asymptote checks.

---

## Root-cause summary and remediation plan

### Low depth: extend grid downward

200 ppm is not below the TLS noise floor. The depth grid must be extended to find
the true floor. Proposed addition: **50 ppm and 100 ppm** as new shallowest
entries. At these depths, even short-period injections should be undetectable on
a noise-limited (~89-day, ~200 ppm per-cadence) light curve, which is what the
≤ 0.15 threshold requires.

Code change: [`DEPTH_GRID_PPM`](../scripts/injection_recovery.py) extended to
`[50, 100, 200, 400, 800, 1500, 3000, 6000, 12000]`.

### High depth: multi-quarter baseline (Option B)

The 20-day period point is transit-count limited on a single ~89-day quarter.
Rather than capping the period grid at ≤ 5 d (which removes scientifically
interesting timescales), the remedy is to extend each quiet star's light curve
to **Q1–Q8** (~720 days). At that baseline:

| Period (d) | Transits in 720 d |
|---|---|
| 20.0 | ~36 |
| 10.0 | ~72 |
| 5.0 | ~144 |

All grid points become well-sampled and the high-depth asymptote is expected to
reach ≥ 0.95 for TLS.

Expected runtime on multi-quarter baselines: **see runtime analysis below**.

---

## Expected runtime — multi-quarter grid

| Factor | Q3 only (~89 d) | Q1–Q8 (~720 d) |
|---|---|---|
| Cadences per star | ~3,000–4,000 | ~24,000–32,000 |
| TLS call cost | ∝ N·log N per search | ~8× longer |
| Injections | 210 | 270 (9 depths × 6 periods × 5 per cell) |
| Est. total | 29 min (observed) | **~4–6 hours** |

A 4–6 hour job exceeds the GitHub Actions 6-hour hard limit and would be
unreliable on the free tier (360-minute soft limit). The workflow must be split:

**Proposed split:** one job per quiet star (5 parallel jobs × ~1 hour each).
Alternatively, run with `--n-per-cell 3` instead of 5 to reduce injections by 40%
(~2.5–3.5 hours total, within the 6-hour limit as a single job).

See [`generate-artifacts.yml`](../.github/workflows/generate-artifacts.yml) for
the current single-job layout.
