# Test Coverage

The detrend → search → vet pipeline is tested at every level.

## Distribution across layers

| Layer | What is tested | Count |
|---|---|---|
| **Golden regression — period** | TLS recovers Kepler-10b period to within 1e-4 days on committed FITS | 6 |
| **Golden regression — EB rejection** | KIC 6965293 triggers `odd_even_depth` FAIL, not any other gate | 7 |
| **Stage contracts (Pydantic)** | Every stage input/output validates at construction | ~65 |
| **No leakage (12 tests)** | Train and test host-star sets are strictly disjoint — **skips** until training runs | 12 (pending) |
| **Provenance completeness** | Every sidecar records `source_doi`, `access_date`, `row_count` | ~8 |
| **Time-system round-trip** | BJD / BTJD / BKJD conversions survive to within 86.4 µs | ~15 |
| **No invented numbers** | Every scientific float in fixtures and frontend traces to a committed artifact | ~10 |
| **API-key deletion** | All 5 pipeline stages run with every external credential unset | ~10 |
| **Adversarial self-test** | Artifact structure; required fields present | ~20 |
| **Chat layer + Guardian screening** | Chat tools read from real artifacts; Guardian blocks unsafe outputs | ~30 |
| **Ingest (TAP / MAST / Gaia)** | Table guard rejects retired tables; network blocked in all offline tests | ~25 |
| **Pipeline I/O** | `artifact_write` / `artifact_read` / `input_hash` round-trips | ~15 |
| **Retrieve + screen contracts** *(exploratory)* | Pydantic contracts for retrieval and screening | ~30 |
| **Injection recovery unit tests** | Script writes correct artifact fields | ~10 |
| **Mutation scripts (excluded)** | Deliberately failing; run manually to prove gates fire | 4 (not in suite) |

## Why the distribution produces accurate results

**Two independent layers reject false positives.**
The vet stage uses a deterministic truth table (no model, no threshold) — a single
FAIL from any of the seven tests yields `false_positive`. The golden EB regression
verifies not just rejection, but that the *named mechanism* is correct.

**Period recovery is constrained end-to-end on real Kepler data.**
TLS runs on committed FITS, detrended with wotan biweight, against the published value.

**All tests run offline with no network access.**
`tests/conftest.py` blocks all outgoing socket connections at session level.

## CI jobs

| Job | What it proves |
|---|---|
| `test-fast` | Contracts import with pydantic + numpy only |
| `test-no-invented-numbers` | Every scientific float traces to a committed artifact |
| `frontend-build` | Vite build succeeds; bundle contains no invented numbers |
| `verify-readme` | Every `<!-- CLAIM:... -->` block matches its regenerated value |
| `test-full` | Full suite including chat layer |
| `smoke-check` | Production frontend and backend health endpoints return 200 |
