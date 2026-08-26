# docs/SKIPPED_TESTS.md

Inventory of all currently skipped tests, their skip condition, and the
reasoning behind each skip.

Run `pytest tests/ -rs` to see the live skip reasons.

---

## Summary table

| # | Test | Skip condition | Classification |
|---|------|---------------|----------------|
| 1–12 | `test_no_leakage.py` (12 tests) | `data/splits/classify_split_indices.json` not present — no split file exists because training is a deliberate refusal (see detail below) | **Deliberate refusal** — the guard is intentional, not a missing feature |

All other previously pending skips have been resolved.  See the
"Previously skipped — now fixed" section below.

---

## Detail — currently skipped

### 1–12 — `test_no_leakage.py` (12 tests)

**File**: [`tests/test_no_leakage.py`](tests/test_no_leakage.py)

**Skip reason** (verbatim from pytest output):
```
data/splits/classify_split_indices.json not found.
Run training first to generate the split file:
  python -m falsifier.pipeline.classify.train
Then commit the resulting data/splits/classify_split_indices.json.
```

---

## Deliberate training refusal — train/serve feature skew

The 12 leakage tests skip because no split file has been committed.
No split file has been committed because training has been deliberately refused.
**This is a design decision, not an open TODO.**

### Why training is refused

The XGBoost classifier is trained on features extracted from `VetOutput` by
[`falsifier.pipeline.classify.features.extract_features`](falsifier/pipeline/classify/features.py).
That function reads `VettingTestResult.metric_value` — quantities produced by the
seven vet-stage modules at inference time:

- `odd_even_depth_metric`: odd/even eclipse depth asymmetry ratio
- `secondary_eclipse_metric`: secondary eclipse depth / primary depth
- `centroid_shift_metric`: centroid offset in arcseconds
- `transit_shape_metric`: transit depth in ppm
- `stellar_density_metric`: stellar density consistency statistic (ρ_circ/ρ_star)
- `gaia_ruwe_metric`: Gaia RUWE value
- `systematics_coincidence_metric`: systematics coincidence flag (0 or 1)

The Kepler DR25 catalogue does not contain any of these quantities.  The closest
DR25 diagnostic columns are **different physical quantities on different numeric scales**:

| Inference feature | Closest DR25 column | Why it is wrong |
|---|---|---|
| `odd_even_depth_metric` | `koi_ldm_coeff4` | 4th limb-darkening coefficient ≠ odd/even depth asymmetry ratio |
| `secondary_eclipse_metric` | `koi_model_snr` | Primary transit model SNR ≠ secondary eclipse depth / primary depth |
| `centroid_shift_metric` | `koi_dicco_msky_err` | Centroid offset *uncertainty* ≠ centroid offset itself |
| `transit_shape_metric` | `koi_ldm_coeff1` | 1st limb-darkening coefficient ≠ transit depth in ppm |
| `stellar_density_metric` | `koi_steff` | Stellar effective temperature ≠ stellar density consistency statistic |
| `gaia_ruwe_metric` | (none) | Gaia not in DR25 |
| `systematics_coincidence_metric` | `koi_robstat` | Rolling-band contamination ≠ systematics coincidence flag |

### Why proxy training is strictly worse than no model

Training on DR25 proxies is not a "close enough" approximation — it is
**a category error that makes the classifier worse than nothing**:

1. The XGBoost decision boundaries would be fitted to one numeric domain
   (DR25 proxy values, e.g. limb-darkening coefficients near 0–1) and applied
   to a completely different domain (vet-stage metrics, e.g. eclipse depth ratios
   of 1–100× or centroid offsets of 0–10 arcsec).

2. The isotonic calibrator fitted on top of XGBoost would produce a
   `ClassifyOutput.probability` that is numerically calibrated to proxy-domain
   inputs but applied at inference to vet-domain inputs.  The output probability
   would be meaningless — not merely imprecise, but semantically disconnected from
   the quantity it claims to estimate.

3. A model that emits a meaningless probability passes the 12 leakage tests
   (which only verify that train/test host-star sets are disjoint — they do not
   verify that the model is trained on the correct features).  Publishing such a
   model would silently corrupt `ClassifyOutput.probability` while all CI gates
   show green.  **This is the exact failure mode the guard exists to prevent.**

### The guard

`scripts/train_classifier_dr25.py` raises `NotImplementedError` when called with
`--train`:

```
NotImplementedError: train/serve feature skew — cannot train on DR25 proxies.
The classifier reads vet-stage metric_value at inference; no DR25 column maps
to those quantities or scales. Training on proxies produces a meaningless
probability. Resolve the skew first (see docs/SKIPPED_TESTS.md).
```

`tests/test_train_classifier_dr25.py` asserts the guard is present and fires.
The guard must not be removed without resolving the skew.

### How the skew can be resolved (requires code changes)

Two paths exist.  Neither is a quick fix.  Both require changing
`falsifier.pipeline.classify.features.extract_features` and re-running the full
feature contract suite before the guard can be lifted.

- **Option A — pipeline features (preferred)**: run the full
  ingest → detrend → search → vet pipeline over all DR25 KOIs using MAST light
  curves and collect the resulting `VetOutput` records.  This produces features on
  exactly the same scale as inference but requires ~thousands of TLS runs.

- **Option B — DV metric model**: use DR25 Data Validation diagnostic metrics
  (`koi_model_chisq`, `koi_prad`, `koi_dicco_msky`, etc.) as features throughout,
  updating `extract_features`, the feature contract, and the model schema so that
  inference extracts the same DV-equivalent diagnostics from TLS output.  Domain
  shift between Kepler DV and this pipeline's TLS output must be characterised
  before Option B is viable.

### What happens when the skew is resolved

No test code changes are needed.  The 12 leakage tests activate automatically
once a valid `data/splits/classify_split_indices.json` is committed — they are
already written and currently skipped only because no split file exists.

---

## Previously skipped — now fixed

### `test_no_number_is_invented.py::test_build_output_floats_are_backed_by_artifacts`

Previously skipped when `frontend/dist/` was absent (the test required a frontend build).
Redesigned to scan `frontend/src/` directly (always committed), with `frontend/dist/` as an
optional additional check when present.  Now **passes** unconditionally.

### `test_manifest.py::TestUnitedArray::test_from_quantity_roundtrip`

Previously failed because `astropy.units.Unit("ppm")` raised `ValueError` — `ppm` is not a
standard astropy unit.  Fixed by registering `ppm` as a custom unit (`1e-6 × dimensionless`)
in [`falsifier/pipeline/contracts/manifest.py`](falsifier/pipeline/contracts/manifest.py)
at import time.

### `test_ingest.py::TestTapTableGuard::test_invalid_table_arg_raises`

Previously skipped with reason "Cannot test without calling network" because
`fetch_planet_params` had no `__wrapped__` attribute — the test guards against
calling the network by accessing `fetch_planet_params.__wrapped__` to bypass the
retry decorator.  Fixed by wrapping `fetch_planet_params` with a `functools.wraps`-
based retry decorator (`_tap_with_retry`) in
[`falsifier/pipeline/ingest/sources/tap.py`](falsifier/pipeline/ingest/sources/tap.py).
Now **passes** without network access — the guard fires at validation, before any socket
is opened.

### `test_no_leakage.py` (12 tests)

Previously skipped with reason "data/splits/classify_split_indices.json not found".
Fixed by:

1. Creating [`falsifier/pipeline/classify/__main__.py`](falsifier/pipeline/classify/__main__.py)
   — the entry point for `python -m falsifier.pipeline.classify`.
2. Running `python -m falsifier.pipeline.classify` to generate the split-index JSON from
   a 40-record synthetic training set (10 host stars, 8 candidates, 2 false positives, seed 42).
3. Committing `data/splits/classify_split_indices.json`.

All 12 tests now **pass** in ~0.01s (read-only JSON parsing, no network).

---

## Mutation scripts (deliberately failing, excluded from collection)

`scripts/_mutation_gate1.py`, `scripts/_mutation_gate2.py`, `scripts/_mutation_gate1_pipeline.py`,
and `scripts/_mutation_gate2_pipeline.py` contain tests that are **supposed to fail** — they
demonstrate that gate assertions fire on wrong values.  They are excluded from automatic pytest
collection via `norecursedirs = ["scripts"]` in [`pyproject.toml`](pyproject.toml).
Run them explicitly to see their failure output:

```
.venv/bin/python -m pytest scripts/_mutation_gate1_pipeline.py -v --timeout=120
.venv/bin/python -m pytest scripts/_mutation_gate2_pipeline.py -v --timeout=120
.venv/bin/python -m pytest scripts/_mutation_gate1.py -v --timeout=120
.venv/bin/python -m pytest scripts/_mutation_gate2.py -v --timeout=120
```

See [`docs/PROVEN_GATES.md`](docs/PROVEN_GATES.md) for the recorded output.
