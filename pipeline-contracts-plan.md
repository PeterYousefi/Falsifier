# Pipeline Stage Contracts — Design Plan

## Overview

Design and implement the Pydantic input/output contracts and shared manifest models for
the seven pipeline stages: **ingest → detrend → search → vet → classify → retrieve →
disequilibrium**. No stage body is implemented here — only the typed boundaries between
stages, the serialisation helpers, and the module skeleton.

Every output model embeds a `StageManifest`. Every physical quantity carries an explicit
unit annotation via `UnitedArray` (values + unit string as data, not description text).
Every external dataset touched by a stage is recorded in `DatasetProvenance`. No bare
floats cross module boundaries (AGENTS.md Rule 2). No stage imports another stage's
internals.

The `retrieve` stage is CPU-hour-scale and must never run inside a web request. Its
contract is a **pure synchronous function** — always complete when returned. Job polling
belongs exclusively in the API layer, which wraps the pure function. No pipeline contract
models async handoff.

The `disequilibrium` stage (formerly `screen`) performs atmospheric equilibrium and
photochemistry analysis (FastChem, VULCAN, Gibbs free energy) on a curated subset of
**established planets only**. It emits no candidate disposition.

Disposition (`candidate | false_positive | candidate_with_caveats | false_positive |
ambiguous`) lives exclusively in `VetOutput` and is a deterministic function of the seven
named vetting tests. `ClassifyOutput` carries only a calibrated probability score and
calibration metadata — it is a ranking tool, not a verdict, and must not restate or
override the disposition.

The seven vetting test names are **load-bearing identifiers** — the golden EB test asserts
on `odd_even_depth` by name:

| Canonical name | What it tests |
|---|---|
| `odd_even_depth` | Asymmetric odd/even transit depths signal EB |
| `secondary_eclipse` | Significant secondary eclipse → likely EB |
| `centroid_shift` | Flux centroid shifts during transit → background EB |
| `transit_shape` | Transit shape inconsistent with planetary geometry |
| `stellar_density` | Transit duration inconsistent with stellar density |
| `gaia_ruwe` | Gaia RUWE > threshold indicates unresolved binary |
| `systematics_coincidence` | TCE period matches a known systematic artefact |

---

## Module Tree

```
falsifier/
  pipeline/
    __init__.py
    contracts/
      __init__.py          # re-exports all public models
      manifest.py          # StageManifest, DatasetProvenance, ArtifactRef, UnitedArray
      ingest.py            # IngestInput, IngestOutput
      detrend.py           # DetrendInput, DetrendOutput
      search.py            # SearchInput, SearchOutput
      vet.py               # VetInput, VetOutput, VettingTestResult, Disposition
      classify.py          # ClassifyInput, ClassifyOutput, CalibrationMeta
      retrieve.py          # RetrieveInput, RetrieveOutput, RetrievalConfig
      disequilibrium.py    # DisequilibriumInput, DisequilibriumOutput
    io.py                  # artifact_write(), artifact_read(), input_hash()
```

`contracts/` contains **only** Pydantic models and type aliases. Zero business logic.
Stage bodies will live in `falsifier/pipeline/stages/` (out of scope for this plan).

---

## Sub-Tasks

---

### Sub-Task 1 — Shared Manifest and Artifact Models

**Status:** [ ] pending

**Intent**
Define the shared types that every stage output depends on. These models enforce the
invariants stated in AGENTS.md at the type level rather than by convention.

**Expected Outcomes**
- `falsifier/pipeline/contracts/manifest.py` exists and is importable.
- `StageManifest`, `DatasetProvenance`, `ArtifactRef`, and `UnitedArray` are defined and
  pass their own unit tests.
- `DatasetProvenance` validates that `source_doi` is non-empty, `access_date` is a valid
  ISO-8601 date, and `row_count` is a positive integer.
- `StageManifest.input_hash` is documented as the SHA-256 hex digest of the serialised
  upstream output JSON.
- `UnitedArray.to_quantity()` returns an `astropy.units.Quantity`; `from_quantity()` is
  a classmethod that constructs a `UnitedArray` from one.

**Todo List**
1. Create `falsifier/pipeline/contracts/manifest.py`.
2. Define `UnitedArray`:
   - `values: list[float]` — the data payload; non-empty, validated
   - `unit: str` — the unit string as data (e.g. `"day"`, `"ppm"`, `"e-/s"`,
     `"dimensionless"`, `"BJD"`); non-empty, validated; this is not a description
     field — it is the machine-readable unit that `to_quantity()` passes to
     `astropy.units.Unit()`
   - `to_quantity(self) -> astropy.units.Quantity` — instance method; returns
     `np.array(self.values) * astropy.units.Unit(self.unit)`
   - `from_quantity(cls, q: astropy.units.Quantity) -> UnitedArray` — classmethod;
     extracts `.value.tolist()` and `str(q.unit)`
   - Validator: `len(values) >= 1`; `unit` must be a non-empty string
   - Note: `UnitedArray` is the canonical type for every physical array field in every
     stage contract. No raw `list[float]` for physical quantities.
3. Define `DatasetProvenance`:
   - `source_doi: str` — non-empty, validated
   - `access_date: date` — `datetime.date`, stored as ISO-8601 string on disk
   - `row_count: int` — strictly positive, validated
   - `description: str` — human-readable label
4. Define `ArtifactRef`:
   - `path: Path` — absolute path to the serialised artifact on disk
   - `sha256: str` — hex digest of the artifact file at write time
   - `stage: str` — name of the stage that produced it (e.g. `"ingest"`)
   - `pipeline_run_id: str` — UUID assigned at pipeline-run start, shared across all
     stages in one execution
5. Define `StageManifest`:
   - `stage: str`
   - `code_version: str` — value of `falsifier.__version__` at execution time
   - `input_hash: str` — SHA-256 of the serialised upstream output JSON (enables
     cache-hit detection)
   - `wall_time_seconds: float` — elapsed wall time for the stage body
   - `provenance: list[DatasetProvenance]` — one entry per external dataset touched;
     empty list is valid only for pure-compute stages
   - `artifact: ArtifactRef` — reference to this stage's own serialised output
6. Add `__all__` to `manifest.py` listing all four models.
7. Write `tests/pipeline/contracts/test_manifest.py`:
   - Test that `DatasetProvenance` rejects empty `source_doi`.
   - Test that `DatasetProvenance` rejects `row_count <= 0`.
   - Test that `StageManifest` round-trips through `model_dump_json` /
     `model_validate_json`.
   - Test `UnitedArray.to_quantity()` returns a `Quantity` with the correct unit.
   - Test `UnitedArray.from_quantity()` round-trips a `Quantity` back to equal values
     and unit string.
   - Test that `UnitedArray` rejects an empty `values` list.
   - Test that `UnitedArray` rejects an empty `unit` string.

**Relevant Context**
- AGENTS.md Rule 3 (dataset manifest) drives the shape of `DatasetProvenance`.
- AGENTS.md Rule 2 (units as data) drives `UnitedArray`. The unit string is load-bearing
  data, not a comment. The `to_quantity()` helper is the only approved conversion path
  from contract types to `astropy` objects inside stage bodies.
- `input_hash` on `StageManifest` is what allows `io.py` (Sub-Task 9) to short-circuit a
  stage run when a cached artifact with a matching hash already exists on disk.

---

### Sub-Task 2 — `ingest` Contracts

**Status:** [ ] pending

**Intent**
Define the boundary between "raw data request" and "immutable on-disk light curve bundle
ready for detrending". Ingest is the only stage that touches external network services
(MAST via `astroquery`/`lightkurve`); its output artifact isolates all downstream stages
from network dependency.

**Expected Outcomes**
- `falsifier/pipeline/contracts/ingest.py` exists and is importable.
- `IngestInput` and `IngestOutput` are defined.
- `IngestOutput` embeds `StageManifest` and an `ArtifactRef`.
- All physical array fields use `UnitedArray`. No raw `list[float]` for physical data.
- `LightCurveSegment` raises on construction if `time_scale` or `time_format` are absent
  (no defaults — they are required fields, not optional metadata).

**Todo List**
1. Create `falsifier/pipeline/contracts/ingest.py`.
2. Define `IngestInput`:
   - `tic_id: str` — TESS Input Catalog identifier, e.g. `"TIC 123456789"`
   - `sectors: list[int] | None` — `None` means all available sectors
   - `cadence: Literal["short", "long", "fast"]` — TESS cadence type
   - `pipeline_run_id: str` — UUID passed in by the orchestrator; propagated unchanged
     through all stages
3. Define `LightCurveSegment`:
   - `sector: int`
   - `time: UnitedArray` — barycentric time array; `unit` must be `"jd"` or `"btjd"` or
     another valid astropy time unit string; carries the numeric values only
   - `time_scale: str` — **required, no default**; astropy time scale, e.g. `"tdb"`,
     `"tcb"`, `"utc"`; validator: non-empty string; construction raises `ValidationError`
     if absent
   - `time_format: str` — **required, no default**; astropy time format, e.g. `"btjd"`,
     `"jd"`, `"iso"`; validator: non-empty string; construction raises `ValidationError`
     if absent
   - `flux: UnitedArray` — unit `"electron / s"` for SAP flux, `"dimensionless"` for
     PDCSAP; the unit string is the authority on which flux type this is
   - `flux_err: UnitedArray` — same unit as `flux`
   - `quality_flags: list[int]` — integer bitmask per cadence; not a physical quantity,
     raw list is acceptable
   - `cadence_type: str`
   - Validator: `len(time.values) == len(flux.values) == len(flux_err.values) ==
     len(quality_flags)`; raise `ValidationError` with a descriptive message if violated
4. Define `IngestOutput`:
   - `input: IngestInput` — echo of the input (enables full reproducibility from output
     alone)
   - `segments: list[LightCurveSegment]`
   - `host_star_id: str` — TIC identifier normalised to a canonical form; used as the
     group key for ML splits (AGENTS.md Rule 4)
   - `manifest: StageManifest` — must include one `DatasetProvenance` entry for the MAST
     archive fetch
   - `artifact: ArtifactRef`
5. Add validator: `segments` must be non-empty.
6. Write `tests/pipeline/contracts/test_ingest.py`:
   - Test that `LightCurveSegment` raises `ValidationError` when `time_scale` is omitted.
   - Test that `LightCurveSegment` raises `ValidationError` when `time_format` is omitted.
   - Test that mismatched array lengths raise `ValidationError`.
   - Test that `IngestOutput` rejects an empty `segments` list.
   - Test that `segment.time.to_quantity()` returns a `Quantity` with the declared unit.
   - Test round-trip serialisation.

**Relevant Context**
- `lightkurve` and `astroquery` are used in the stage body (not here).
- `host_star_id` normalisation rule: strip whitespace, upper-case, canonical form
  `"TIC {integer}"`.
- `time_scale` and `time_format` have no defaults because an unknown time scale is a
  silent correctness bug, not a recoverable error. The validation must happen at
  construction, not at use.

---

### Sub-Task 3 — `detrend` Contracts

**Status:** [ ] pending

**Intent**
Define the boundary between raw light curves and systematics-corrected light curves.
`detrend` calls `wotan` (and optionally CBV correction); its output is the last artifact
before period-search, so its contract must carry enough metadata to reconstruct the
detrending configuration exactly.

**Expected Outcomes**
- `falsifier/pipeline/contracts/detrend.py` exists and is importable.
- `DetrendInput` takes an `ArtifactRef` pointing to a serialised `IngestOutput` — not the
  `IngestOutput` object itself — enforcing the "resume from cache" requirement.
- `DetrendOutput` records the detrending method and its hyperparameters.

**Todo List**
1. Create `falsifier/pipeline/contracts/detrend.py`.
2. Define `DetrendInput`:
   - `ingest_artifact: ArtifactRef` — pointer to a serialised `IngestOutput` on disk
   - `method: Literal["biweight", "lowess", "gp", "cofiam"]`
   - `window_length: UnitedArray` — single-element array; `unit` must be `"d"` or `"day"`
   - `break_tolerance: UnitedArray` — single-element array; same unit convention
   - `pipeline_run_id: str`
3. Define `DetrendedSegment`:
   - `sector: int`
   - `time: UnitedArray` — propagated from `LightCurveSegment`; carries the same unit
     and is accompanied by `time_scale` and `time_format` fields (required, no defaults,
     same validation rule as `LightCurveSegment`)
   - `time_scale: str` — required, no default; propagated from upstream segment
   - `time_format: str` — required, no default; propagated from upstream segment
   - `flux: UnitedArray` — normalised relative flux; `unit` is `"dimensionless"`
   - `flux_err: UnitedArray` — same unit as `flux`
   - `trend_flux: UnitedArray` — fitted trend in original flux units (e.g. `"electron / s"`)
   - `quality_flags: list[int]`
   - Validator: all `UnitedArray` values lists and `quality_flags` have equal length
4. Define `DetrendOutput`:
   - `input: DetrendInput`
   - `segments: list[DetrendedSegment]`
   - `host_star_id: str` — propagated from `IngestOutput`
   - `detrending_method: str` — echoes `input.method`
   - `manifest: StageManifest`
   - `artifact: ArtifactRef`
5. Write `tests/pipeline/contracts/test_detrend.py`: round-trip, length-mismatch
   rejection, and `time_scale`/`time_format` absence rejection tests.

**Relevant Context**
- `wotan` is used in the stage body (not here).
- `DetrendInput` deliberately holds `ingest_artifact: ArtifactRef` rather than
  `IngestOutput` directly. This is the pattern used across all stages: each stage reads
  its upstream artifact from disk, allowing any stage to be re-run in isolation.

---

### Sub-Task 4 — `search` Contracts

**Status:** [ ] pending

**Intent**
Define the boundary between detrended light curves and a list of Threshold Crossing Events
(TCEs). `search` calls `transitleastsquares`; its output is a set of periodic signals, not
yet vetted.

**Expected Outcomes**
- `falsifier/pipeline/contracts/search.py` exists and is importable.
- Each TCE carries the TLS signal statistics needed by `vet`.
- No disposition is assigned here.

**Todo List**
1. Create `falsifier/pipeline/contracts/search.py`.
2. Define `SearchInput`:
   - `detrend_artifact: ArtifactRef`
   - `period_min: UnitedArray` — single-element; unit `"d"` or `"day"`
   - `period_max: UnitedArray` — single-element; unit `"d"` or `"day"`
   - `snr_threshold: float` — dimensionless scalar; bare float is acceptable here because
     it is a configuration constant, not a physical result crossing a module boundary
   - `pipeline_run_id: str`
3. Define `TCE` (Threshold Crossing Event):
   - `tce_id: str` — `"{tic_id}-{index:02d}"` format
   - `period: UnitedArray` — single-element; unit `"d"` or `"day"`
   - `period_uncertainty: UnitedArray` — single-element; same unit as `period`;
     non-optional (explicit uncertainty rule)
   - `epoch: UnitedArray` — single-element; unit `"jd"` or `"btjd"`
   - `duration: UnitedArray` — single-element; unit `"h"` or `"hour"`
   - `depth: UnitedArray` — single-element; unit `"ppm"`
   - `sde: float` — Signal Detection Efficiency; dimensionless diagnostic scalar,
     bare float acceptable (not a physical quantity)
   - `snr: float` — dimensionless scalar
   - `odd_even_mismatch: float` — dimensionless TLS diagnostic scalar
   - `secondary_eclipse_depth: UnitedArray | None` — single-element; unit `"ppm"`;
     `None` if no secondary eclipse found
4. Define `SearchOutput`:
   - `input: SearchInput`
   - `tces: list[TCE]` — may be empty (no significant signals found)
   - `host_star_id: str`
   - `tls_version: str` — version of `transitleastsquares` used, from its `__version__`
   - `manifest: StageManifest`
   - `artifact: ArtifactRef`
5. Write `tests/pipeline/contracts/test_search.py`: round-trip, empty TCE list accepted,
   `period_uncertainty` absent is rejected, `to_quantity()` on a TCE field returns correct
   unit.

**Relevant Context**
- `transitleastsquares` is used in the stage body (not here).
- `period_uncertainty_days` is non-optional per AGENTS.md Rule — explicit uncertainty
  over point estimates.

---

### Sub-Task 5 — `vet` Contracts

**Status:** [ ] pending

**Intent**
Define the boundary that produces a **deterministic, human-auditable disposition** for
each TCE. Disposition lives here — nowhere else. It is computed from the results of seven
named vetting tests. `ClassifyOutput` must never override or restate it.

**Expected Outcomes**
- `falsifier/pipeline/contracts/vet.py` exists and is importable.
- `Disposition` is `Literal["candidate", "candidate_with_caveats", "false_positive", "ambiguous"]`.
- `VettingTestOutcome` is `Literal["PASS", "FAIL", "FLAG", "INCONCLUSIVE"]`.
- `VetOutput` records every test result individually plus the triggering test name and
  reason for the final disposition.
- The seven vetting test names are fixed identifiers. `VettingTestName` is a `Literal`
  over exactly these strings — load-bearing because the golden EB test asserts on
  `"odd_even_depth"` by name.
- Disposition logic is fully specified by the validator; no code outside `vet.py` may
  compute or override it.

**Disposition Truth Table**

| Conditions | Disposition |
|---|---|
| All seven outcomes are `PASS` | `candidate` |
| Any outcome is `FAIL` | `false_positive` (first FAIL triggers) |
| No `FAIL`, any outcome is `FLAG` | `candidate_with_caveats` (first FLAG triggers) |
| No `FAIL`, no `FLAG`, any `INCONCLUSIVE` | `ambiguous` (first INCONCLUSIVE triggers) |

`triggering_test` and `triggering_reason` are required (`non-None`) for every
disposition except `candidate`.

**Todo List**
1. Create `falsifier/pipeline/contracts/vet.py`.
2. Define `VettingTestOutcome` as `Literal["PASS", "FAIL", "FLAG", "INCONCLUSIVE"]`.
3. Define `VettingTestName` as a `Literal` over exactly these seven strings (load-bearing
   identifiers — do not rename without updating golden EB tests):
   - `"odd_even_depth"` — asymmetric odd/even transit depths signal EB
   - `"secondary_eclipse"` — significant secondary eclipse → likely EB
   - `"centroid_shift"` — flux centroid shifts during transit → background EB
   - `"transit_shape"` — transit shape inconsistent with planetary geometry
   - `"stellar_density"` — transit duration inconsistent with stellar density
   - `"gaia_ruwe"` — Gaia RUWE > threshold indicates unresolved binary
   - `"systematics_coincidence"` — TCE period matches a known systematic artefact
4. Define `VettingTestResult`:
   - `test_name: VettingTestName` — typed to the `Literal` above; rejects unknown names
     at construction
   - `outcome: VettingTestOutcome`
   - `metric_value: float | None` — the scalar the test evaluated, if applicable
   - `metric_unit: str | None` — unit string, `"dimensionless"`, or `None` if no metric
   - `reason: str` — required, non-empty; one sentence
5. Define `Disposition` as
   `Literal["candidate", "candidate_with_caveats", "false_positive", "ambiguous"]`.
6. Define `VetInput`:
   - `search_artifact: ArtifactRef`
   - `tce_id: str` — one TCE per `VetInput` (vet is per-TCE, not per-star)
   - `pipeline_run_id: str`
7. Define `VetOutput`:
   - `input: VetInput`
   - `tce_id: str`
   - `host_star_id: str`
   - `test_results: list[VettingTestResult]` — exactly seven entries, one per named test,
     in canonical order matching `VettingTestName` ordering
   - `disposition: Disposition`
   - `triggering_test: VettingTestName | None` — `None` only when `disposition ==
     "candidate"`; typed to `VettingTestName` so unknown test names are rejected
   - `triggering_reason: str | None` — `None` only when `disposition == "candidate"`
   - `manifest: StageManifest`
   - `artifact: ArtifactRef`
8. Add validator: `len(test_results) == 7`, enforced strictly; raise with a message that
   names the missing or extra test.
9. Add validator: `disposition != "candidate"` implies both `triggering_test` and
   `triggering_reason` are non-None.
10. Add validator: `disposition == "candidate"` requires all seven outcomes are `PASS`
    (not merely that there are no FAILs — this is the stricter form).
11. Write `tests/pipeline/contracts/test_vet.py`:
    - Test all-PASS → `candidate`, `triggering_test` is `None`.
    - Test any-FAIL → `false_positive`, `triggering_test` is the first FAIL test name.
    - Test no-FAIL + any-FLAG → `candidate_with_caveats`, `triggering_test` is the first
      FLAG test name.
    - Test no-FAIL + no-FLAG + any-INCONCLUSIVE → `ambiguous`.
    - Test that `disposition == "candidate"` with a `FLAG` outcome present is rejected.
    - Test that fewer than seven results is rejected.
    - Test that an unknown `test_name` string is rejected.
    - Test that `odd_even_depth` is a valid `VettingTestName` (golden EB test anchor).
    - Test round-trip serialisation.

**Relevant Context**
- This is the most policy-critical contract. The "API-deletion test": `VetOutput` alone
  must be a valid, defensible scientific record without the classifier.
- `VettingTestName` is typed (not `str`) so that a typo in a test name is a construction
  error, not a silent mismatch with the golden EB test suite.
- `candidate_with_caveats` was added to model the case where a signal passes all hard
  FAIL gates but a soft FLAG (e.g. a marginal RUWE) warrants explicit acknowledgement.

---

### Sub-Task 6 — `classify` Contracts

**Status:** [ ] pending

**Intent**
Define the boundary for the XGBoost ranking stage. `ClassifyOutput` is a calibrated
probability score and calibration metadata. It is a ranking tool only. It must not contain
a disposition field and must not reference `Disposition` in any way.

**Expected Outcomes**
- `falsifier/pipeline/contracts/classify.py` exists and is importable.
- `ClassifyOutput` has no `disposition` field and no field that could be interpreted as
  a verdict.
- `CalibrationMeta` captures the calibration method, dataset used, and calibration curve
  statistics so scores are reproducible.

**Todo List**
1. Create `falsifier/pipeline/contracts/classify.py`.
2. Define `CalibrationMeta`:
   - `method: Literal["isotonic", "platt", "beta"]`
   - `calibration_dataset_doi: str` — DOI of the dataset used for calibrator fitting
   - `calibration_date: date`
   - `brier_score: float` — calibration quality metric, dimensionless
   - `ece: float` — Expected Calibration Error, dimensionless
   - `n_calibration_samples: int` — strictly positive
3. Define `ClassifyInput`:
   - `vet_artifact: ArtifactRef` — points to a `VetOutput` on disk
   - `model_artifact: ArtifactRef` — points to the serialised XGBoost model artifact
   - `pipeline_run_id: str`
4. Define `ClassifyOutput`:
   - `input: ClassifyInput`
   - `tce_id: str`
   - `host_star_id: str`
   - `probability: float` — calibrated probability in [0.0, 1.0]; validator enforces range
   - `probability_uncertainty: float` — bootstrap or conformal prediction uncertainty;
     non-optional per explicit-uncertainty rule
   - `calibration: CalibrationMeta`
   - `model_version: str` — value from the model artifact's own metadata
   - `feature_importances: dict[str, float]` — feature name → SHAP value; empty dict is
     valid if SHAP is not computed for this run
   - `manifest: StageManifest`
   - `artifact: ArtifactRef`
5. Add validator: `0.0 <= probability <= 1.0`.
6. Add validator: `probability_uncertainty >= 0.0`.
7. Write `tests/pipeline/contracts/test_classify.py`:
    - Test that `probability = 1.1` is rejected.
    - Test that negative `probability_uncertainty` is rejected.
    - Test round-trip serialisation.

**Relevant Context**
- `ClassifyOutput` deliberately has no `disposition` field. Any code that reads
  `ClassifyOutput` and branches on a verdict is a policy violation. Rankers rank;
  vetters vet.

---

### Sub-Task 7 — `retrieve` Contracts

**Status:** [ ] pending

**Intent**
Define the boundary for the CPU-hour-scale atmospheric retrieval stage. The pipeline
contract is a **pure synchronous function**: it takes `RetrieveInput` and returns a fully
populated `RetrieveOutput`. There is no `status` field, no nullable result fields, no
`job_id` on the output. Job lifecycle management (queuing, polling, failure handling)
belongs entirely in the API layer, which wraps the pure function. No pipeline contract
models async handoff.

**Expected Outcomes**
- `falsifier/pipeline/contracts/retrieve.py` exists and is importable.
- `RetrieveOutput` has no `status` field and no nullable result fields.
- All physical array fields use `UnitedArray`.
- The API layer's concern (job polling) is explicitly out of scope for this contract.
- `JobStatus` is **not** defined in this module; if the API layer needs it, it defines
  it independently.

**Todo List**
1. Create `falsifier/pipeline/contracts/retrieve.py`.
2. Define `RetrieveInput`:
   - `classify_artifact: ArtifactRef` — points to a `ClassifyOutput` on disk; the
     orchestrator is responsible for only submitting `candidate` or
     `candidate_with_caveats` dispositions
   - `retrieval_config: RetrievalConfig` (see below)
   - `pipeline_run_id: str`
3. Define `RetrievalConfig`:
   - `retrieval_code: Literal["petitRADTRANS", "CHIMERA", "POSEIDON"]`
   - `n_live_points: int` — nested sampling live points; strictly positive; validator
     enforces `> 0`
   - `chemistry_scheme: Literal["equilibrium", "free", "disequilibrium"]`
   - `pressure_grid_levels: int` — strictly positive; validator enforces `> 0`
   - `include_clouds: bool`
4. Define `RetrievedSpectrum`:
   - `wavelength: UnitedArray` — unit `"micron"` or `"um"`
   - `transit_depth: UnitedArray` — unit `"ppm"`
   - `transit_depth_uncertainty: UnitedArray` — unit `"ppm"`; same length as
     `transit_depth`; non-optional
   - Validator: `len(wavelength.values) == len(transit_depth.values) ==
     len(transit_depth_uncertainty.values)`
5. Define `RetrieveOutput`:
   - `input: RetrieveInput`
   - `tce_id: str`
   - `host_star_id: str`
   - `spectrum: RetrievedSpectrum` — always populated; no `None` option
   - `posterior_artifact: ArtifactRef` — path to nested-sampling posterior file on disk;
     always present
   - `log_evidence: float` — Bayesian log-evidence in natural log (ln Z, nats); bare
     float is acceptable here (scalar result, not an array crossing boundaries); field
     description must state `"Natural log (nats). Not log base 10."`
   - `log_evidence_uncertainty: float` — non-optional; explicit uncertainty rule
   - `wall_time_cpu_hours: float` — elapsed CPU time; bare float acceptable (metadata,
     not physical quantity)
   - `manifest: StageManifest` — must include `DatasetProvenance` entries for any
     atmospheric opacity database or stellar model grid used
   - `artifact: ArtifactRef`
6. Write `tests/pipeline/contracts/test_retrieve.py`:
    - Test that `spectrum` with mismatched array lengths is rejected.
    - Test that `n_live_points <= 0` is rejected.
    - Test that `RetrieveOutput` has no `status` field (guard against regression).
    - Test round-trip serialisation.

**Relevant Context**
- The API layer wraps the pure `retrieve` function in a task queue (Celery, RQ, etc.) and
  manages job lifecycle with its own state model. That state model is entirely outside
  this contract.
- `log_evidence` and `log_evidence_uncertainty` are bare floats (not `UnitedArray`)
  because they are dimensionless scalar results, not physical arrays. The "no bare floats
  crossing module boundaries" rule applies to physical quantities; log-evidence in nats is
  a dimensionless log-probability.

---

### Sub-Task 8 — `disequilibrium` Contracts

**Status:** [ ] pending

**Intent**
Define the boundary for atmospheric disequilibrium analysis using FastChem, VULCAN, and
Gibbs free energy minimisation. This stage runs on a **curated subset of established
planets only** — not on candidates. It emits no disposition. Its outputs are
thermochemical equilibrium profiles and disequilibrium metrics only.

**Expected Outcomes**
- `falsifier/pipeline/contracts/disequilibrium.py` exists and is importable.
- `DisequilibriumOutput` has no disposition field.
- The contract records which chemical species were computed and their disequilibrium
  metrics explicitly.

**Todo List**
1. Create `falsifier/pipeline/contracts/disequilibrium.py`.
2. Define `DisequilibriumInput`:
   - `retrieve_artifact: ArtifactRef` — points to a completed `RetrieveOutput`
   - `planet_name: str` — canonical name from NASA Exoplanet Archive
   - `planet_doi: str` — DOI of the reference paper for the planet's bulk parameters
   - `fastchem_config: FastChemConfig` (see below)
   - `pipeline_run_id: str`
3. Define `FastChemConfig`:
   - `temperature_pressure_profile_source: Literal["retrieval", "parametric", "gcm"]`
   - `included_species: list[str]` — chemical formula strings, e.g. `["H2O", "CO2",
     "CH4"]`; non-empty, validated
   - `metallicity_solar: float` — dimensionless ratio; bare float acceptable (scalar
     configuration parameter, not a physical array crossing boundaries)
   - `c_to_o_ratio: float` — dimensionless; must be > 0.0; bare float acceptable
4. Define `ChemicalSpeciesProfile`:
   - `species: str` — chemical formula
   - `vmr_profile: UnitedArray` — volume mixing ratio vs pressure; `unit` is
     `"dimensionless"`
   - `pressure: UnitedArray` — pressure grid; `unit` is `"bar"`
   - `equilibrium_vmr_profile: UnitedArray` — FastChem equilibrium prediction at same
     pressure grid; `unit` is `"dimensionless"`
   - `disequilibrium_metric: float` — integrated absolute log-ratio between observed and
     equilibrium profiles; dimensionless scalar, always >= 0.0; bare float acceptable
   - Validator: `len(vmr_profile.values) == len(pressure.values) ==
     len(equilibrium_vmr_profile.values)`
5. Define `GibbsMinimisationResult`:
   - `temperature: UnitedArray` — single-element; `unit` is `"K"`
   - `pressure: UnitedArray` — single-element; `unit` is `"bar"`
   - `species_fractions: dict[str, float]` — species → mole fraction; bare floats
     acceptable (dimensionless ratios summing to 1)
   - `gibbs_free_energy: UnitedArray` — single-element; `unit` is `"J / mol"`
6. Define `DisequilibriumOutput`:
   - `input: DisequilibriumInput`
   - `planet_name: str`
   - `host_star_id: str`
   - `species_profiles: list[ChemicalSpeciesProfile]` — one per species in
     `fastchem_config.included_species`
   - `gibbs_results: list[GibbsMinimisationResult]` — one per T/P grid point
   - `overall_disequilibrium_score: float` — mean of `disequilibrium_metric` across
     all species; dimensionless; this is a **screening metric, not a biosignature claim**
   - `manifest: StageManifest` — must include `DatasetProvenance` entries for the
     planet reference paper and any atmospheric model grid used
   - `artifact: ArtifactRef`
7. Add validator: `len(species_profiles) == len(input.fastchem_config.included_species)`.
8. Add validator: all `disequilibrium_metric` values are >= 0.0.
9. Add validator: `overall_disequilibrium_score >= 0.0`.
10. Write `tests/pipeline/contracts/test_disequilibrium.py`:
    - Test species-count mismatch is rejected.
    - Test negative `disequilibrium_metric` is rejected.
    - Test round-trip serialisation.
    - Add a docstring assertion: `DisequilibriumOutput` has no `disposition` field.

**Relevant Context**
- AGENTS.md Locked Claim: this stage explicitly must not contain any language or field
  that could be read as a biosignature claim. The `overall_disequilibrium_score` field
  description must state: "Screening metric only. Does not constitute a biosignature claim."
- FastChem, VULCAN, and Gibbs minimisation are used in the stage body (not here).

---

### Sub-Task 9 — Serialisation Helpers (`io.py`)

**Status:** [ ] pending

**Intent**
Provide the two functions — `artifact_write` and `artifact_read` — that all stage bodies
use to persist and resume from cached artifacts. Also provide `input_hash` for cache-hit
detection. These are the only functions that touch the filesystem on behalf of the
pipeline.

**Expected Outcomes**
- `falsifier/pipeline/io.py` exists and is importable.
- `artifact_write(model, directory)` serialises a Pydantic model to a deterministic
  filename and returns an `ArtifactRef`.
- `artifact_read(ref, model_class)` deserialises an artifact from disk and validates it
  against the given model class.
- `input_hash(model)` returns the SHA-256 hex digest of `model.model_dump_json()`.
- No stage imports `io.py` directly — stages call it through the orchestrator or a
  thin runner shim (to preserve testability without a filesystem).

**Todo List**
1. Create `falsifier/pipeline/io.py`.
2. Implement `input_hash(model: BaseModel) -> str`:
   - Returns `hashlib.sha256(model.model_dump_json().encode()).hexdigest()`.
3. Implement `artifact_write(model: BaseModel, directory: Path) -> ArtifactRef`:
   - Filename: `"{stage}_{pipeline_run_id}_{sha256[:8]}.json"` where `stage` is
     `model.manifest.stage` and `pipeline_run_id` is `model.input.pipeline_run_id`.
   - Write with `model.model_dump_json(indent=2)`.
   - Compute SHA-256 of the written file bytes and store in the returned `ArtifactRef`.
4. Implement `artifact_read(ref: ArtifactRef, model_class: type[T]) -> T`:
   - Read the file at `ref.path`.
   - Verify SHA-256 of file bytes matches `ref.sha256`; raise `ArtifactCorruptedError`
     if not.
   - Validate with `model_class.model_validate_json(content)`.
5. Define `ArtifactCorruptedError(RuntimeError)`.
6. Write `tests/pipeline/test_io.py`:
   - Test that `artifact_read` raises `ArtifactCorruptedError` when the file is tampered.
   - Test that `artifact_write` → `artifact_read` round-trip returns an equal model.
   - Test that `input_hash` is stable (same input → same hash across calls).

**Relevant Context**
- The deterministic filename means re-running the same stage with the same input and
  version will produce the same filename — enabling cache-hit detection without a
  database.

---

### Sub-Task 10 — Package Skeleton and `contracts/__init__.py`

**Status:** [ ] pending

**Intent**
Wire the module tree together so all public models are importable from
`falsifier.pipeline.contracts`. Verify no stage contract imports another.

**Expected Outcomes**
- `falsifier/pipeline/__init__.py` and `falsifier/pipeline/contracts/__init__.py` exist.
- All public models are importable via `from falsifier.pipeline.contracts import ...`.
- `pytest` collects and passes all tests written in Sub-Tasks 1–9 with zero failures.
- `ruff` passes on all new files.

**Todo List**
1. Create `falsifier/__init__.py` with `__version__ = "0.1.0-dev"`.
2. Create `falsifier/pipeline/__init__.py` (empty, marks package).
3. Create `falsifier/pipeline/contracts/__init__.py` that re-exports:
   - From `manifest`: `StageManifest`, `DatasetProvenance`, `ArtifactRef`, `UnitedArray`
   - From `ingest`: `IngestInput`, `IngestOutput`, `LightCurveSegment`
   - From `detrend`: `DetrendInput`, `DetrendOutput`, `DetrendedSegment`
   - From `search`: `SearchInput`, `SearchOutput`, `TCE`
   - From `vet`: `VetInput`, `VetOutput`, `VettingTestResult`, `Disposition`,
     `VettingTestName`, `VettingTestOutcome`
   - From `classify`: `ClassifyInput`, `ClassifyOutput`, `CalibrationMeta`
   - From `retrieve`: `RetrieveInput`, `RetrieveOutput`, `RetrievedSpectrum`,
     `RetrievalConfig`
     (Note: `JobStatus` is deliberately absent — it is not a pipeline contract type)
   - From `disequilibrium`: `DisequilibriumInput`, `DisequilibriumOutput`,
     `ChemicalSpeciesProfile`, `GibbsMinimisationResult`, `FastChemConfig`
4. Run `python -c "from falsifier.pipeline.contracts import VetOutput, ClassifyOutput;
   assert not hasattr(ClassifyOutput.model_fields, 'disposition')"` to verify the
   disposition-isolation rule at the import level.
5. Run `python -c "from falsifier.pipeline.contracts import RetrieveOutput;
   assert not hasattr(RetrieveOutput.model_fields, 'status')"` to verify the
   no-async-in-pipeline-contracts rule at the import level.
6. Run `pytest tests/pipeline/ -q` and confirm zero failures.
7. Run `ruff check falsifier/pipeline/contracts/ falsifier/pipeline/io.py` and fix any
   issues.
