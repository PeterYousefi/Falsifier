# ADR 0001 — Refuse Proxy Training for the Classifier

**Status:** Decided  
**Date:** 2026-08-26  
**Deciders:** Falsifier project  

---

## Context

The Falsifier pipeline has five stages: ingest → detrend → search → vet → classify.
The classify stage uses an XGBoost classifier that ingests a feature vector extracted
from `VetOutput` by `falsifier.pipeline.classify.features.extract_features`.

That function reads `VettingTestResult.metric_value` for each of the seven
canonical vet tests.  The resulting feature vector contains:

| Feature | Physical quantity | Typical range |
|---|---|---|
| `odd_even_depth_metric` | Odd/even eclipse depth asymmetry ratio | 1–100× |
| `secondary_eclipse_metric` | Secondary eclipse depth / primary depth | 0–1 |
| `centroid_shift_metric` | Centroid offset in arcseconds | 0–10 arcsec |
| `transit_shape_metric` | Transit depth in ppm | 100–50,000 ppm |
| `stellar_density_metric` | Stellar density consistency statistic (ρ_circ/ρ_star) | 0.1–10 |
| `gaia_ruwe_metric` | Gaia DR3 RUWE value | 0.5–5 |
| `systematics_coincidence_metric` | Systematics coincidence flag | 0 or 1 |

The standard labelled training set in this field is the Kepler DR25 catalogue
(Thompson et al. 2018, DOI: `10.3847/1538-4365/aab4f9`).  The DR25 cumulative
table is publicly available from the NASA Exoplanet Archive TAP service.  It
contains 2,000 entries with koi_disposition labels (`CONFIRMED`, `CANDIDATE`,
`FALSE POSITIVE`).  It is the natural candidate for training labels.

---

## The specific skew

The DR25 catalogue does not contain the seven features above.  The closest
available DR25 columns are different physical quantities on different numeric
scales:

| Inference feature | Closest DR25 column | Why it is wrong |
|---|---|---|
| `odd_even_depth_metric` | `koi_ldm_coeff4` | 4th limb-darkening coefficient (range 0–1) ≠ odd/even depth asymmetry ratio (range 1–100×) |
| `secondary_eclipse_metric` | `koi_model_snr` | Primary transit model SNR ≠ secondary eclipse depth / primary depth |
| `centroid_shift_metric` | `koi_dicco_msky_err` | Centroid offset *uncertainty* ≠ centroid offset itself |
| `transit_shape_metric` | `koi_ldm_coeff1` | 1st limb-darkening coefficient ≠ transit depth in ppm |
| `stellar_density_metric` | `koi_steff` | Stellar effective temperature ≠ stellar density consistency statistic |
| `gaia_ruwe_metric` | (none) | Gaia not in DR25 |
| `systematics_coincidence_metric` | `koi_robstat` | Rolling-band contamination flag is the closest match; still a different quantity |

This is not a problem of missing columns or imprecise proxies.  It is a
**domain mismatch**: the XGBoost decision boundaries would be fitted to DR25
proxy values (limb-darkening coefficients in [0, 1]) and applied at inference
to vet-stage outputs (depth ratios in [1, 100×]).  The isotonic calibrator
fitted on top of XGBoost would produce a `ClassifyOutput.probability` that is
calibrated to one numeric domain but applied to another.  The output probability
would be semantically disconnected from the quantity it claims to estimate.
It would not be merely imprecise; it would be meaningless.

---

## Options considered

### Option 1 — Train on DR25 proxies

Map each inference feature to its closest DR25 column, train XGBoost, and ship
a `ClassifyOutput.probability`.  Label the model as "trained on DR25 proxies."

**Rejected.**  The decision boundaries and the calibrator are both fitted to a
different numeric domain than inference.  Labelling the skew does not remove it.
A user reading `probability = 0.93` cannot know whether that number reflects
the vet-stage feature distribution or the DR25 proxy distribution.  The label
would need to appear in every downstream use of the probability — an
impractical requirement.  The 12 leakage tests (`tests/test_no_leakage.py`)
would pass (they verify host-star disjointness, not feature compatibility),
providing a false signal of correctness.

### Option 2 — Run the full pipeline on all DR25 KOIs (preferred)

Fetch light curves for all DR25 KOIs from MAST.  Run the full
ingest → detrend → search → vet pipeline on each.  Collect the resulting
`VetOutput` records.  Use the real `metric_value` fields as training features.

**The correct resolution.**  Features at training time are exactly the same
physical quantities on exactly the same numeric scale as at inference time.
No domain shift exists.  The calibrator is valid.

**Not yet implemented.**  This requires ~2,000 TLS runs on MAST light curves
(approximately 1–2 weeks of CI compute or several hours on a multi-node runner).
It is blocked by compute budget, not by a design problem.

### Option 3 — DR25 DV metric model

Use DR25 Data Validation diagnostic metrics (`koi_model_chisq`, `koi_prad`,
`koi_dicco_msky`, etc.) throughout.  Retrain the classifier on those metrics.
Rewrite `extract_features` to extract the same DV diagnostics from TLS output
at inference time.  Characterise the domain shift between Kepler DV and this
pipeline's TLS output.

**Viable but requires changes to the feature contract.**  The classify stage
would no longer be a "vet metric re-scorer" but a "DV metric classifier."
The `extract_features` function, the feature contract, and the `ClassifyOutput`
schema must all be updated.  The domain shift between Kepler DV and TLS output
must be characterised and documented before this option can be called valid.

---

## Decision

Training is **refused** until Option 2 or Option 3 is implemented.

`scripts/train_classifier_dr25.py --train` raises `NotImplementedError` with a
full explanation.  `tests/test_train_classifier_dr25.py` asserts the guard is
present.  The guard must not be removed without implementing one of the valid
options.

The 12 leakage tests in `tests/test_no_leakage.py` skip because no split file
has been committed.  No split file will be committed until a valid model exists.
This is the correct state.  The skip count is disclosed explicitly in
`docs/SKIPPED_TESTS.md` and in the README.

---

## Consequences

**Positive:**
- `ClassifyOutput.probability` is never populated with a number that means
  nothing.  A user who sees `probability = 0.93` can trust it reflects a model
  trained on the same feature distribution it is applied to — once a model
  exists.
- The 12 leakage tests are fully written and will activate automatically once a
  valid split file is committed.  No test code changes are needed to unblock.

**Negative:**
- The classify stage is wired to the API queue but has no committed model.  It
  runs in the live pipeline and returns a placeholder result.
- No ML-based probability is available for any target.  The vet disposition is
  the final output.
- The 12 leakage tests are permanently skipped until the skew is resolved.

**What would unblock it:**
- For Option 2: a multi-node CI job or a dedicated run on cloud compute fetching
  Q1–Q17 FITS for all 2,000 KOIs and running the full pipeline.  The commit of
  `data/splits/classify_split_indices.json` produced by that run unblocks all
  12 leakage tests automatically.
- For Option 3: a design document for the DV-metric feature contract, followed
  by updates to `extract_features`, the feature contract, and `ClassifyOutput`.
  Domain shift characterisation is required before the model can be considered
  valid.

---

## Generalisation

If the feature distribution at training time cannot be shown equal to the
feature distribution at inference time, a calibrated probability is not a
measurement. It is a number that has the appearance of a probability without
the semantic content. Shipping it is not a conservative choice: it is a choice
to mislead, because the output will be used as a probability by every consumer
who reads it. Any pipeline that trains a classifier on proxy features and
applies it to different features at inference time should apply this test before
committing a model.
