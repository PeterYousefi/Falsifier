# Falsifier

[![CI](https://github.com/ajdarstudio/Falsifier/actions/workflows/ci.yml/badge.svg)](https://github.com/ajdarstudio/Falsifier/actions/workflows/ci.yml)
[![Live Demo](https://img.shields.io/badge/demo-falsifier.vercel.app-blue)](https://falsifier.vercel.app)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![IBM AI Builders Challenge 2026](https://img.shields.io/badge/IBM_AI_Builders_Challenge-Space_Exploration-0062ff)](https://ibm.com/ai-builders)

> **This project is not a biosignature detector.**
> **No exoplanet biosignature has ever been confirmed.**
> This claim is immutable. No generated code, comment, or UI copy contradicts it.

---

## Demo

<!-- DEMO_VIDEO_URL is defined here exactly once. Change this one line when the real URL is ready.
     See docs/RELEASE_CHECKLIST.md for the exact file and line to edit. -->
[▶ Watch the walkthrough](__DEMO_VIDEO_URL__) — 3 min · enter a Kepler/TESS ID, watch all four pipeline stages stream live, see the named rejection mechanism

---

## Judge Quick Access

| To verify… | Go here |
|---|---|
| The project is not a biosignature detector | Top of this file — locked blockquote |
| **Live judge walkthrough page** | App → Judge tab — **[falsifier.vercel.app](https://falsifier.vercel.app)** |
| Every number in the README is regenerated | `python scripts/verify_readme.py --strict` (exits 0) |
| Live claim inventory with pass/fail per claim | `GET https://<backend>/verify` (no auth required) |
| Kepler-10b period recovered to 5.3×10⁻⁶ days | `pytest tests/test_kepler10_recovery.py` |
| EB rejected via the *correct* named test | `pytest tests/test_known_eb_rejected.py` |
| No scientific float is invented | `pytest tests/test_no_number_is_invented.py` |
| All nine harness defects caught before commit | [`docs/WHAT_THE_GATES_CAUGHT.md`](docs/WHAT_THE_GATES_CAUGHT.md) |
| Eight mutation gates proven with verbatim output | [`docs/PROVEN_GATES.md`](docs/PROVEN_GATES.md) |
| Adversarial false-alarm rate finding | README → Measured results; source `docs/tls_run_2026_q3_baseline.md` |
| How IBM Bob was used | Section below; see also [`docs/BOB_EVIDENCE.md`](docs/BOB_EVIDENCE.md) |
| Prior-art positioning | [`docs/PRIOR_ART.md`](docs/PRIOR_ART.md) |
| Provenance-is-not-truth worked example | [`docs/PROVENANCE_IS_NOT_TRUTH.md`](docs/PROVENANCE_IS_NOT_TRUTH.md) |
| Negative-claim protocol | [`docs/NEGATIVE_CLAIMS.md`](docs/NEGATIVE_CLAIMS.md) |
| Train/serve skew refusal as ADR | [`docs/decisions/0001-refuse-proxy-training.md`](docs/decisions/0001-refuse-proxy-training.md) |

---

## Falsification thesis

Most detection pipelines are built to find things. This one is built to destroy its own candidates:
[`adversarial_selftest.py`](scripts/adversarial_selftest.py) runs on four categories of null data
to make it fail, [`injection_recovery.py`](scripts/injection_recovery.py) finds where detection
breaks down, eight mutation gates in [`docs/PROVEN_GATES.md`](docs/PROVEN_GATES.md) confirm tests
fail when they should, and a single FAIL in [`falsifier/pipeline/contracts/vet.py`](falsifier/pipeline/contracts/vet.py)
kills a candidate with no appeal.
A candidate that survives is one that could not be killed.

**File backing every clause:**
- "four categories of null data" → `scripts/adversarial_selftest.py` (`CATEGORIES`)
- "eight mutation gates" → `docs/PROVEN_GATES.md` (eight `✅ EXECUTED` rows)
- "single FAIL kills a candidate" → `falsifier/pipeline/contracts/vet.py` (`model_validator`)

**Proven gates (mutation log):**

| Gate | What it catches | Mutation level | Logged |
|---|---|---|---|
| Period recovery | `run_search` returning a period off by 0.01 d (100× tolerance) | **Pipeline-level** (`mock.patch.object` on `run_search`) + assertion-level | Yes |
| EB triggering test | Correct rejection but wrong test name (`centroid_shift` instead of `odd_even_depth`) | **Pipeline-level** (`mock.patch.object` on `run_vet`) + assertion-level | Yes |
| No-fabricated-numbers | README version block hand-edited to `9.9.9-FAKE` | Source mutation | Yes |
| Leakage | Same host star in both train and test `host_star_ids` | Source mutation | Yes |
| Time round-trip | Residual of 1e-6 d (1000× tolerance) | Source mutation | Yes |
| Provenance completeness | Sidecar with `access_date` removed | Source mutation | Yes |
| Phase-zero t0 convention | `phased_lc` constructed with t0 shifted by one Kepler long-cadence | Analytical | Yes |
| Unregistered-numeric scanner | README contains `4.7×10⁻⁶` outside any CLAIM block | Fixture mutation | Yes |

---

## Measured results

> Every number here is wrapped in a `<!-- CLAIM:name -->` block and verified by
> `python scripts/verify_readme.py --strict`.  That command is the acceptance gate.
> Manually editing a number is a policy violation (AGENTS.md Rule 5).

<!-- CLAIM:falsifier_version -->
Pipeline version: `0.1.0-dev`
<!-- /CLAIM:falsifier_version -->

<!-- CLAIM:n_pipeline_stages -->
Pipeline stages wired in API queue: 5
<!-- /CLAIM:n_pipeline_stages -->

**Kepler-10b period recovered** on committed FITS (detrend → TLS):

<!-- CLAIM:recovered_period_days -->
Kepler-10b recovered period (TLS on committed FITS): 0.83748542 days (Δ = 5.3e-06 days)
<!-- /CLAIM:recovered_period_days -->

19× tighter than the 1e-4 day tolerance. Tolerance (<!-- CLAIM:period_tolerance_days -->
Period recovery tolerance: 1e-04 days (~8.6 s)
<!-- /CLAIM:period_tolerance_days -->
). Published value:

<!-- CLAIM:kepler10b_period_days -->
Kepler-10b published period (Batalha et al. 2011): 0.83749070 days
<!-- /CLAIM:kepler10b_period_days -->

**KIC 6965293 EB rejected** via `odd_even_depth` specifically (named test asserted, not just rejection).
Depth ratio:

<!-- CLAIM:eb_depth_ratio -->
KIC 6965293 EB depth ratio (Prša et al. 2011): 6.68 primary/secondary
<!-- /CLAIM:eb_depth_ratio -->

**Adversarial false-alarm rate (preliminary):**

<!-- CLAIM:scrambled_far_preliminary -->
Scrambled FAR (preliminary, 2026-08-19 BLS-fallback run): 0.20 at SDE ≥ 9.0
<!-- /CLAIM:scrambled_far_preliminary -->

Randomly permuted flux clears the SDE threshold 20% of the time — a property of the threshold, not the substrate. SDE threshold:

<!-- CLAIM:adversarial_sde_threshold -->
Adversarial false-alarm SDE threshold: 9.0
<!-- /CLAIM:adversarial_sde_threshold -->

Categories tested:

<!-- CLAIM:adversarial_n_categories -->
Adversarial null-data categories: 4
<!-- /CLAIM:adversarial_n_categories -->

Injection recovery SDE threshold:

<!-- CLAIM:injection_sde_threshold -->
Injection recovery SDE threshold: 9.0
<!-- /CLAIM:injection_sde_threshold -->

Period-match tolerance:

<!-- CLAIM:injection_period_match_pct -->
Period-match tolerance for recovery: 2%
<!-- /CLAIM:injection_period_match_pct -->

Vetting tests:

<!-- CLAIM:n_vetting_tests -->
Vetting tests: 7
<!-- /CLAIM:n_vetting_tests -->

Proven gates (mutation log with verbatim output):

<!-- CLAIM:n_proven_gates -->
Gates proven by mutation testing: 8
<!-- /CLAIM:n_proven_gates -->

Tests collected (CI, full-dev):

<!-- CLAIM:n_tests_ci -->
Full test suite (CI, full-dev): 436 collected
<!-- /CLAIM:n_tests_ci -->

Time round-trip tolerance:

<!-- CLAIM:time_roundtrip_tolerance -->
Time round-trip tolerance: 1e-09 days (86.4 µs)
<!-- /CLAIM:time_roundtrip_tolerance -->

Committed golden targets:

<!-- CLAIM:n_golden_targets -->
Committed golden targets: 12
<!-- /CLAIM:n_golden_targets -->

Curated exploratory targets:

<!-- CLAIM:n_curated_targets -->
Curated exploratory targets: 2
<!-- /CLAIM:n_curated_targets -->

**Real-world context** (source: NASA Exoplanet Archive `10.26133/NEA12`, `data/artifacts/impact_facts.json`):

<!-- CLAIM:koi_fp_count -->
KOI FALSE POSITIVE count: 479
<!-- /CLAIM:koi_fp_count -->

<!-- CLAIM:koi_total_rows -->
KOI cumulative table total rows: 2,000
<!-- /CLAIM:koi_total_rows -->

<!-- CLAIM:koi_fp_fraction -->
KOI false-positive fraction: 23.9%
<!-- /CLAIM:koi_fp_fraction -->

<!-- CLAIM:koi_confirmed_count -->
KOI CONFIRMED count: 1,329
<!-- /CLAIM:koi_confirmed_count -->

<!-- CLAIM:koi_candidate_count -->
KOI CANDIDATE count: 192
<!-- /CLAIM:koi_candidate_count -->

<!-- CLAIM:toi_fp_count -->
TESS TOI FP count: 530
<!-- /CLAIM:toi_fp_count -->

<!-- CLAIM:toi_pc_count -->
TESS TOI PC count: 712
<!-- /CLAIM:toi_pc_count -->

<!-- CLAIM:toi_cp_count -->
TESS TOI CP count: 365
<!-- /CLAIM:toi_cp_count -->

For full methodology and tables: [`docs/MEASURED_RESULTS.md`](docs/MEASURED_RESULTS.md)

---

## How IBM Bob was used

| Bob capability | How it was applied |
|---|---|
| **Architect Mode (Plan)** — contract design | Designed the `VetInput` / `VetOutput` Pydantic schemas before any implementation; contract tests were written first, failing until the stage matched them |
| **Code Mode (Agent)** — per-stage implementation | Each of the five pipeline stages was implemented in a separate Bob session; Bob surfaced three type violations before any test was run |
| **Golden tests first** — TDD scaffolding | Bob generated `test_kepler10_recovery.py` and `test_known_eb_rejected.py` as failing stubs |
| **Defect surfacing** — depth-formula bug | Bob identified that `results.depth` in TLS is flux *level*, not fractional depth |
| **Policy enforcement** — AGENTS.md contracts | Bob refused to hardcode `SDE_THRESHOLD = 9.0` in the adversarial script; extracted it to `pipeline_constants.py` |

See [`docs/BOB_EVIDENCE.md`](docs/BOB_EVIDENCE.md) for committed Bob artifacts and session transcripts.

---

## Full documentation index

| Topic | File |
|---|---|
| Architecture, API, deployment | [`docs/FULL_ARCHITECTURE.md`](docs/FULL_ARCHITECTURE.md) |
| Full measured results with methodology | [`docs/MEASURED_RESULTS.md`](docs/MEASURED_RESULTS.md) |
| Test coverage detail | [`docs/TEST_COVERAGE.md`](docs/TEST_COVERAGE.md) |
| Completeness curve & FAR methodology | [`docs/COMPLETENESS_AND_FAR.md`](docs/COMPLETENESS_AND_FAR.md) |
| Nine defects caught before commit | [`docs/WHAT_THE_GATES_CAUGHT.md`](docs/WHAT_THE_GATES_CAUGHT.md) |
| Eight mutation gates — verbatim output | [`docs/PROVEN_GATES.md`](docs/PROVEN_GATES.md) |
| Dead / experimental code declaration | [`docs/DEAD_CODE.md`](docs/DEAD_CODE.md) |
| Skipped tests inventory | [`docs/SKIPPED_TESTS.md`](docs/SKIPPED_TESTS.md) |
| Prior-art positioning | [`docs/PRIOR_ART.md`](docs/PRIOR_ART.md) |
| IBM Bob evidence | [`docs/BOB_EVIDENCE.md`](docs/BOB_EVIDENCE.md) |
| Negative-claim protocol | [`docs/NEGATIVE_CLAIMS.md`](docs/NEGATIVE_CLAIMS.md) |
| Provenance-is-not-truth | [`docs/PROVENANCE_IS_NOT_TRUTH.md`](docs/PROVENANCE_IS_NOT_TRUTH.md) |
| ADR: refuse proxy training | [`docs/decisions/0001-refuse-proxy-training.md`](docs/decisions/0001-refuse-proxy-training.md) |
| TLS baseline run (preliminary FAR) | [`docs/tls_run_2026_q3_baseline.md`](docs/tls_run_2026_q3_baseline.md) |
| Release checklist | [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md) |

---

## Non-negotiable rules

| Rule | Enforcement |
|---|---|
| No hardcoded scientific values in UI/API | `python scripts/verify_readme.py --strict` |
| Every physical quantity carries `astropy.units` | `pytest tests/pipeline/contracts/` |
| Every dataset records DOI + access date + row count | `pytest tests/test_provenance_complete.py` |
| ML splits grouped by host star ID | `pytest tests/test_no_leakage.py` |
| README claims regenerable | `python scripts/verify_readme.py --strict` (CI gate) |
| Dead code declared explicitly | [`docs/DEAD_CODE.md`](docs/DEAD_CODE.md) |

---

## License

MIT — see [`LICENSE`](LICENSE)
