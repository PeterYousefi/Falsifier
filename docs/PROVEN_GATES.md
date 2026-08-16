# PROVEN_GATES.md

Mutation testing log for the golden fixture test suite.
Each entry records: the mutant, the test that catches it, and the verbatim
failure message produced when pytest ran `tests/_stubs_delete_me.py` on
**2025-07-14** before the stub file was deleted.

The stubs were self-contained (no pipeline imports) and replicated the exact
assertion logic from `tests/test_kepler10_recovery.py` and
`tests/test_known_eb_rejected.py` with mutant values injected directly.

---

## Gate 1 — Period tolerance: `test_kepler10b_period_recovery`

### Mutation

`run_search` returns a TCE with `period = 0.83749070 + 0.01 = 0.84749070 days`.
This is 100× the test tolerance of `1e-4 days`.

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

### Verbatim pytest failure output

```
FAILED tests/_stubs_delete_me.py::test_mutation1_wrong_period_is_caught

    @pytest.mark.no_network
    def test_mutation1_wrong_period_is_caught():
        ...
>       assert abs(recovered_period - KEPLER10B_PERIOD_DAYS) < PERIOD_TOLERANCE_DAYS, (
            f"Period recovery failed.\n"
            ...
        )
E       AssertionError: Period recovery failed.
E           Published : 0.83749070 days (Batalha et al. 2011, DOI:10.1088/0004-637X/729/1/27)
E           Recovered : 0.84749070 days
E           Difference: 1.00e-02 days
E           Tolerance : 1.0e-04 days
E           SDE       : 42.00
E       assert 0.010000000000000009 < 0.0001
E        +  where 0.010000000000000009 = abs((0.8474907 - 0.8374907))
```

### What this proves

A `run_search` implementation that returns a period off by even 0.01 days
(12× the period uncertainty quoted in Batalha+2011) cannot pass this test.
The tolerance of `1e-4 days` (~8.6 seconds) is tight enough to catch
period-grid aliasing, detrending artefacts, and period-doubling — all of
which would produce offsets significantly larger than `1e-4 days`.

---

## Gate 2 — EB triggering test specificity: `test_known_eb_triggering_test_is_odd_even_depth`

### Mutation

`run_vet` returns `disposition="false_positive"` with `triggering_test="centroid_shift"`
instead of the correct `"odd_even_depth"`. The `odd_even_depth` test result is set
to `PASS`; `centroid_shift` is set to `FAIL`.

This models an implementation that:
- correctly rejects the EB (coarse gate passes)
- but attributes the rejection to the wrong vetting test (fine gate fails)

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

### Verbatim pytest failure output

```
FAILED tests/_stubs_delete_me.py::test_mutation2_wrong_trigger_is_caught

    @pytest.mark.no_network
    def test_mutation2_wrong_trigger_is_caught():
        ...
>       assert vet_out.triggering_test == EXPECTED_TRIGGERING_TEST, (
            f"Wrong triggering test for known EB {EB_KIC_ID}.\n"
            ...
        )
E       AssertionError: Wrong triggering test for known EB KIC 6965293.
E           Expected : 'odd_even_depth'
E           Got      : 'centroid_shift'
E           Reason   : Centroid offset 3.2 arcsec during eclipse
E         
E         KIC 6965293 has a ~7:1 primary/secondary depth ratio per the Kepler
E         EB Catalog (Prsa+2011, DOI:10.1088/0004-6256/141/3/83).
E         The rejection must be traced to the odd/even depth asymmetry, not to
E         a different vetting test.
E         
E         All test results:
E           odd_even_depth: PASS — odd_even_depth passed
E           secondary_eclipse: PASS — secondary_eclipse passed
E           centroid_shift: FAIL — Centroid offset 3.2 arcsec during eclipse
E           transit_shape: PASS — transit_shape passed
E           stellar_density: PASS — stellar_density passed
E           gaia_ruwe: PASS — gaia_ruwe passed
E           systematics_coincidence: PASS — systematics_coincidence passed
E       assert 'centroid_shift' == 'odd_even_depth'
E         
E         - odd_even_depth
E         + centroid_shift
```

### What this proves

Passing `test_known_eb_disposition_is_false_positive` (disposition gate) is
not sufficient.  An implementation must specifically fire the `odd_even_depth`
test for KIC 6965293.  This cannot be gamed by routing all EBs through
`centroid_shift` or `stellar_density`.

The string `"odd_even_depth"` is a typed `VettingTestName` `Literal` in the
contract (`falsifier/pipeline/contracts/vet.py`).  Any implementation that
spells the name differently will fail Pydantic construction before reaching
this test.

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
