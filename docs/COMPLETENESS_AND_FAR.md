# Completeness Curve and Adversarial False-Alarm Rate

## Completeness curve — harness built, nine defects caught, artifact not yet committed

The injection-recovery harness is built, unit-tested, and sharded across a
45-job matrix (5 stars × 9 depths, 30 injections each). Nine defects were
caught and fixed before any numbers were committed
(see `docs/WHAT_THE_GATES_CAUGHT.md`).

*Scope:* no completeness numbers are committed yet. The two runs to date were
blocked before any artifact could be written.

**Shard layout:**

| Dimension | Value |
|---|---|
| Jobs | 45 (5 stars × 9 depths, parallel, `fail-fast: false`) |
| Injections per job | 30 (6 periods × 5 per cell) |
| Per-job cap | 5 hours (`timeout-minutes: 300`) |
| Per-injection cost (estimated) | 6–9 min on ~24,000 cadences |
| Timing measurement | `measure-tls-timing` pre-flight job |
| Checkpoint | JSONL written after each injection; resume on re-trigger |

**Prior runs (detail):**

- *Run 1 (BLS_fallback, 2026-08-19)*: TLS not installed; `test_detection_algorithm_is_tls` would have failed. Run discarded.
- *Run 2 (contaminated star list + missing MAST products, 2026-08-19)*: two shards exited with `QuietStarNotFoundError`. Replacement stars (KIC 5084157, KIC 8935630) pinned.

To regenerate (trigger via GitHub Actions; requires MAST access for Q1–Q8 fetch):
```bash
python scripts/injection_recovery.py \
  --seed 42 --n-per-cell 5 \
  --depth-filter 1500 \
  --output-dir data/artifacts/shards \
  --no-plot
```

---

## Adversarial false-alarm rate — 20% on scrambled flux at SDE = 9.0

Scrambled FAR = 0.20 at SDE = 9.0 (preliminary, 2026-08-19 BLS-fallback run).
Randomly permuting the flux array clears the SDE = 9.0 detection threshold 20%
of the time. This is a property of the threshold, not the substrate.

*Scope:* this figure comes from the 2026-08-19 run on a contaminated star list
with BLS_fallback detector. The number will be re-measured on the corrected
quiet-star list under TLS.

**Categories of null data:**

| Category | What it tests |
|---|---|
| `scrambled` | Time axis randomly permuted |
| `sign_inverted` | Flux negated |
| `off_target` | Flux rolled by N cadences (simulates ~15 arcsec background EB contamination) |
| `blank_sky` | Gaussian noise at ~300 ppm instrument floor |

See `docs/tls_run_2026_q3_baseline.md` and `docs/WHAT_THE_GATES_CAUGHT.md` for
the nine defects caught before commit.
