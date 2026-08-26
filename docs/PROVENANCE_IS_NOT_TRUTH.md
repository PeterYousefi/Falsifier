# docs/PROVENANCE_IS_NOT_TRUTH.md

> **The worked example in this document is real.**
> It describes a defect that passed the project's strongest lineage gate.
> The gate worked as designed. The input was wrong. That is the point.

---

## The limitation class

Provenance gates verify **lineage**, not **validity**.

A gate that asks "does every number in the README trace back to a committed
artifact?" has exactly one answer: yes or no. It cannot ask "is the artifact
correct?" The artifact is the claimed ground truth. Once a number is committed
to an artifact and the gate passes, the gate has done everything it was built
to do. If the artifact is wrong, no downstream provenance check will say so.

This is not a bug in the gate. It is a structural constraint on what provenance
verification can guarantee. Lineage is not truth.

---

## The worked example: KOI cumulative table total

### Before

In an early state of this repository, `data/artifacts/impact_facts.json`
contained:

```json
{
  "koi_total_rows": {
    "value": 2000,
    "adql": "SELECT TOP 2000 * FROM cumulative",
    ...
  },
  "koi_disposition_counts": {
    "value": {"CONFIRMED": 1329, "CANDIDATE": 192, "FALSE POSITIVE": 479},
    ...
  },
  "koi_fp_fraction": {
    "value": 23.9,
    ...
  }
}
```

The README reported:

```
KOI cumulative table total rows: 2,000
KOI false-positive fraction: 23.9%
```

Both claims passed `test_no_number_is_invented.py`. Both traced to
`data/artifacts/impact_facts.json`. Provenance was intact.

The artifact was wrong. `SELECT TOP 2000` is a row cap, not an aggregate. The
2,000 figure was the cap value being reported as the table total. The derived
false-positive fraction of 23.9% was computed over the first 2,000 rows
returned — a non-random slice of an unknown size.

### Why the gate passed

`test_no_number_is_invented.py` asks: "does this number appear in a committed
artifact?" It does not ask: "was the artifact produced by a sound query?" It
cannot. It has no knowledge of SQL, no model of what the NASA Exoplanet Archive
TAP service returns for a row-capped query, and no way to distinguish between
`SELECT COUNT(*) FROM cumulative` (an aggregate returning the true count) and
`SELECT TOP 2000 * FROM cumulative` (a row-limited scan returning at most 2,000
rows). Both produce a committed artifact. Both pass the lineage gate.

This is the structural reason the gate could not catch it: **the gate verifies
the chain from README claim to artifact, not the chain from artifact to physical
reality.**

### After (current state)

`scripts/impact_facts.py` now uses:

```sql
-- Total rows: aggregate, no row cap
SELECT COUNT(*) AS total_rows FROM cumulative

-- Per-disposition counts: aggregate, no row cap
SELECT koi_disposition, COUNT(*) AS n
FROM cumulative
GROUP BY koi_disposition
```

The 2026-08-26 live re-query returned:

| Disposition | Count |
|---|---|
| CONFIRMED | 1,329 |
| CANDIDATE | 192 |
| FALSE POSITIVE | 479 |
| **Total** | **2,000** |

The total of exactly 2,000 is genuine. The Kepler mission ended in 2018; the
KOI cumulative catalog is frozen. The false-positive fraction of 23.9% is
correct. The numbers did not change. The *basis* for the numbers changed from
a capped scan to a verified aggregate.

---

## What closed the specific hole

`tests/test_impact_facts_not_truncated.py` adds a second gate that the
provenance gate cannot provide:

1. **No ADQL string in the artifact may contain the word `TOP`.**
   `SELECT TOP N` on the NASA Exoplanet Archive TAP service caps the row scan
   before aggregation. Its presence in a count-producing query is a structural
   error, not just a suspicious value.

2. **The sum of disposition counts must not equal a common cap value (500, 1000).**
   A round sum equal to a standard cap value is the signature of a
   truncated query. (2,000 is excluded from the forbidden set because the
   Kepler catalog genuinely contains exactly 2,000 entries as of 2026-08-26.)

3. **The GROUP BY sum must equal the COUNT(\*) total.**
   If the two aggregate queries are inconsistent, one or both is wrong.

This test is wired into the `test-full` CI job. It runs on every push.

---

## The general pattern

Provenance gates verify one property: every number shown to a user was produced
by a committed artifact, not invented in code. This property is load-bearing
and worth enforcing. It eliminates an entire class of defects (hardcoded values,
numbers that drift from their source, UI values that were never measured).

It does not verify:

- That the query which produced the artifact was sound
- That the data source returned what the query intended to request
- That the artifact was not corrupted between production and commit
- That the query was run at the right time on the right data version
- That the model or method underlying the artifact is valid

Any system that relies on provenance gates for correctness guarantees beyond
lineage is overstating what the gate provides. The gate is necessary. It is
not sufficient.

The correct response is not to weaken the provenance gate — it is to layer
additional domain-specific checks on top of it. For SQL queries against
external TAP services, the additional check is: assert the query structure
is sound (no `TOP` clause in a count query). For model-based numbers, the
additional check depends on the model. For measurements, it is reproducibility.

None of these are replacements for the lineage gate. All of them are
complements to it.

---

## Summary

| Property | `test_no_number_is_invented.py` | `test_impact_facts_not_truncated.py` |
|---|---|---|
| Number appears in artifact | ✓ Checks | — |
| Artifact has provenance fields | — | ✓ Checks |
| Query has no row cap (`TOP`) | — | ✓ Checks |
| Counts sum to total | — | ✓ Checks |
| Query produced a valid count | — | — (domain knowledge required) |
| Data source was queried correctly | — | — (external; verified by re-query) |

The empty cells in the last two rows are not oversights. They are the scope
boundary. Automated gates can verify structure and consistency. Validity of the
underlying measurement requires human judgement, re-query, or an independent
source — and none of those are continuous.
