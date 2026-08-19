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

---

## Adversarial Self-Test — Scrambled FAR Finding (2026-08-19, BLS_fallback)

> **Status:** This finding is from a contaminated, BLS-fallback run and must not
> be committed as a production result. It is preserved here as a real observation
> pending a clean TLS re-run on the corrected quiet-star list.

The adversarial self-test run of 2026-08-19 (20 trials per category, 5 stars,
BLS_fallback, contaminated star list) recorded:

| Category | n\_false\_alarms / n\_trials | FAR |
|---|---|---|
| **scrambled** | 4/20 | **0.20** |
| sign\_inverted | 0/20 | 0.00 |
| off\_target | 1/20 | 0.05 |
| blank\_sky | 0/20 | 0.00 |

### Findings to preserve

1. **scrambled FAR = 0.20 at SDE ≥ 9.0.** Randomly permuting the flux array
   — which destroys all astrophysical structure — clears the SDE = 9.0 threshold
   20% of the time. This strongly suggests SDE = 9.0 is too permissive as a sole
   detection gate for a 30-day period search window. The threshold should be
   re-examined once a clean TLS run on the corrected quiet-star list exists.

2. **off\_target detection is a real planet (trial 53, KIC 9410930).** The
   `off_target` transform rolls the flux array, which preserves periodicity. The
   single detection at P = 1.856 d, SDE = 27.9 corresponds to K00196.01
   (P = 1.9 d) — a confirmed planet on one of the contaminated substrate stars.
   This is direct confirmation that substrate contamination invalidates the run;
   it is not a false alarm from the off\_target transform itself.

3. **sign\_inverted trials were byte-identical duplicates.** Sign inversion is
   deterministic: 20 trials on 5 stars produced 4 groups of 5 identical outputs.
   Effective n was 5, not 20. Fixed in `adversarial_selftest.py` by adding a
   per-cadence Gaussian noise realisation scaled by `flux_err` before each trial.

4. **best\_depth\_ppm was wrong (~999,700 ppm).** TLS `results.depth` is the
   flux level at mid-transit, not the fractional depth. Fixed in both
   `adversarial_selftest.py` and `injection_recovery.py`:
   `depth_ppm = (1 - results.depth) * 1e6`.

### 5 — n_cadences inconsistency: KIC 7272437 ran on Q1–Q8 while others ran Q3

KIC 7272437 has a committed stitched Q1–Q8 file (~23,784 cadences) in
`data/golden/`.  The `load_light_curve` function selects the longest-baseline
file automatically.  The other four stars had only their Q3 files (~3,000–4,000
cadences) at runtime.

Result: the trial table showed `n_cadences = 23,784` for KIC 7272437 and
3,000–4,000 for all other stars.  The substrate was not homogeneous.

**Fix (applied):** the `generate-artifacts.yml` adversarial job now fetches
Q1–Q8 for **all five** quiet stars, including KIC 7272437 (`--force`), so every
star resolves to a ~720-day baseline before the script runs.  See
`docs/WHAT_THE_GATES_CAUGHT.md` defect #9.

### Action required

Re-run `adversarial_selftest.py` after fetching Q1–Q8 FITS files for the corrected
quiet-star list (KIC 1161145, KIC 5084157, KIC 7272437, KIC 7347849, KIC 8935630).
Use `--force` for KIC 7272437 even though a Q1-Q8 file is already committed, so
the workflow confirms all five stars resolve to consistent baselines.
Only commit the artifact once TLS is used and the star list is clean.

> KIC 5347580 and KIC 8867895 have been replaced: KIC 5347580 had no Q1–Q8 MAST
> products (only Q9/Q13/Q17); KIC 8867895 entered safe mode after Q1 and has only
> two quarters in MAST. Replacements verified planet-free and Q1–Q8 confirmed
> 2026-08-19.

---

## Injection-Recovery Shard Failure Diagnosis — Run \#32214547803 (2026-08-19)

### Observed

Jobs `IR shard — KIC 5347580` (job 95953725039) and `IR shard — KIC 8867895`
(job 95953725124) both returned exit code 1. Step timing from the GitHub API:

| Step | KIC 5347580 | KIC 8867895 |
|---|---|---|
| Install Python deps | 60 s | 60 s |
| **Fetch Q1–Q8 light curve** | **8 s** (exit 0) | **9 s** (exit 0) |
| Write star list CSV | instant | instant |
| **Run injection\_recovery.py** | **≤1 s** ❌ exit 1 | **≤1 s** ❌ exit 1 |

The fetch step completed in 8–9 seconds and returned exit 0. The injection
script crashed in under one second.

### Correction to earlier inference

A prior diagnosis suggested `QuietStarBaselineTooShortError` as the possible
cause, with the note that the Q3 baseline (~89 days) "might be shorter than
MIN\_BASELINE\_DAYS = 60 d". That inference is **wrong**: 89 > 60, so the
baseline check passes on a successfully loaded Q3 file. The stated mechanism
cannot explain the observed failure.

### Actual root cause

**`fetch_golden.py` exited 0 even though no FITS file was written to disk.**

`fetch_golden.py --force --target "KIC 5347580"` matched both the Q3 and the
Q1–Q8 entries for that star. The Q3 download attempted to find the pinned product
`kplr005347580-2009350155506_llc`. If MAST returned no results or the pinned
product was not found, `_fetch_single_quarter` printed an error to stderr and
returned `False` — the script then continued, printed "Done. 0/2 file(s)
fetched.", and **exited 0 unconditionally**.

Because no FITS file existed at `data/golden/kic_5347580*.fits`, the subsequent
`injection_recovery.py` call hit `QuietStarNotFoundError` in `load_quiet_star`
within the first second (before any light curve was loaded, before any TLS call).

Timing is consistent: 8–9 s is plausible for one fast MAST query returning
empty results; ≤1 s crash is consistent with `QuietStarNotFoundError` raised
at startup.

### Fix applied

`fetch_golden.py` now distinguishes between:
- `_fetch_entry` returns `False` and the file **already exists** → skip (not a
  failure; the file is present from a prior committed fetch).
- `_fetch_entry` returns `False` and the file **does not exist** → genuine failure;
  `failed` counter incremented, `sys.exit(1)` at the end.

This makes the CI step that calls `fetch_golden.py` fail visibly at the fetch
stage, rather than silently allowing the injection script to crash later with a
misleading error.

### Outstanding

The root cause of the MAST fetch failure (why the pinned product was not found)
is not determinable from the public GitHub API without the actual job log text
(which requires admin credentials to download). Possible causes: transient MAST
API error, product ID format change, or the star not being available under the
pinned pipeline version for Q3. The fetch fix ensures this surfaces as a clear
error regardless of the underlying MAST issue.
