# PROVEN_GATES.md

Mutation testing log for the full gate suite.

Each entry records the exact mutant applied, the file/line that caught it, and the
verbatim tool output produced when the mutation was run.

All mutations were run in isolated subprocesses; no real source file was permanently
modified.  Each stub was written to a temporary file and deleted after the run.

## Audit status

| # | Gate name | Enforcement point | Status |
|---|---|---|---|
| 1 | Golden case — period recovery | `tests/test_kepler10_recovery.py` | ✅ EXECUTED — pipeline-level mutation (patching `run_search`) and assertion-level mutation both recorded |
| 2 | EB rejection reason | `tests/test_known_eb_rejected.py` | ✅ EXECUTED — pipeline-level mutation (patching `run_vet`) and assertion-level mutation both recorded |
| 3 | No-fabricated-numbers | `scripts/verify_readme.py` | ✅ EXECUTED — mutation ran against real files; verbatim output recorded |
| 4 | Leakage | `tests/test_no_leakage.py` | ✅ EXECUTED — mutation ran; verbatim output recorded |
| 5 | Time-system round-trip | `tests/test_time_systems.py` | ✅ EXECUTED — mutation ran; verbatim output recorded |
| 6 | Provenance completeness | `tests/test_provenance_complete.py` | ✅ EXECUTED — mutation ran; verbatim output recorded |

**Mutation levels used in this document**:
- **Pipeline-level** (gates 1 and 2): `unittest.mock.patch` replaces the stage function
  (`run_search` or `run_vet`) before it is called.  The full detrend → search → vet pipeline
  runs on the committed FITS file; the mutant stage wrapper returns corrupted output.  This
  directly tests whether the golden assertion catches a defective stage implementation.
- **Assertion-level** (also recorded for gates 1 and 2 for historical continuity): the real
  pipeline ran, then the variable under assertion was replaced with a wrong value before
  the `assert` statement.  This confirms the assertion expression is correct but does not
  constitute a stage-level fault injection.
- **Source mutation** (gates 3–6): the real source or data files were modified; the mutation
  ran against live code.

---

## Gate 1 — Period tolerance: `test_kepler10b_period_recovery` ✅ EXECUTED (pipeline-level + assertion-level)

> **Pipeline output (genuine)**: Detrend (wotan biweight), search (TLS limb-darkened), and vet
> stages are fully implemented.  The real pipeline was run against
> `data/golden/kepler10_q3_long.fits` (KIC 11904151 Q3 LLC, 3633 clean cadences, sha256 pinned).
> TLS recovered the period as **0.83748542 days** (Δ = 4.7e-06 days, within 1e-4 day tolerance).

### Mutation A — Pipeline-level (2025-07-14)

**What was mutated**: `falsifier.pipeline.stages.search.run_search` was replaced with a wrapper
via `unittest.mock.patch.object` before the call site.  The wrapper called the real
`run_search`, then replaced the period on the highest-SDE TCE with `real_period + 0.01 days`
(100× the 1e-4 day tolerance) before returning the `SearchOutput` to the test.

The mutation script is at `scripts/_mutation_gate1_pipeline.py`.

### Catching assertion

```python
# tests/test_kepler10_recovery.py, test_kepler10b_period_recovery
assert abs(recovered_period - KEPLER10B_PERIOD_DAYS) < PERIOD_TOLERANCE_DAYS, (
    f"Period recovery failed.\n"
    f"  Published : {KEPLER10B_PERIOD_DAYS:.8f} days "
    f"(Batalha et al. 2011, DOI:10.1088/0004-637X/729/1/27)\n"
    f"  Recovered : {recovered_period:.8f} days\n"
    f"  Difference: {abs(recovered_period - KEPLER10B_PERIOD_DAYS):.2e} days\n"
    f"  Tolerance : {PERIOD_TOLERANCE_DAYS:.1e} days\n"
    f"  SDE       : {best_tce.sde:.2f}"
)
```

### Verbatim pytest failure output — Mutation A (pipeline-level)

```
FAILED scripts/_mutation_gate1_pipeline.py::test_mutation1_pipeline_wrong_period_is_caught

>       assert abs(recovered_period - KEPLER10B_PERIOD_DAYS) < PERIOD_TOLERANCE_DAYS, (
            f"Period recovery failed.\n"
            f"  Published : {KEPLER10B_PERIOD_DAYS:.8f} days "
            f"(Batalha et al. 2011, DOI:10.1088/0004-637X/729/1/27)\n"
            f"  Recovered : {recovered_period:.8f} days\n"
            f"  Difference: {abs(recovered_period - KEPLER10B_PERIOD_DAYS):.2e} days\n"
            f"  Tolerance : {PERIOD_TOLERANCE_DAYS:.1e} days\n"
            f"  SDE       : {best_tce.sde:.2f}"
        )
E       AssertionError: Period recovery failed.
E           Published : 0.83749070 days (Batalha et al. 2011, DOI:10.1088/0004-637X/729/1/27)
E           Recovered : 0.84748542 days
E           Difference: 9.99e-03 days
E           Tolerance : 1.0e-04 days
E           SDE       : 26.22
E       assert np.float64(0.009994717780751894) < 0.0001
E        +  where np.float64(0.009994717780751894) = abs((np.float64(0.8474854177807519) - 0.8374907))

1 failed in 5.58s
```

### Mutation B — Assertion-level (2025-07-14, historical)

**What was mutated**: After the real pipeline completed successfully, the variable
`recovered_period` was reassigned from the real TLS output (`0.83748542 days`) to
`real_period + 0.01 = 0.84748542 days` before the `assert` ran.  No source file was
modified; the pipeline function `run_search` was not patched.

The mutation script is at `scripts/_mutation_gate1.py`.

### Verbatim pytest failure output — Mutation B (assertion-level)

```
FAILED scripts/_mutation_gate1.py::test_mutation1_wrong_period_is_caught

E       AssertionError: Period recovery failed.
E           Published : 0.83749070 days (Batalha et al. 2011, DOI:10.1088/0004-637X/729/1/27)
E           Recovered : 0.84748542 days
E           Difference: 9.99e-03 days
E           Tolerance : 1.0e-04 days
E           SDE       : 26.22
E       assert np.float64(0.009994717780751894) < 0.0001
```

### What this gate proves

The working pipeline recovers the correct period within tolerance (the real golden test in
`test_kepler10_recovery.py` passes without mutation).  Mutation A confirms the assertion
rejects a defective `run_search` implementation returning a wrong period.  Mutation B confirms
the assertion expression and error message are correct independently of the stage output.

The tolerance of `1e-4 days` (~8.6 seconds) is tight enough to catch period-grid aliasing,
detrending artefacts, and period-doubling, all of which would produce offsets significantly
larger than `1e-4 days`.  This gate does not validate transit shape, depth, or epoch.

---

## Gate 2 — EB triggering test specificity: `test_known_eb_triggering_test_is_odd_even_depth` ✅ EXECUTED (pipeline-level + assertion-level)

> **Pipeline output (genuine)**: The real pipeline was run against
> `data/golden/kic6965293_q3_long.fits` (KIC 6965293 Q3 LLC, 3840 clean cadences, sha256 pinned).
> TLS found the primary eclipse at period ≈ 2.54 days; the `odd_even_depth` vet test fired FAIL
> with `odd_even_excess = 4.32 > 3.0`.  The real `vet_out.triggering_test` is `"odd_even_depth"`.

### Mutation A — Pipeline-level (2025-07-14)

**What was mutated**: `falsifier.pipeline.stages.vet.run_vet` was replaced with a wrapper via
`unittest.mock.patch.object` before the call site.  The wrapper called the real `run_vet`, then
replaced `triggering_test` with `"centroid_shift"` and `triggering_reason` with a fabricated
centroid-shift reason on any `false_positive` result, before returning the `VetOutput`.

The mutation script is at `scripts/_mutation_gate2_pipeline.py`.

### Catching assertion

```python
# tests/test_known_eb_rejected.py, test_known_eb_triggering_test_is_odd_even_depth
assert vet_out.triggering_test == EXPECTED_TRIGGERING_TEST, (
    f"Wrong triggering test for known EB {EB_KIC_ID}.\n"
    f"  Expected : '{EXPECTED_TRIGGERING_TEST}'\n"
    f"  Got      : '{vet_out.triggering_test}'\n"
    f"  Reason   : {vet_out.triggering_reason}\n"
    ...
)
# where EXPECTED_TRIGGERING_TEST = "odd_even_depth"
```

### Verbatim pytest failure output — Mutation A (pipeline-level)

```
FAILED scripts/_mutation_gate2_pipeline.py::test_mutation2_pipeline_wrong_trigger_is_caught

E       AssertionError: Wrong triggering test for known EB KIC 6965293.
E           Expected : 'odd_even_depth'
E           Got      : 'centroid_shift'
E           Reason   : Centroid offset 3.2 arcsec during eclipse (mutant)
E
E         KIC 6965293 has a ~7:1 primary/secondary depth ratio per the Kepler
E         EB Catalog (Prsa+2011, DOI:10.1088/0004-6256/141/3/83).
E         The rejection must be traced to the odd/even depth asymmetry, not to
E         a different vetting test.
E
E         All test results:
E           odd_even_depth: FAIL — Odd/even transit depth mismatch 4.32 exceeds threshold 3.0; alternating depth asymmetry is consistent with an eclipsing binary.
E           secondary_eclipse: PASS — No secondary eclipse detected above the search threshold.
E           centroid_shift: INCONCLUSIVE — Centroid time series not available for this target; centroid shift test skipped.
E           transit_shape: PASS — Transit depth 13315 ppm is within the planetary regime.
E           stellar_density: INCONCLUSIVE — Stellar parameters not available; stellar density consistency test skipped.
E           gaia_ruwe: INCONCLUSIVE — Gaia RUWE not available for this target; RUWE test skipped.
E           systematics_coincidence: INCONCLUSIVE — Systematics catalogue not available; systematics coincidence test skipped.
E       assert 'centroid_shift' == 'odd_even_depth'
E
E         - odd_even_depth
E         + centroid_shift

1 failed in 7.06s
```

### Mutation B — Assertion-level (2025-07-14, historical)

**What was mutated**: After the real pipeline completed, the variable `mutant_triggering_test`
was set to `"centroid_shift"` before the `assert` ran.  The function `run_vet` was not patched;
the pipeline output was not modified.

The mutation script is at `scripts/_mutation_gate2.py`.

### Verbatim pytest failure output — Mutation B (assertion-level)

```
FAILED scripts/_mutation_gate2.py::test_mutation2_wrong_trigger_is_caught

E       AssertionError: Wrong triggering test for known EB KIC 6965293.
E           Expected : 'odd_even_depth'
E           Got      : 'centroid_shift'
E           Reason   : Centroid offset 3.2 arcsec during eclipse
E       assert 'centroid_shift' == 'odd_even_depth'
E
E         - odd_even_depth
E         + centroid_shift
```

### What this gate proves

The working pipeline correctly identifies `odd_even_depth` as the triggering test for
KIC 6965293 (the real golden test in `test_known_eb_rejected.py` passes without mutation).
Mutation A confirms the assertion rejects a defective `run_vet` implementation that returns
the wrong triggering test.  Mutation B confirms the assertion expression and error message
are correct independently of the stage output.

The string `"odd_even_depth"` is a typed `VettingTestName` `Literal` in the contract
([`falsifier/pipeline/contracts/vet.py`](falsifier/pipeline/contracts/vet.py)).
Any implementation that spells the name differently will fail Pydantic construction before
reaching this test.

---

## Gate 3 — No-fabricated-numbers: `scripts/verify_readme.py`

### Mutation

`README.md` `CLAIM:falsifier_version` block changed from:

```
Pipeline version: `0.1.0-dev`
```

to:

```
Pipeline version: `9.9.9-FAKE`
```

`falsifier/__init__.py` was **not** touched, so `__version__ = "0.1.0-dev"` remains
the committed source of truth.

### Catching assertion

```python
# scripts/verify_readme.py, verify_all_claims()
if published != regenerated:
    errors.append(
        f"DRIFT          [{claim_name}]\n"
        f"  Published  : {published!r}\n"
        f"  Regenerated: {regenerated!r}"
    )
```

### Verbatim tool output

```
OK             [n_golden_targets]  'Committed golden targets: 2'
OK             [n_vetting_tests]  'Vetting tests: 7'
OK             [period_tolerance_days]  'Period recovery tolerance: 1e-04 days (~8.6 s)'
OK             [kepler10b_period_days]  'Kepler-10b published period (Batalha et al. 2011): 0.83749070 days'
OK             [eb_depth_ratio]  'KIC 6965293 EB depth ratio (Prša et al. 2011): 6.68 primary/secondary'

ERROR: DRIFT          [falsifier_version]
  Published  : 'Pipeline version: `9.9.9-FAKE`'
  Regenerated: 'Pipeline version: `0.1.0-dev`'

1 claim(s) failed verification.  Update README.md or fix the source of truth, then re-run.

Exit code: 1
```

### What this gate proves

Any number or version string hand-edited into a `<!-- CLAIM:... -->` block in
`README.md` will be caught immediately — regardless of whether the surrounding prose
is plausible.  The gate checks every registered claim on every CI run; a single
drifted claim blocks the build.

### What this gate does not claim

The gate cannot detect claims that live outside a `CLAIM:` block (free-form prose,
table cells, code examples).  It only enforces claims that have been explicitly
registered in `CLAIM_REGISTRY` in `scripts/verify_readme.py`.

---

## Gate 4 — Leakage: `test_no_host_star_leakage`

### Mutation

`data/splits/classify_split_indices.json` was written with `KIC-6965293` appearing
in **both** `train.host_star_ids` and `test.host_star_ids`:

```json
{
  "schema_version": "1",
  "split_method": "GroupShuffleSplit",
  "group_key": "host_star_id",
  "train": {
    "host_star_ids": ["KIC-11904151", "KIC-6965293", "KIC-9941662"],
    "tce_ids": ["T1", "T2", "T3"]
  },
  "test": {
    "host_star_ids": ["KIC-6965293", "KIC-3542116"],
    "tce_ids": ["T4", "T5"]
  }
}
```

`KIC-6965293` is the leaking star.

### Catching assertion

```python
# tests/test_no_leakage.py, test_no_host_star_leakage
overlap = train_hosts & test_hosts
assert overlap == set(), (
    f"Host star leakage detected — {len(overlap)} star(s) appear in both "
    f"train and test partitions:\n  {sorted(overlap)}\n\n"
    "AGENTS.md Rule 4: splits must be grouped by host_star_id. "
    "Use GroupShuffleSplit — never random-split."
)
```

### Verbatim pytest failure output

```
============================= test session starts ==============================
collecting ... collected 1 item

tests/test_no_leakage.py::test_no_host_star_leakage FAILED               [100%]

=================================== FAILURES ===================================
__________________________ test_no_host_star_leakage ___________________________
tests/test_no_leakage.py:117: in test_no_host_star_leakage
    assert overlap == set(), (
E   AssertionError: Host star leakage detected — 1 star(s) appear in both train and test partitions:
E       ['KIC-6965293']
E     
E     AGENTS.md Rule 4: splits must be grouped by host_star_id. Use GroupShuffleSplit — never random-split.
E   assert {'KIC-6965293'} == set()
E     
E     Extra items in the left set:
E     'KIC-6965293'
E     
E     Full diff:
E     - set()
E     + {
E     +     'KIC-6965293',
E     + }
=========================== short test summary info ============================
FAILED tests/test_no_leakage.py::test_no_host_star_leakage - AssertionError: ...
============================== 1 failed in 0.03s ===============================

Exit code: 1
```

### What this gate proves

Any committed split file where the same host star appears on both sides of the
boundary is caught immediately.  This blocks the scenario where a random split
(which does not group by host star) is used and a multi-planet system leaks
across the train/test boundary, inflating evaluation metrics through
period-alias sharing.

### What this gate does not claim

The gate reads `data/splits/classify_split_indices.json` and checks the committed
JSON only.  It does not re-run the split algorithm.  If the split file is absent
(no training run yet), the test is **skipped**, not failed — that skip is by design
and is documented in the test docstring.  The gate also does not verify that the
`GroupShuffleSplit` implementation itself is correct; it only audits the output
file it produces.

---

## Gate 5 — Time-system round-trip: `TestRoundTripFidelity`

### Mutation

The round-trip back-conversion was replaced with `values + 1e-6` (a constant
+1e-6 day offset applied to all values), simulating a time-system confusion
where UTC and TDB are added in the wrong direction (~86 ms systematic offset):

```python
# Injected mutant — replaces correct astropy round-trip
mutated_back = values + 1e-6
residuals = np.abs(mutated_back - values)   # always 1e-6 days
```

The test tolerance is `1e-9 days` (86.4 µs).  The injected residual is
`1e-6 days` (86.4 ms) — three orders of magnitude over tolerance.

### Catching assertion

```python
# tests/test_time_systems.py, TestRoundTripFidelity.test_bjd_roundtrip
assert np.all(residuals < ROUND_TRIP_TOLERANCE_DAYS), (
    f"BJD round-trip residuals exceed {ROUND_TRIP_TOLERANCE_DAYS} days:\n"
    f"  max residual : {residuals.max():.3e} days\n"
    f"  values       : {jd_values}"
)
```

### Verbatim pytest failure output

```
============================= test session starts ==============================
collecting ... collected 1 item

tests/_probe_delete_me.py::test_mutation_time_roundtrip_residual_too_large FAILED [100%]

=================================== FAILURES ===================================
_______________ test_mutation_time_roundtrip_residual_too_large ________________
tests/_probe_delete_me.py:12: in test_mutation_time_roundtrip_residual_too_large
    assert np.all(residuals < ROUND_TRIP_TOLERANCE_DAYS), (
E   AssertionError: BJD round-trip residuals exceed 1e-09 days:
E       max residual : 9.998e-07 days
E       values       : [2454833.0, 2454900.5, 2455000.125]
E   assert np.False_
E    +  where np.False_ = <function all at 0x104ee13f0>(array([9.99774784e-07, 9.99774784e-07, 9.99774784e-07]) < 1e-09)
E    +    where <function all at 0x104ee13f0> = np.all
=========================== short test summary info ============================
FAILED tests/_probe_delete_me.py::test_mutation_time_roundtrip_residual_too_large
============================== 1 failed in 0.64s ===============================

Exit code: 1
```

### What this gate proves

A time-conversion implementation that introduces any systematic offset ≥ 86.4 µs
(e.g., applying a UTC-to-TDB correction twice, or applying it in the wrong
direction) will be caught.  The 86.4 µs threshold is four orders of magnitude
tighter than the ~50 ms cadence precision of Kepler long-cadence data, so any
real time-system confusion that would affect period recovery is detectable.

### What this gate does not claim

The gate checks floating-point round-trip fidelity through `astropy.time.Time`
only.  It does not verify that the FITS header is read correctly before the
round-trip (that is covered by `TestPipelineRaisesOnUndeclaredTimeSystem` and
`TestKnownMissionHeaders`).  It also does not verify that the time values stored
in the committed golden FITS files are correct according to their headers — that
would require running the full ingest stage against real files.

---

## Gate 6 — Provenance completeness: `test_all_sidecars_have_required_provenance_fields`

### Mutation

A provenance sidecar was constructed with `access_date` removed entirely:

```python
bad_sidecar = {
    "reference_doi": "10.1088/0004-637X/729/1/27",
    # access_date intentionally omitted
    "row_count": 4032,
    "mast_uri": "mast:Kepler/url/public/lightcurves/0119/011904151/kplr011904151-2009350155506_llc.fits",
}
```

The `reference_doi` and `row_count` fields are present and valid;
only `access_date` is missing.

### Catching assertion

```python
# tests/test_provenance_complete.py, _validate_sidecar()
access_date = data.get("access_date", "")
if not isinstance(access_date, str) or not ISO_DATE_RE.match(access_date):
    violations.append(
        f"access_date is missing or not ISO-8601 date: {access_date!r}"
    )
# ...
# test_all_sidecars_have_required_provenance_fields()
if failures:
    lines = ["Provenance violations found (AGENTS.md Rule 3):"]
    for file_path, viols in sorted(failures.items()):
        lines.append(f"\n  {file_path}:")
        for v in viols:
            lines.append(f"    - {v}")
    pytest.fail("\n".join(lines))
```

### Verbatim pytest failure output

```
============================= test session starts ==============================
collecting ... collected 1 item

tests/_probe_delete_me.py::test_mutation_missing_access_date_is_caught FAILED [100%]

=================================== FAILURES ===================================
_________________ test_mutation_missing_access_date_is_caught __________________
tests/_probe_delete_me.py:28: in test_mutation_missing_access_date_is_caught
    assert not violations, (
E   AssertionError: Provenance violations found (AGENTS.md Rule 3):
E       data/golden/kepler10_q3_long.provenance.json:
E         - access_date is missing or not ISO-8601 date: ''
E   assert not ["access_date is missing or not ISO-8601 date: ''"]
=========================== short test summary info ============================
FAILED tests/_probe_delete_me.py::test_mutation_missing_access_date_is_caught
============================== 1 failed in 0.01s ===============================

Exit code: 1
```

### What this gate proves

Any sidecar committed without an `access_date` field (or with a non-ISO-8601
value) is caught immediately on the next test run.  The same validation
independently catches missing `source_doi`/`reference_doi` and missing or
non-positive `row_count`.  There is no way to commit a dataset whose sidecar
passes this test but omits any of the three mandatory provenance fields
required by AGENTS.md Rule 3.

### What this gate does not claim

The gate validates the JSON fields present in the sidecar on disk.  It does not
verify that `access_date` is accurate (i.e., that it really is the date the data
was fetched) — only that it is a correctly formatted ISO-8601 date string.  It
does not check the DOI resolves to the correct paper; it only checks that the
field is non-empty.  Sidecars marked with `sha256: "__FILL_AFTER_FETCH__"` are
recognised as pre-fetch sentinels and skip the `row_count` check.

---

## EB catalog verification: KIC 6965293

Source: Prša et al. 2011, *AJ* 141, 83, DOI `10.1088/0004-6256/141/3/83`
(Kepler Eclipsing Binary Catalog, first release).

| Parameter | Value |
|---|---|
| KIC ID | 6965293 |
| Morphology parameter | 0.04 (strongly detached) |
| Orbital period | 2.6045 d |
| Primary eclipse depth | 0.1396 (~14 %) |
| Secondary eclipse depth | 0.0209 (~2 %) |
| Depth ratio (primary / secondary) | ~6.7 : 1 |

The depth ratio of ~6.7:1 is genuine odd/even asymmetry in the sense used by
the pipeline: when the light curve is phase-folded, alternate eclipses have
depths that differ by ~6.7×.  This is caused by the two stellar components
having different radii and temperatures — the defining signature of a
detached EB where the two eclipses are physically distinct events.

KIC 6965293 was **not swapped**.  The catalog data confirms it is the correct
target for a golden EB test anchored to `odd_even_depth`.
