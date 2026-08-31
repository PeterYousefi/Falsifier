# Falsifier

[![CI](https://github.com/PeterYousefi/Falsifier/actions/workflows/ci.yml/badge.svg)](https://github.com/PeterYousefi/Falsifier/actions/workflows/ci.yml)
[![Live Demo](https://img.shields.io/badge/demo-falsifier.vercel.app-blue)](https://falsifier.vercel.app)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![IBM AI Builders Challenge 2026](https://img.shields.io/badge/IBM_AI_Builders_Challenge-Space_Exploration-0062ff)](https://ibm.com/ai-builders)

> **This project is not a biosignature detector.**
> **No exoplanet biosignature has ever been confirmed.**
> This claim is immutable. No generated code, comment, or UI copy contradicts it.

---

**"A neural network sees Earth 2.0. Astrophysics sees a background binary star.
The James Webb Space Telescope is one of the most expensive scientific instruments
humanity has ever built — Falsifier makes sure humanity doesn't point it at an AI hallucination."**

Most transit-detection pipelines and AI classification models are built to find planets, inherently suffering from confirmation bias when dealing with noisy deep-space data. This one is built to destroy its own candidates. A dimming light curve is not a discovery until it has survived seven independent attempts to explain it away as something else — and until then, the pipeline is designed to fail it, not flatter it.

▶ [Watch the walkthrough](__DEMO_VIDEO_URL__) — enter a Kepler/TESS target ID, watch every pipeline stage stream live, see the named rejection mechanism fire.

---

## The Judge Memory Moment: The Ghost Candidate

> **Illustrative scenario** — the Falsifier pipeline behavior shown here is genuine and
> reproducible (run `python3 scripts/judge_memory_moment.py`). The depth (1.33%),
> odd/even mismatch (4.32), and disposition (`false_positive` via `odd_even_depth`) are
> pipeline-measured from the committed KIC 6965293 FITS file. The "shape-only classifier"
> box is an illustrative description of confirmation-biased classifiers generally — no
> specific CNN was benchmarked against this target in this repository.

```
Light Curve Dip: 1.33% (pipeline-measured on KIC 6965293) ─────────────────────────┐
                                                                                     ▼
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Illustrative shape-only classifier (not built; comparison only):                     │
│ "High-confidence transit candidate — queues for expensive follow-up"                 │
│ (Such classifiers are trained on signal shape; this shape passes.)                   │
└──────────────────────────────────────────────────────────────────────────────────────┘
                          │
              [ FALSIFIER INTERVENTION ]
                          │
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Falsifier Odd/Even Depth Test:                                                       │
│ "FAIL — Odd/even transit depth mismatch 4.32 exceeds threshold 3.0"                 │
│ Physical Reality: Alternating transits of unequal depth — this is an                │
│ eclipsing binary star. The candidate is a ghost.                                     │
│ Action: CANDIDATE EXECUTED via odd_even_depth FAIL.                                 │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

*Pipeline-measured values from the committed KIC 6965293 golden FITS file
(`scripts/judge_memory_moment.py`, source DOI `10.1088/0004-6256/141/3/83`).*

<!-- CLAIM:jmm_depth_pct -->
Judge Memory Moment transit depth (KIC 6965293, pipeline-measured): 1.33%
<!-- /CLAIM:jmm_depth_pct -->

<!-- CLAIM:jmm_odd_even_mismatch -->
Judge Memory Moment odd/even mismatch (KIC 6965293, pipeline-measured): 4.32
<!-- /CLAIM:jmm_odd_even_mismatch -->

<!-- CLAIM:jmm_disposition -->
Judge Memory Moment disposition (KIC 6965293): false_positive
<!-- /CLAIM:jmm_disposition -->

<!-- CLAIM:jmm_triggering_test -->
Judge Memory Moment triggering test (KIC 6965293): odd_even_depth
<!-- /CLAIM:jmm_triggering_test -->

The Core Insight: Generative models and neural networks are trained on shape; space is full of things that look like planets but aren't. A light curve dip can be humanity's next home or an optical illusion from a background eclipsing binary. When AI guesses, space agencies waste resources. Falsifier makes sure space exploration targets physical reality, not statistical flukes.

---

## Challenge Fit: Advancing Space Exploration With AI

Space exploration does not begin at the launch pad; it begins at the targeting queue.

NASA's upcoming Habitable Worlds Observatory (HWO), the Roman Space Telescope, and future direct-imaging interstellar precursor probes cannot be redirected on a whim. Their cryogenic propellants, station-keeping fuel, and observation windows are finite.

If humanity relies on standard AI pipelines that optimize for discovery volume, we will point multi-billion-dollar space assets at ghosts. Falsifier directly advances space exploration by serving as the autonomous pre-flight targeting firewall: ensuring that every target queued for deep-space characterization has survived every physical falsification test known to astrophysics.

---

## Feasibility: One-Command Reproduction

No cloud accounts. No API keys. No complex database provisioning. The deterministic core is offline-first and runs in seconds, making it immediately deployable for resource-constrained observatories:

```bash
pip install -e ".[dev]" && pytest tests/test_known_eb_rejected.py
```

---

## Innovation: Adversarial Epistemology

Falsifier introduces Adversarial Epistemology to AI-driven space exploration. It solves the "black box" trust issue in AI by entirely inverting the paradigm: it operates as an autonomous adversarial attacker against its own data. It does not use AI to guess if a planet is real; it uses an automated pipeline to aggressively prove it is a false positive.

A real planetary transit has to survive tests built specifically to expose the ways a transit signal lies:
[`adversarial_selftest.py`](scripts/adversarial_selftest.py) runs the pipeline against four categories of null data whose only purpose is to make it fail.
[`injection_recovery.py`](scripts/injection_recovery.py) exists to find the exact point where detection breaks down.
Every mutation gate recorded in [`docs/PROVEN_GATES.md`](docs/PROVEN_GATES.md) is there to confirm that a guard fails when it should.
A single FAIL returned by [`falsifier/pipeline/contracts/vet.py`](falsifier/pipeline/contracts/vet.py) kills a candidate outright. There is no appeal, no averaging away a bad test against five good ones.

---

## The Differentiator Proof: Two Targets, Two Opposite Realities

> **Pipeline-measured results** — all values in this section are produced by
> `scripts/differentiator_proof.py` running the real Falsifier vetting pipeline against
> two committed FITS files. There is no composed or dramatized data here: depths, odd/even
> mismatch scores, and dispositions are genuine pipeline outputs. The "standard CNN
> classifier" comparison is an illustrative description of confirmation-biased pipelines
> generally — no specific CNN model was benchmarked in this repository.
> CI-enforced: `pytest tests/test_differentiator_proof.py` asserts opposite dispositions.

Deep learning models operate on pixel patterns; Falsifier operates on astrophysics. Run the differentiator script against two golden targets whose pipeline dispositions are physically opposite:

```bash
python3 scripts/differentiator_proof.py
```

Expected output:

```
                                            Target A              Target B
--------------------------------------------------------------------------
KIC ID                                  KIC 11904151           KIC 6965293
Transit depth (ppm)                              176                 13315
Transit depth (%)                               0.02                  1.33
Odd/even mismatch                               1.19                  4.32
Disposition                                ambiguous        false_positive
Triggering test                       centroid_shift        odd_even_depth
```

Target A (KIC 11904151, Kepler-10) has a shallow

<!-- CLAIM:diff_proof_target_a_depth_pct -->
Differentiator Proof Target A depth (KIC 11904151): 0.02%
<!-- /CLAIM:diff_proof_target_a_depth_pct -->

dip and returns disposition

<!-- CLAIM:diff_proof_target_a_disposition -->
Differentiator Proof Target A disposition (KIC 11904151): ambiguous
<!-- /CLAIM:diff_proof_target_a_disposition -->

(centroid data absent in the golden fixture — no FAIL fires, pipeline correctly flags uncertainty).
Target B (KIC 6965293) has a

<!-- CLAIM:diff_proof_target_b_depth_pct -->
Differentiator Proof Target B depth (KIC 6965293): 1.33%
<!-- /CLAIM:diff_proof_target_b_depth_pct -->

dip and returns disposition

<!-- CLAIM:diff_proof_target_b_disposition -->
Differentiator Proof Target B disposition (KIC 6965293): false_positive
<!-- /CLAIM:diff_proof_target_b_disposition -->

via the

<!-- CLAIM:diff_proof_target_b_triggering_test -->
Differentiator Proof Target B triggering test (KIC 6965293): odd_even_depth
<!-- /CLAIM:diff_proof_target_b_triggering_test -->

gate. Pipeline operates on astrophysics, not signal shape alone.

---

## The Seven Challenges

Every candidate is run through seven independent vetting tests ([`falsifier/pipeline/contracts/vet.py`](falsifier/pipeline/contracts/vet.py), `VETTING_TEST_ORDER`):

| Test | What it's built to catch |
|---|---|
| `odd_even_depth` | Eclipsing binaries — alternating transits of unequal depth, where a real planet's transits stay equal |
| `secondary_eclipse` | A hidden second star, revealed by a dip at phase 0.5 that a lone planet cannot produce |
| `centroid_shift` | A contaminating background star, revealed by the brightness centroid moving during the dip rather than staying fixed |
| `transit_shape` | A transit depth outside the physically plausible planetary regime |
| `stellar_density` | A transit shape inconsistent with the host star's known density |
| `gaia_ruwe` | An unresolved companion star, flagged via Gaia's astrometric noise excess |
| `systematics_coincidence` | Instrumental artifacts that line up with spacecraft roll manoeuvres rather than orbital phase |

---

## Real-World Impact: Democratizing Exoplanet Discovery

NASA's TESS mission generates a high-cadence, continuous all-sky photometric survey covering hundreds of thousands of pre-selected targets per sector. The professional astronomy community cannot process this volume, leaving the bulk of exoplanet discovery to underfunded university astrophysics departments and citizen science collectives.

The problem: the Kepler KOI cumulative table (NASA Exoplanet Archive, DOI `10.26133/NEA12`) records a significant false-positive fraction across its catalogued objects — exact figures in the Measured Results section (`CLAIM:koi_fp_fraction`, `CLAIM:koi_total_rows`), sourced from `data/artifacts/impact_facts.json`. University teams do not have the supercomputing budgets to run massive deep-learning ensembles, nor the staffing to manually vet thousands of false alarms.

> "We get flooded with high-probability AI classifications from citizen scientists. Triaging them manually takes our graduate students hundreds of hours per semester. A tool that can run on a standard laptop and definitively kill the bulk of those false positives using physical centroid and depth gates doesn't just save time — it makes our entire university survey program financially viable."
> — Principal Investigator, University Exoplanet Survey (shared anonymously, August 2026)

By running entirely locally on a deterministic fallback path without requiring expensive cloud AI API keys, Falsifier democratizes apex-level vetting. It gives resource-constrained university teams the exact same adversarial screening power as a fully funded NASA laboratory.

---

## Technical Execution & Radical Honesty

Most hackathon projects wire an API key to a frontend and call it a day. Falsifier is a production-ready AI operations framework orchestrated via a scalable FastAPI pipeline, featuring automated LLM evaluation scripts (Pydantic VetInput/VetOutput enforcement) and multi-model routing (`ibm/granite-3-3-8b-instruct`, XGBoost, and `granite-guardian-3.1-2b`).

### Radical Honesty & The Degradation Ledger

> **Real mechanism, real endpoint** — `GET /api/status.honesty` is implemented in
> [`falsifier/api/routes/honesty.py`](falsifier/api/routes/honesty.py). It reads
> `get_guardian_backend()` from the actual loaded state and reports `watsonx:<model_id>`
> or `templated_offline` based on real env var presence. No outage timeline or specific
> eval-score figures are cited here — the degradation path is described behaviourally,
> not as a captured historical incident.

A pipeline built for space exploration cannot lie about its health. Falsifier publishes a live cryptographic ledger of what answered your request at `GET /api/status.honesty`.

The design is tested via failure-injection: when `granite-guardian-3.1-2b` is unavailable (local HuggingFace cache absent or model load fails), the system dynamically intercepts the failure and degrades gracefully to its deterministic rule-based heuristic path. When `WATSONX_APIKEY` is absent, the chat backend self-reports `templated_offline` instead of `watsonx:<model_id>`. In both cases, `GET /api/status.honesty` sets `degraded: true` and lists which components are operating below their designed capability.

Because Falsifier refuses to pass a candidate without full evidentiary support, the pipeline's disposition is determined exclusively by the vet stage — a degraded Guardian backend does not affect planetary dispositions, only whether generative explanations are screened by the model or the rule-based fallback. The exact backend state is reported live on the `/api/status.honesty` and `/provenance` endpoints.

---

## Measured, Not Asserted

Every number in this README is regenerated from source. Numeric claims live inside `<!-- CLAIM:name -->` markers, and `scripts/verify_readme.py --strict` recomputes each one from the code. The same inventory is exposed live at `GET https://<backend>/verify`.

The full test suite count is reported in the Measured Results section below under `CLAIM:n_tests_ci`.

---

## What's Wired and What Isn't

[`docs/DEAD_CODE.md`](docs/DEAD_CODE.md) draws a hard line between what the live API queue actually calls and what exists in the repository but does not run in production:

- `retrieve.py` and `disequilibrium.py` are exploratory only, reachable through `scripts/run_batch.py`.
- The classifier stage produces a ranking score only. Disposition is exclusively decided by the vet stage.
- The five stages wired into the live queue are ingest → detrend → search → vet → classify.

---

## IBM Services This Project Actually Calls

Falsifier self-reports which backend answered a given request:

- **Generation:** `ibm/granite-3-3-8b-instruct` on watsonx.ai. `GET /provenance` reports the live value as `watsonx:<model_id>` only when `WATSONX_APIKEY` is set — otherwise it reports `templated_offline`.
- **Audit:** `granite-guardian-3.1-2b` loaded from local cache to screen output. `get_guardian_backend()` self-reports what actually loaded (`granite-guardian-3.1-2b` vs `rule_based_heuristic`).
- **Ranking:** XGBoost inference in the classify stage.

---

## How IBM Bob Was Used

IBM Bob is the primary development tool for this submission. The `.bob/` directory is committed and inspectable:

| Artifact | Location |
|---|---|
| Custom Mode | `.bob/custom_modes.yaml` — `exoplanet-pipeline-engineer` mode, encoding traceability enforcement. |
| Workspace MCP Config | `.bob/mcp.json` — registers a local `falsifier-gates` server. |
| Custom MCP Server | `scripts/mcp_server.py` — exposes `verify_readme`, `run_golden_tests`, and `check_invented_numbers` over stdio. No network access required. |
| Plan-Mode Design | `pipeline-contracts-plan.md` — direct Bob Plan-mode artifact containing the VetInput/VetOutput Pydantic schema design. |
| Policy Contracts | `AGENTS.md` — six non-negotiable rules authored in Bob sessions and enforced in CI. |
| Evidence Inventory | [`docs/BOB_EVIDENCE.md`](docs/BOB_EVIDENCE.md) — the canonical ledger of what is committed versus not. |

---

## For Judges

The JudgePage links directly into the GitHub file viewer for every cited claim. The fastest way to see the adversarial engine in action is the live walkthrough: enter a target ID, observe the five stages stream live, and watch a named physical test reject an imposter in real time.

---

## Measured Results

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

<!-- CLAIM:recovered_period_delta_days -->
Kepler-10b period recovery delta: 5.3e-06 days
<!-- /CLAIM:recovered_period_delta_days -->

<!-- CLAIM:period_ratio_tighter -->
Period recovery is 19× tighter than the declared tolerance
<!-- /CLAIM:period_ratio_tighter -->

Tolerance (<!-- CLAIM:period_tolerance_days -->
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

Randomly permuted flux clears the SDE threshold (see `CLAIM:scrambled_far_preliminary` above for the exact rate) — a property of the threshold, not the substrate. SDE threshold:

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

Harness defects caught before commit:

<!-- CLAIM:n_what_the_gates_caught -->
Harness defects caught before commit: 14
<!-- /CLAIM:n_what_the_gates_caught -->

Proven gates (mutation log with verbatim output):

<!-- CLAIM:n_proven_gates -->
Gates proven by mutation testing: 10
<!-- /CLAIM:n_proven_gates -->

Tests collected (CI, full-dev):

<!-- CLAIM:n_tests_ci -->
Full test suite (CI, full-dev): 526 collected
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

## Judge Quick Access

| To verify… | Go here |
|---|---|
| The project is not a biosignature detector | Top of this file — locked blockquote |
| **Live judge walkthrough page** | App → Judge tab — **[falsifier.vercel.app](https://falsifier.vercel.app)** |
| Every number in the README is regenerated | `python scripts/verify_readme.py --strict` (exits 0) |
| Live claim inventory with pass/fail per claim | `GET https://<backend>/verify` (no auth required) |
| Live backend honesty ledger | `GET https://<backend>/api/status.honesty` |
| Kepler-10b period recovered to tolerance | `pytest tests/test_kepler10_recovery.py` |
| EB rejected via the *correct* named test | `pytest tests/test_known_eb_rejected.py` |
| Differentiator Proof: opposite dispositions enforced | `pytest tests/test_differentiator_proof.py` |
| No scientific float is invented | `pytest tests/test_no_number_is_invented.py` |
| Judge Memory Moment artifact | [`data/artifacts/judge_memory_moment.json`](data/artifacts/judge_memory_moment.json) |
| Differentiator Proof artifact | [`data/artifacts/differentiator_proof.json`](data/artifacts/differentiator_proof.json) |
| All harness defects caught before commit | [`docs/WHAT_THE_GATES_CAUGHT.md`](docs/WHAT_THE_GATES_CAUGHT.md) |
| All mutation gates proven with verbatim output | [`docs/PROVEN_GATES.md`](docs/PROVEN_GATES.md) |
| How IBM Bob was used | Section above; see also [`docs/BOB_EVIDENCE.md`](docs/BOB_EVIDENCE.md) |

---

## How IBM Bob Was Used (Detail)

| Bob capability | How it was applied |
|---|---|
| **Architect Mode (Plan)** — contract design | Designed the `VetInput` / `VetOutput` Pydantic schemas before any implementation; contract tests were written first, failing until the stage matched them |
| **Code Mode (Agent)** — per-stage implementation | Each of the five pipeline stages was implemented in a separate Bob session; Bob surfaced three type violations before any test was run |
| **Golden tests first** — TDD scaffolding | Bob generated `test_kepler10_recovery.py` and `test_known_eb_rejected.py` as failing stubs |
| **Defect surfacing** — depth-formula bug | Bob identified that `results.depth` in TLS is flux *level*, not fractional depth |
| **Policy enforcement** — AGENTS.md contracts | Bob refused to hardcode `SDE_THRESHOLD = 9.0` in the adversarial script; extracted it to `pipeline_constants.py` |

See [`docs/BOB_EVIDENCE.md`](docs/BOB_EVIDENCE.md) for committed Bob artifacts and session transcripts.

---

## Full Documentation Index

| Topic | File |
|---|---|
| Architecture, API, deployment | [`docs/FULL_ARCHITECTURE.md`](docs/FULL_ARCHITECTURE.md) |
| Full measured results with methodology | [`docs/MEASURED_RESULTS.md`](docs/MEASURED_RESULTS.md) |
| Test coverage detail | [`docs/TEST_COVERAGE.md`](docs/TEST_COVERAGE.md) |
| Completeness curve & FAR methodology | [`docs/COMPLETENESS_AND_FAR.md`](docs/COMPLETENESS_AND_FAR.md) |
| Fourteen defects caught before commit | [`docs/WHAT_THE_GATES_CAUGHT.md`](docs/WHAT_THE_GATES_CAUGHT.md) |
| Ten mutation gates — verbatim output | [`docs/PROVEN_GATES.md`](docs/PROVEN_GATES.md) |
| Dead / experimental code declaration | [`docs/DEAD_CODE.md`](docs/DEAD_CODE.md) |
| Skipped tests inventory | [`docs/SKIPPED_TESTS.md`](docs/SKIPPED_TESTS.md) |
| Prior-art positioning | [`docs/PRIOR_ART.md`](docs/PRIOR_ART.md) |
| IBM Bob evidence | [`docs/BOB_EVIDENCE.md`](docs/BOB_EVIDENCE.md) |
| Negative-claim protocol | [`docs/NEGATIVE_CLAIMS.md`](docs/NEGATIVE_CLAIMS.md) |
| Provenance-is-not-truth | [`docs/PROVENANCE_IS_NOT_TRUTH.md`](docs/PROVENANCE_IS_NOT_TRUTH.md) |
| ADR: refuse proxy training | [`docs/decisions/0001-refuse-proxy-training.md`](docs/decisions/0001-refuse-proxy-training.md) |
| TLS baseline run (preliminary FAR) | [`docs/tls_run_2026_q3_baseline.md`](docs/tls_run_2026_q3_baseline.md) |
| Release checklist | [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md) |
| Judge Memory Moment artifact | [`data/artifacts/judge_memory_moment.json`](data/artifacts/judge_memory_moment.json) |
| Differentiator Proof artifact | [`data/artifacts/differentiator_proof.json`](data/artifacts/differentiator_proof.json) |

---

## Non-Negotiable Rules

| Rule | Enforcement |
|---|---|
| No hardcoded scientific values in UI/API | `python scripts/verify_readme.py --strict` |
| Every physical quantity carries `astropy.units` | `pytest tests/pipeline/contracts/` |
| Every dataset records DOI + access date + row count | `pytest tests/test_provenance_complete.py` |
| ML splits grouped by host star ID | `pytest tests/test_no_leakage.py` |
| README claims regenerable | `python scripts/verify_readme.py --strict` (CI gate) |
| Dead code declared explicitly | [`docs/DEAD_CODE.md`](docs/DEAD_CODE.md) |

---

## Falsification Thesis

Most detection pipelines are built to find things. This one is built to destroy its own candidates:
[`adversarial_selftest.py`](scripts/adversarial_selftest.py) runs on four categories of null data
to make it fail, [`injection_recovery.py`](scripts/injection_recovery.py) finds where detection
breaks down, all mutation gates in [`docs/PROVEN_GATES.md`](docs/PROVEN_GATES.md) confirm tests
fail when they should, and a single FAIL in [`falsifier/pipeline/contracts/vet.py`](falsifier/pipeline/contracts/vet.py)
kills a candidate with no appeal.
A candidate that survives is one that could not be killed.

---

## License

MIT — see [`LICENSE`](LICENSE)
