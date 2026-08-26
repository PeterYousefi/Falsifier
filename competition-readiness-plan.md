# Competition-Readiness Plan — IBM AI Builders Challenge 2026
## Falsifier · August 2026

> **Implementation order: Tasks 0 → 1 → 2 → 3a → 3b → 4 → 5 (HELD) → 6.**
> Each task is a self-contained commit block. No task touches code outside its scope.
> Task 5 is HELD pending exact AGENTS.md Rule 6 branch-exception wording approval.

---

## Task 0 — AGENTS.md compliance map

Maps every task to the rules it touches and resolves known collisions.

### Rule mapping

| Task | Rule touched | Verdict |
|---|---|---|
| 1 — Close README drift | Rule 5 (no hand-edited numbers); Rule 6 (dead-code table update needed if SKIPPED_TESTS changes what is "live") | Complies if fixed via source of truth + `verify_readme.py` regeneration. New test adds a gate but does not edit a number. |
| 2 — Reframe classify | Rule 6 (dead-code table changes); Rule 1 (no numbers added to UI/API) | Complies as docs-only + dead-code table update in same commit. |
| 3a — FAR artifact | Rule 1 (numbers must come from committed artifact); Rule 3 (manifest mandatory); Rule 5 (CLAIM blocks regenerable) | Complies: script writes artifact → artifact is committed → CLAIM block regenerated from it. |
| 3b — Completeness shard | Same as 3a | Complies same way. |
| 4 — Validation past n=2 | Rule 1 (numbers from artifact); Rule 3 (manifest); Rule 4 (ML splits grouped — N/A, no training); Rule 5 (CLAIMs regenerable) | Complies. No threshold tuning allowed. |
| 5 — Branch exploratory half | Rule 6 (dead-code table shrinks; must be updated in same commit); Rule 5 (README rows removed must also be removed from CLAIM registry if they were registered) | Complies if dead-code table and README stochastic rows are updated in the same commit. |
| 6 — Rewrite README front matter | Rule 1 (no hardcoded numbers); Rule 5 (every new number in a CLAIM block with named source) | Complies if Prša 6.68 ratio is sourced from MANIFEST.json and all other new numbers go through CLAIM blocks. |

### Known collision resolutions

**Rule 5 × Task 1 (hand-edited numbers):**
The three drifts (n_proven_gates renders 7 but table has 6 rows; SKIPPED_TESTS.md described as "all resolved"; Classify described as deterministic "given committed model artifact") must be fixed at the source of truth, not by editing the CLAIM block body.

- `n_proven_gates`: The CLAIM reads 7. `_regen_n_proven_gates()` counts `✅ EXECUTED` table rows in `PROVEN_GATES.md` — the audit table has exactly 7 such rows (verified). The CLAIM value is correct. **The drift is in the gate-table in README (lines 927–932: 6 rows, not 7) and in the repository layout comment (line 1012: "6 gates").** Fix: add the Gate 7 (phase-zero t0) row to the README gate-table and update the layout comment to "7 gates" — these are prose/table fixes that do not edit a CLAIM block body, so Rule 5 is satisfied.
- `SKIPPED_TESTS.md "all resolved"` (README line 1013): The body of SKIPPED_TESTS.md documents 12 tests still skipping on an unresolved skew. Fix: update the repository layout description to "12 tests pending train/serve skew resolution" — prose fix, no CLAIM block involved.
- `Classify "deterministic given committed model artifact"` (README line 635 reproducibility table): no committed model exists. Fix: update this cell to state "no committed model; classify stage is wired but blocked — see docs/SKIPPED_TESTS.md".

**Rule 6 × Tasks 2 and 5 (dead-code table):**
- Task 2 (docs-only reframe): The dead-code table entry for `classify.py` already exists. The wording changes but no module moves. Dead-code table update goes in the same commit as the docs changes.
- Task 5 (branch out exploratory): The dead-code table rows for `retrieve.py`, `disequilibrium.py`, `batch/runner.py` will be removed when those modules leave main. The table must be updated in the same commit that removes the modules. The README exploratory sections and stochastic rows are removed in the same commit.

**Rule 1 / Rule 5 × Tasks 3, 4, 6 (new numbers):**
- Task 3: Every FAR and recovery fraction must be written by the script to a committed JSON artifact. The CLAIM block reads from that artifact. No number may appear in README before the artifact is committed.
- Task 4: The confusion matrix is written to a committed JSON artifact by the evaluation script. CLAIM blocks regenerate from it.
- Task 6: The Prša 6.68 ratio is already in `MANIFEST.json` → already behind a CLAIM block (`eb_depth_ratio`). Any new numeric claim (e.g., hero scenario numbers) must either reuse an existing CLAIM or add a new one with a named source.

### Task 5 — HELD: proposed Rule 6 branch-exception wording

Before Task 5 is approved, the following amendment must be presented verbatim for user sign-off.
Constraints it must satisfy: covers ONLY code removed from main to a named branch (not merely
"documented somewhere"); requires branch name + removal reason in README; must NOT weaken Rule 6
generally.

**Proposed wording (addition to AGENTS.md Rule 6, new paragraph after the existing one):**

> **Branch exception — exploratory modules:** A module removed from `main` in its entirety and
> moved to a named long-lived branch satisfies Rule 6 for the `main` branch, provided the README
> dead-code table is updated **in the same commit** to include: (a) the module path, (b) the
> branch name it was moved to, and (c) one sentence explaining why it is not on `main`. A module
> that is merely unreachable — but still present on `main` — does not qualify for this exception
> and must be listed individually under Dead / Experimental Code with a wiring explanation.

**AGENTS.md amendment ships in the same commit as the exploratory module move.**

### CLAIM:n_curated_targets removal (Task 5 pre-condition)
`verify_readme.py` exits 2 on an unregistered CLAIM block. Removing `n_curated_targets` requires:
1. Remove the `<!-- CLAIM:n_curated_targets -->` block from README.
2. Remove `"n_curated_targets": _regen_n_curated_targets` from `CLAIM_REGISTRY` in `scripts/verify_readme.py`.
3. Remove `_regen_n_curated_targets` function from `scripts/verify_readme.py`.
All three changes in the same commit that moves `data/targets/curated_targets.json` to the branch.

### Status
- [ ] HELD — awaiting Rule 6 amendment wording approval

---

## Task 1 — Close the README claim drift

### Intent
Three factual contradictions between the README and committed state violate Rule 5 (claims must be regenerable from committed state). Fix all three at the source of truth. Add a structural gate that prevents prose tables from contradicting registered CLAIM blocks.

### Identified drifts (evidence-grounded)

| Drift | Committed truth | README says |
|---|---|---|
| Gate-table row count vs `n_proven_gates` | PROVEN_GATES.md audit table: 7 rows with `✅ EXECUTED` (lines 15–21). `_regen_n_proven_gates()` correctly returns 7. CLAIM:n_proven_gates correctly renders 7. README gate-summary table (lines 925–932) has only **6 data rows** — Gate 7 (phase-zero t0) is missing. | CLAIM is correct; visible table has 6 rows, missing Gate 7 |
| Repository layout — PROVEN_GATES.md description | 7 gates, verbatim output | "6 gates, verbatim failure output" (line 1012) |
| Repository layout — SKIPPED_TESTS.md description | 12 tests pending train/serve skew | "all resolved" (line 1013) |
| Reproducibility table — Classify row | No committed model; stage is wired but blocked | "Deterministic given committed model artifact" (line 635) |

**CLAIM:n_proven_gates is NOT touched** — it renders 7 and that is correct. The fix targets only prose/table drift.

### Acceptance criteria
1. `python scripts/verify_readme.py --strict` exits 0 (no drift, no unregistered block).
2. The README gate-summary table has 7 data rows; Gate 7 (phase-zero t0 convention) is present.
3. Repository layout line reads "7 gates, verbatim failure output".
4. Repository layout SKIPPED_TESTS.md line reads "12 tests pending train/serve skew resolution".
5. Classify row in reproducibility table reads: "No — no committed model; training blocked by train/serve feature skew (see docs/SKIPPED_TESTS.md)".
6. `tests/test_readme_tables_match_claims.py` asserts bidirectionally: (a) parse integer from `CLAIM:n_proven_gates` block; (b) count data rows in the README gate-summary table; (c) assert equal. Test fails if a row is deleted AND fails if the CLAIM is hand-edited to a wrong number.
7. `verify-readme` CI job runs the new test (`pytest tests/test_readme_tables_match_claims.py -v` step added).
8. `docs/WHAT_THE_GATES_CAUGHT.md` entry 10: "README prose drift — gate-summary table had 6 rows while CLAIM:n_proven_gates rendered 7; verify_readme.py only checked registered CLAIM blocks, leaving prose tables free to contradict them. Fix: added test_readme_tables_match_claims.py."

### Todo list
1. Add Gate 7 row to README gate-summary table (lines 925–932): "Phase-zero t0 convention | phased LC centroid displaced > HALF_BIN when t0 off by one Kepler long-cadence | Analytical | Yes".
2. Update repository layout line 1012: "6 gates" → "7 gates, verbatim failure output".
3. Update repository layout line 1013 for SKIPPED_TESTS.md: "all resolved" → "12 tests pending train/serve skew resolution".
4. Update Classify row in reproducibility table (line 635): replace "Yes | Deterministic given committed model artifact" with "No — no committed model; training blocked by train/serve feature skew (see docs/SKIPPED_TESTS.md)".
5. Write `tests/test_readme_tables_match_claims.py` with bidirectional assertion (stdlib only — no falsifier import, no network).
6. Add step to `verify-readme` CI job: `pytest tests/test_readme_tables_match_claims.py -v` (pip install pytest already present in that job).
7. Add entry 10 to `docs/WHAT_THE_GATES_CAUGHT.md`.

### Relevant context
- `scripts/verify_readme.py` → `_regen_n_proven_gates()` (line 259): counts `|` lines with `✅ EXECUTED`
- `docs/PROVEN_GATES.md` lines 13–21: audit table — 7 rows, all `✅ EXECUTED`
- `README.md` lines 916–918: `CLAIM:n_proven_gates` renders 7 (correct)
- `README.md` lines 925–933: gate-summary table — 6 data rows (missing Gate 7)
- `README.md` line 1012: "6 gates" (wrong)
- `README.md` line 1013: "all resolved" (wrong — 12 tests still skip)
- `README.md` line 635: "Deterministic given committed model artifact" (wrong — no artifact)
- `.github/workflows/ci.yml`: `verify-readme` job to be extended

### Status
- [ ] pending

---

## Task 2 — Reframe classify as a scope decision, not a blocker

### Intent
The pipeline description in README and docs should accurately describe Falsifier as a deterministic false-positive triage pipeline whose vet stage uses a truth table. The classify stage is wired but deliberately held behind a guard, not broken. SKIPPED_TESTS.md should read as a documented design decision with reasoning, not an open TODO.

**Approved: docs-only.** queue.py, test_api_deletion.py, and CLAIM:n_pipeline_stages are untouched.
The classify stage fires only when `req.run_classify` is true AND `vet_outs` is non-empty — the
default live path is ingest → detrend → search → vet. Classify is opt-in, guarded by a deliberate
refusal to train on skewed features. That is what the code does; describe it accurately.

### Acceptance criteria
1. `docs/SKIPPED_TESTS.md`: the 12 skipped tests are framed as a deliberate refusal — section titled "Deliberate training refusal" with full reasoning. No "TODO" or "pending resolution" language.
2. README dead-code table classify.py row: describes deliberate guard, not "no valid model committed."
3. README IBM AI Builders submission summary: describes default path (ingest → detrend → search → vet) + classify as opt-in, guarded. No "fifth stage … has no committed model."
4. No changes to queue.py, test_api_deletion.py, CLAIM:n_pipeline_stages.
5. `python scripts/verify_readme.py --strict` exits 0.

### Todo list
1. Rewrite `docs/SKIPPED_TESTS.md` section 1–12: title "Deliberate training refusal — train/serve feature skew"; explain why training on DR25 proxies produces a model that is strictly worse than no model at inference (calibrated to wrong scale → probability is meaningless → downstream decisions on false output); note that the guard `NotImplementedError` is the correct behaviour, not a missing feature.
2. Update README dead-code table classify.py row: "Wired via API queue (opt-in); deliberately not trained — classifier training is blocked by a confirmed train/serve feature skew defect; training on DR25 proxies would produce a meaningless probability at inference (see docs/SKIPPED_TESTS.md)".
3. Update README IBM AI Builders submission summary: "Falsifier runs four deterministic pipeline stages — ingest, detrend, period search, and seven-test vetting — on any Kepler/TESS target and outputs a disposition with a traceable reason. A fifth stage (classify) is opt-in and deliberately not trained: the classifier's feature extractor reads vet-stage metric_value fields that no DR25 column maps to; training on proxies would produce a meaningless probability. The guard is intentional, not a placeholder."
4. Run `python scripts/verify_readme.py --strict` — must exit 0.

### Relevant context
- `falsifier/api/queue.py` lines 480–489: classify runs only when `req.run_classify` is true
- `scripts/train_classifier_dr25.py`: raises `NotImplementedError` with full explanation
- `tests/test_train_classifier_dr25.py`: asserts the guard fires
- `docs/SKIPPED_TESTS.md` lines 24–80: current skew documentation

### Status
- [ ] pending

---

## Task 3a — Commit the adversarial FAR artifact (TLS, Q3 quiet stars)

### Intent
Commit the first real measured FAR numbers under TLS, all five replacement quiet stars, Q3 files.
Run five stars × 20 trials = 100 per category; report per-star FAR. `off_target` reported in prose
only (structural reason: cyclic permutation preserves periodicity regardless of substrate).
**Hard write-gate**: if `detection_algorithm != "TLS"`, the script must raise and write nothing.

### Pre-conditions
- All five replacement quiet stars (KIC 1161145, KIC 5084157, KIC 7272437, KIC 7347849, KIC 8935630) Q3 FITS fetched to `data/golden/` (30–120 s each).
- The pilot shard `data/artifacts/pilot_shards/injection_recovery_kic_7272437.json` is invalidated (BLS_fallback) and must NOT be promoted.
- `transitleastsquares` must be installed (`python -c "import transitleastsquares"`).

### Hard write-gate (new, required)
`scripts/adversarial_selftest.py` must be modified to **raise `SystemExit(1)` and write no artifact** if `detection_algorithm != "TLS"` at the point of writing output. This is a pre-write guard, not a post-hoc test. Add the same guard to `scripts/injection_recovery.py`. Document this as a new entry in `docs/WHAT_THE_GATES_CAUGHT.md` under "structural guards added."

### Acceptance criteria
1. `adversarial_selftest.py` and `injection_recovery.py` both raise and exit 1 before writing if TLS is not the detector (write-gate).
2. `scripts/adversarial_selftest.py` run on all five Q3 files; artifact has `"detection_algorithm": "TLS"`.
3. Artifact committed to `data/artifacts/adversarial_selftest.json` with manifest sidecar.
4. CLAIM blocks registered for `adversarial_far_scrambled`, `adversarial_far_sign_inverted`, `adversarial_far_blank_sky`; each sourced from artifact, labelled with n and Wilson 68% CI.
5. `off_target` reported in README prose only, with explicit statement: "cyclic permutation preserves periodicity; this category is not a substrate-independent FAR measurement."
6. If any individual star shows an anomalous detection in scrambled/sign_inverted/blank_sky, the star is named — no pooling without disclosure.
7. `tests/test_adversarial_selftest.py::test_detection_algorithm_is_tls` passes.
8. `python scripts/verify_readme.py --strict` exits 0.

### Todo list
1. Add write-gate to `scripts/adversarial_selftest.py`: before `json.dump`, check `detection_algorithm == "TLS"` and raise `SystemExit("ABORT: detection_algorithm is not TLS — refusing to write artifact")` if not.
2. Add same write-gate to `scripts/injection_recovery.py`.
3. Document both guards in `docs/WHAT_THE_GATES_CAUGHT.md` as "structural guards added after defect 7 recurred in pilot shard."
4. Fetch Q3 FITS for all five replacement quiet stars if not present.
5. Run `python scripts/adversarial_selftest.py --seed 42 --n-trials 20 --output-dir data/artifacts --data-dir data/golden --no-plot`.
6. Inspect artifact: verify `detection_algorithm == "TLS"`; check `off_target` trials; name any anomalous per-star detections.
7. Register CLAIM blocks + `_regen_*` functions in `scripts/verify_readme.py`.
8. Commit all changes. Run `python scripts/verify_readme.py --strict`.

### Relevant context
- `scripts/adversarial_selftest.py`: already implements all four categories; needs TLS installed
- `scripts/pipeline_constants.py`: canonical `DEFAULT_QUIET_STARS`, `SDE_THRESHOLD`
- `data/golden/`: committed FITS files — verify which Q3 files exist before running
- `tests/test_adversarial_selftest.py::test_detection_algorithm_is_tls`: gate that must pass

### Status
- [ ] pending

---

## Task 3b — Commit a partial completeness curve (single star, Q3)

### Intent
Commit a single-star completeness shard on the committed Q3 FITS. Five injections per cell, reduced grid (not the full 45-job matrix). Label it explicitly as a single-star pilot. Register the recovery fractions as CLAIM blocks.

### Scope constraints
- Do NOT run the 45-job matrix. One star, the committed Q3 FITS (KIC 7272437 Q3, ~3633 cadences).
- Use the full depth grid but reduced injections: 5 per cell instead of 30 (`--n-per-cell 5 --seed 42`).
- The write-gate added in Task 3a (raise + exit 1 if detection_algorithm != "TLS") is already present.
- The pilot shard in `data/artifacts/pilot_shards/injection_recovery_kic_7272437.json` is invalidated (BLS_fallback) and must NOT be promoted — run fresh.

### Acceptance criteria
1. Artifact `data/artifacts/completeness_pilot_kic7272437_q3.json` committed with `"detection_algorithm": "TLS"`.
2. Manifest sidecar committed with `source_doi`, `access_date`, `row_count`.
3. `tests/test_injection_recovery.py::test_detection_algorithm_is_tls` passes on the committed artifact.
4. Recovery fractions for at least three depth values are registered as CLAIM blocks with a label "single-star pilot, KIC 7272437 Q3, n=5 per cell".
5. README clearly labels the data as a single-star pilot, not the full matrix.
6. `python scripts/verify_readme.py --strict` exits 0.

### Todo list
1. Run: `python scripts/injection_recovery.py --seed 42 --n-per-cell 5 --depth-filter all --output-dir data/artifacts --output-name completeness_pilot_kic7272437_q3 --data-dir data/golden --checkpoint-dir /tmp/checkpoints --no-plot`
2. Inspect artifact: assert `detection_algorithm == "TLS"`.
3. Extract recovery fractions per depth. Register `completeness_pilot_*` CLAIM blocks (one per depth point or a summary fraction).
4. Add `_regen_*` functions in `scripts/verify_readme.py`.
5. Add "Completeness pilot (single star)" section to README Measured Results.
6. Commit artifact + sidecar + README + verify_readme.py changes.
7. Run `python scripts/verify_readme.py --strict` — must exit 0.

### Relevant context
- `scripts/injection_recovery.py`: full harness; supports `--n-per-cell`, `--depth-filter`
- `data/golden/kic_7272437_q3_long.fits`: committed Q3 FITS; SHA-256 pinned
- `data/artifacts/pilot_shards/injection_recovery_kic_7272437.json`: INVALIDATED (BLS_fallback, detection_algorithm ≠ TLS) — do not use

### Status
- [ ] pending

---

## Task 4 — Take validation past n=2

### Intent
Expand the golden test set from 2 targets to ~10 KOIs with known dispositions (balanced confirmed vs. false positive). Run the pipeline, commit a vet-stage confusion matrix, register it. Analyse each miss by name and triggering test. Do NOT tune thresholds.

### Selection criteria
- ~10 KOIs from the NASA Exoplanet Archive `cumulative` table.
- Roughly balanced: ~5 confirmed planets, ~5 known false positives.
- No overlap with existing golden set (KIC 11904151 / Kepler-10, KIC 6965293).
- MAST Q3 coverage confirmed before selection (verifiable via astroquery before any FITS fetch).
- Not in the old contaminated list (KIC 3425851, KIC 5514383, KIC 9410930, KIC 10963065).

### Acceptance criteria
1. ~10 new KOIs added to MANIFEST.json with `source_doi`, `access_date`.
2. FITS files fetched and committed (or fetched at CI time with pinned product IDs).
3. Pipeline run on each new target; vet-stage output recorded.
4. Confusion matrix committed as `data/artifacts/validation_matrix.json`.
5. CLAIM blocks for precision, recall (or TP/FP/FN/TN counts) sourced from the committed artifact.
6. Each miss documented by name and triggering test in README or in a new `docs/VALIDATION_MISSES.md`.
7. No threshold was tuned during this task (no changes to `pipeline_constants.py` SDE_THRESHOLD or vet-stage thresholds).
8. `python scripts/verify_readme.py --strict` exits 0.

### Todo list
1. Query NASA Exoplanet Archive `cumulative` table for ~10 KOIs with confirmed/false-positive dispositions, balanced, with MAST Q3 coverage. Verify no KOI entry for KIC IDs of interest. Record selections in a candidate list.
2. Add new MANIFEST.json entries for selected targets.
3. Fetch Q3 FITS via `python scripts/fetch_golden.py` for each new target.
4. Write `scripts/validate_koi_set.py` (or extend an existing script) to run the pipeline on the new targets and write `data/artifacts/validation_matrix.json` with TP/FP/FN/TN counts and per-target vet output.
5. Commit artifact + manifest sidecar.
6. Register CLAIM blocks (`validation_tp`, `validation_fp`, `validation_fn`, `validation_tn` or `validation_precision`, `validation_recall`).
7. Add per-miss analysis (name + triggering test + reason) to README or docs/VALIDATION_MISSES.md.
8. Run `python scripts/verify_readme.py --strict` — must exit 0.

### Constraint
No threshold tuning. A miss with a documented reason is the correct output.

### Relevant context
- `data/golden/MANIFEST.json`: add new entries here
- `scripts/fetch_golden.py`: FITS fetcher, now exits 1 on failed fetch
- `falsifier/pipeline/stages/vet.py`: deterministic truth table
- `tests/test_known_eb_rejected.py`: existing golden EB test — new test pattern

### Status
- [ ] pending

---

## Task 5 — Branch out the exploratory half

### Intent
Move the exploratory (stochastic, unvalidated) modules off main. Main's suite must pass without petitRADTRANS/dynesty/pyfastchem/vulcan installed. README loses the exploratory sections and stochastic rows. Dead-code table updates in the same commit.

### Scope of move to branch `exploratory-atmospheres`
Modules: `falsifier/pipeline/stages/retrieve.py`, `falsifier/pipeline/stages/disequilibrium.py`, `falsifier/pipeline/batch/runner.py`, `scripts/run_batch.py`, `data/targets/curated_targets.json`, `data/targets/muscles/`, `tests/test_retrieve_screen.py`.

Dependencies: `petitRADTRANS`, `dynesty`, `pyfastchem`, `vulcan` — remove from `pyproject.toml` (dev group) and `requirements.txt` (if present) on main.

CLAIM blocks affected: `n_curated_targets` — this CLAIM sources from `data/targets/curated_targets.json` which is being moved. The CLAIM block must be removed from README and from the CLAIM registry in `scripts/verify_readme.py` in the same commit.

### Acceptance criteria
1. Branch `exploratory-atmospheres` exists with all listed modules moved.
2. `main` branch: `pytest tests/ -x` passes without petitRADTRANS/dynesty/pyfastchem/vulcan installed.
3. `test_retrieve_screen.py` is absent from main.
4. README has no exploratory-modules section, no stochastic rows in the reproducibility table (retrieve/disequilibrium/batch rows removed).
5. Dead-code table: entries for `retrieve.py`, `disequilibrium.py`, `batch/runner.py` replaced with a single line: "Moved to branch `exploratory-atmospheres`."
6. `n_curated_targets` CLAIM block and `_regen_n_curated_targets` function removed from README and `scripts/verify_readme.py`.
7. `python scripts/verify_readme.py --strict` exits 0 on main.
8. CI install lines in `.github/workflows/ci.yml` no longer reference the exploratory deps.
9. README documents the branch in one sentence under the dead-code table.

### AGENTS.md amendment required
Task 5 moves modules off main. AGENTS.md Rule 6 says dead code must be declared in README. The amendment is: "Modules moved to a named exploratory branch are declared by a single-line reference to that branch in the README dead-code table; they need not be listed individually on main."

Proposed wording (add to Rule 6, after the existing paragraph):
> **Branch exception**: a module moved in its entirety to a named exploratory branch (documented in the README dead-code table with branch name) satisfies Rule 6 for the main branch. The branch itself is not subject to Rule 6 enforcement.

This amendment ships in the same commit as the exploratory move.

### Todo list
1. Create branch `exploratory-atmospheres` from current main.
2. On the new branch: verify all exploratory modules are present and tests pass.
3. On main: delete/move the listed modules and test file.
4. Remove exploratory deps from `pyproject.toml` and `requirements.txt`.
5. Update dead-code table in README.
6. Remove exploratory sections (Retrieve, Screen, batch pipeline) from README.
7. Remove stochastic rows (retrieve, disequilibrium, batch) from reproducibility table.
8. Remove `n_curated_targets` CLAIM block from README and `_regen_n_curated_targets` from `scripts/verify_readme.py`.
9. Add AGENTS.md Rule 6 branch exception amendment (commit rationale: "Task 5 — exploratory branch split").
10. Run `pytest tests/ -x` and `python scripts/verify_readme.py --strict` on main.

### Relevant context
- `README.md` lines 659–729: exploratory modules section — remove
- `README.md` lines 630–649: reproducibility table — remove stochastic rows
- `README.md` lines 735–745: dead-code table — update
- `scripts/verify_readme.py` → `_regen_n_curated_targets` (line 151) — remove
- `tests/test_retrieve_screen.py`: remove from main
- `pyproject.toml`: remove `petitRADTRANS`, `dynesty`, `pyfastchem`, `vulcan`

### Status
- [ ] pending

---

## Task 6 — Rewrite the README front matter (LAST)

### Intent
After Tasks 1–5 are complete, rewrite the README opening to describe what is actually true: a deterministic false-positive triage pipeline with measured evidence. Move PROVEN_GATES.md above the fold. Add the KIC 6965293 hero scenario with committed plot. Shorten the README.

### Hero scenario requirements
- Star: KIC 6965293 → disposition `false_positive` → triggering test `odd_even_depth`
- Published depth ratio: 6.68:1 (Prša et al. 2011) — already in `MANIFEST.json` → already behind `CLAIM:eb_depth_ratio`
- Plot: odd/even depth plot rendered from committed FITS → committed to `docs/assets/kic6965293_odd_even_depth.png`
- Side-by-side: manual vetting approach vs. pipeline output — prose, no invented numbers

### Structure (front-to-back order)
1. Problem statement: thousands of Kepler/TESS candidates, expert-hours per light curve, false positives dilute follow-up
2. What Falsifier does: rejects false positives deterministically, names the test that rejected each one
3. Hero scenario: KIC 6965293 with plot
4. PROVEN_GATES.md section (moved above the fold)
5. Biosignature non-claim (moved below hero)
6. Judge Quick Access table
7. Existing sections (shortened, exploratory content gone per Task 5)

### Acceptance criteria
1. `docs/assets/kic6965293_odd_even_depth.png` committed, rendered from committed KIC 6965293 Q3 FITS.
2. All numbers in the rewritten front matter trace to CLAIM blocks.
3. README is shorter than the current version (word count).
4. `python scripts/verify_readme.py --strict` exits 0.
5. No new number appears in README without a CLAIM block and named source.
6. Biosignature non-claim is preserved verbatim per AGENTS.md Locked Claim.

### Todo list
1. Generate `docs/assets/kic6965293_odd_even_depth.png` from committed FITS via a dedicated script `scripts/generate_hero_plot.py` (renders odd/even phase-folded flux, commits plot).
2. Write the new front matter following the structure above.
3. Move PROVEN_GATES.md reference above the fold.
4. Add Judge Quick Access table immediately after hero scenario.
5. Remove sections moved or deleted by Task 5; remove defensive language that no longer applies.
6. Run `python scripts/verify_readme.py --strict` — must exit 0.
7. Verify README word/line count is reduced from current.

### Relevant context
- `data/golden/kic6965293_q3_long.fits`: committed FITS for KIC 6965293
- `MANIFEST.json` → `golden_set[1].eb_catalog.depth_ratio_primary_over_secondary = 6.68`: already CLAIM:eb_depth_ratio
- `tests/test_known_eb_rejected.py`: verifies `odd_even_depth` rejection — link in hero scenario
- Current README: 1020+ lines — target is meaningfully shorter

### Status
- [ ] pending

---

## Implementation notes

### Gate that must stay green throughout every task
- `python scripts/verify_readme.py --strict` exits 0
- `pytest tests/test_no_number_is_invented.py` passes
- `pytest tests/pipeline/contracts/` passes
- `pytest tests/test_known_eb_rejected.py` passes
- `pytest tests/test_kepler10_recovery.py` passes
- No test may be deleted or weakened

### Hard constraints (from task spec)
- NotImplementedError guard in `scripts/train_classifier_dr25.py` is NEVER removed.
- AGENTS.md is never edited to make a task pass without a rationale in the same commit.
- No number is carried forward from a failed or invalidated run.
- The pilot shard `data/artifacts/pilot_shards/injection_recovery_kic_7272437.json` (BLS_fallback) is NOT promoted to a result.

### Pre-flight dependency check for Tasks 3a/3b
Before running adversarial or injection-recovery scripts:
- Confirm `transitleastsquares` is installed (`python -c "import transitleastsquares"`).
- Confirm Q3 FITS are present for the five replacement quiet stars in `data/golden/`.
- Only KIC 7272437 Q3 is currently committed; others must be fetched.
