# docs/PRIOR_ART.md

> **Every factual claim about a named system in this document carries a DOI or
> arXiv identifier.  If a claim could not be sourced, it was dropped rather than
> softened.  No sentence in this document asserts that Falsifier is better than
> any named system.**

---

## Comparison table

The following systems are the incumbents in automated transit vetting.  Each row
describes what the system consumes, its decision mechanism, whether it names a
mechanism or returns a score, whether a rejection is reproducible from committed
inputs, and what it claims that Falsifier deliberately does not.

| System | Input | Decision mechanism | Output | Reproducible from committed inputs? | Claims Falsifier does not make |
|---|---|---|---|---|---|
| **Kepler Robovetter (DR25)** | Catalogue metrics from Kepler Data Validation pipeline (`koi_*` columns) | Deterministic heuristic cascade: ordered sequence of metric threshold comparisons; each metric is tested against a fixed threshold | Discrete disposition (`PC` / `FP` / `AFP` / `NTP`) plus a `not_transit_like_score` scalar (0–1) | Yes — DR25 catalogue columns + threshold constants are public; Thompson et al. 2018 (DOI: 10.3847/1538-4365/aab4f9) describes the exact cascade | A calibrated score between 0 and 1 representing degree of transit-likeness across the full DR25 TCE population |
| **ExoMiner** | Cadence-level flux, centroid, DV diagnostic time-series extracted from the Kepler DV pipeline | 1D CNN trained on DR25-labelled TCEs; no manual threshold tuning | Probability (0–1); threshold applied post-hoc to produce disposition | Reproducible given the committed model weights and the Kepler DV pipeline outputs; model architecture and training described in Valizadegan et al. 2022 (DOI: 10.3847/1538-4357/ac4399) | A learned probability over the full DR25 population; generalisation claims backed by held-out Kepler and TESS performance |
| **TRICERATOPS** | TESS photometry + GAIA astrometry + stellar catalog parameters | Bayesian false-positive probability: marginalises over background binary, nearby eclipsing binary, and planet scenarios via importance sampling | False-positive probability (FPP) per scenario; `fppt` scalar | Reproducible from TESS photometry + model parameters; Giacalone & Dressing 2020 (DOI: 10.3847/2515-5172/ab8e6e); Giacalone et al. 2021 (DOI: 10.3847/1538-3881/ac22f0) | Astrophysical prior over binary configurations; multi-scenario probability decomposition quantifying relative likelihood of competing hypotheses |
| **Vespa** | Transit depth and shape from a fit, plus stellar parameters | Marginalised likelihood over five false-positive scenarios (EB, background EB, hierarchical triple, etc.) using TRILEGAL galaxy model priors | False-positive probability (FPP) scalar | Reproducible given the TRILEGAL model and stellar parameters; Morton 2012 (DOI: 10.1086/668540); Morton et al. 2016 (DOI: 10.3847/0004-637X/822/2/86) | A galaxy-model-informed prior over binary occurrence rates; absolute FPP that quantifies the probability that a transit is not planetary |

---

## Boundary

### What Falsifier does not claim priority over

Automated vetting, transit search, and false-positive triage are established
fields with published, benchmarked, and widely deployed methods.  Kepler
Robovetter was the instrument for the official DR25 disposition of every
Kepler KOI (Thompson et al. 2018, DOI: 10.3847/1538-4365/aab4f9).  ExoMiner
achieves state-of-the-art performance on the DR25 population (Valizadegan et
al. 2022, DOI: 10.3847/1538-4357/ac4399).  TRICERATOPS and Vespa have both
been applied to the TESS alert stream at scale.  Falsifier does not contest
any of those results.

### The one axis of design difference

Falsifier uses a deterministic truth table in place of a score.  The table
lives in [`falsifier/pipeline/contracts/vet.py`](falsifier/pipeline/contracts/vet.py)
as a Pydantic `model_validator` enforced at object construction time.  Any
`VetOutput` with an inconsistent disposition raises at object-build time; it
cannot be stored.  When a candidate is rejected, `VetOutput.triggering_test`
names the specific test that triggered the rejection — not a probability, not
a score, but a string like `"odd_even_depth"` that points to a physical
measurement.  A rejection is auditable: a reader can open the artifact, read
the `triggering_test` field, and know exactly which test killed the candidate.

This is the axis on which the design differs from all four incumbents:
Robovetter returns a disposition plus a score; ExoMiner returns a probability;
TRICERATOPS and Vespa return FPPs.  Falsifier returns a named mechanism.

### The cost of that choice

A truth table cannot express graded evidence.  The four-outcome vocabulary
(`PASS | FAIL | FLAG | INCONCLUSIVE`) collapses continuous measurements to
discrete bins.  Robovetter's `not_transit_like_score` and ExoMiner's
probability both carry information that Falsifier's `FAIL / FLAG / INCONCLUSIVE`
discard.  A candidate that clears the `odd_even_depth` gate with a depth ratio
of 1.01 is treated identically to one that clears it with a ratio of 0.50:
both return `PASS`, both produce a `candidate` disposition if all seven tests
pass.  A score-based system can express the difference; the truth table cannot.

The choice is deliberate.  An auditable rejection without a probability is
more defensible than a calibrated probability whose calibration cannot be
verified at inference time (see `docs/decisions/0001-refuse-proxy-training.md`
and `docs/SKIPPED_TESTS.md`).  But the cost is real: cases where the evidence
is genuinely continuous, or where seven independent tests produce mixed signals,
are handled less expressively by a truth table than by a model.

---

## Sources

| Citation | DOI | Used for |
|---|---|---|
| Thompson et al. 2018, ApJS 235, 38 | `10.3847/1538-4365/aab4f9` | Kepler Robovetter DR25 description |
| Valizadegan et al. 2022, ApJ 926, 120 | `10.3847/1538-4357/ac4399` | ExoMiner architecture and DR25 benchmarks |
| Giacalone & Dressing 2020, RNAAS 4, 4 | `10.3847/2515-5172/ab8e6e` | TRICERATOPS initial description |
| Giacalone et al. 2021, AJ 161, 24 | `10.3847/1538-3881/ac22f0` | TRICERATOPS validation and TESS application |
| Morton 2012, ApJ 761, 6 | `10.1086/668540` | Vespa original description |
| Morton et al. 2016, ApJ 822, 86 | `10.3847/0004-637X/822/2/86` | Vespa application to Kepler candidates |
