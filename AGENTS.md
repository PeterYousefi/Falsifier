# AGENTS.md — Project Policy Spine
> Read this file at the start of every session before touching any code.

---

## Locked Claim

This project performs **disequilibrium screening and false-positive triage** for exoplanet
candidates. It is **not** a biosignature detector.
**No exoplanet biosignature has ever been confirmed.**
This claim is immutable. No generated code, comment, or UI copy may contradict or weaken it.

---

## Non-Negotiable Rules for All Generated Code

### 1 — No Hardcoded Scientific Values in UI or API Code
Every number displayed to a user must originate from a **committed pipeline artifact**
(e.g. a versioned `.json` / `.csv` produced by a reproducibility script).
Hardcoding a scientific value (flux, period, radius, score, threshold) in UI or API code is
forbidden. If the value isn't traceable to a pipeline run, it must not appear.

### 2 — Physical Quantities Carry Units
Every physical quantity uses `astropy.units`. No bare floats may cross module boundaries.
```python
# correct
period = 3.14 * u.day
# forbidden
period = 3.14          # no unit — rejected at review
```

### 3 — Dataset Manifest Is Mandatory
Every ingested dataset must have a corresponding manifest entry recording:
- `source_doi`  — the citable DOI
- `access_date` — ISO-8601 date the data was fetched
- `row_count`   — integer row count at ingest time

No dataset is used in any pipeline stage until its manifest entry is committed.

### 4 — ML Splits Are Grouped by Host Star
Train/test/validation splits are **always grouped by host star ID**.
Random splitting is forbidden: it leaks planetary-system structure across the boundary and
produces artificially optimistic metrics. Any split function must accept and enforce a
`group_by="host_star_id"` argument.

### 5 — README Claims Must Be Regenerable
No claim (detection rate, false-positive rate, model score, dataset size) appears in the README
unless it is produced — and kept current — by the project's reproducibility script
(`scripts/reproduce.sh` or equivalent). Manually written statistics are forbidden.

### 6 — Dead Code Must Be Declared
If a module is written but is not reachable from a live code path (import chain or CLI entry
point), it **must be listed explicitly** in the README under a "Dead / Experimental Code" section
with a note explaining why it is not wired in. Silently unused code is a policy violation.

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Web framework | FastAPI |
| Astronomy | astropy, lightkurve, wotan, transitleastsquares, astroquery |
| ML | xgboost |
| Chat inference | IBM watsonx.ai (ModelInference chat, tool calling) (`WATSONX_APIKEY`; degrades offline if absent) |
| Output screening | Granite Guardian (`ibm-granite/granite-guardian-3.1-2b`, local HuggingFace cache, `local_files_only=True`, no network call) |
| Testing | pytest |
| Frontend | Vite + React + Three.js |

All dependencies are pinned in `requirements.txt` / `pyproject.toml`. Unpinned transitive
dependencies in scientific packages are a reproducibility risk — pin them.

---

## Enforcement

These rules are enforced at:
1. **Code review** — PRs failing any rule above are blocked.
2. **CI** — `pytest` suite includes policy-level tests (unit manifest checks, unit-crossing checks).
3. **Agent sessions** — any AI assistant operating in this repo must refuse requests that
   would violate the rules above and must explain which rule is at stake.
