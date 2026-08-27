# Dead / Not-in-Live-Path Modules

The following modules are written but **not reachable from the real-time
detection pipeline** (`POST /jobs` → ingest → classify) or from
`scripts/verify_readme.py`. Any module absent from this table that is also
unreachable from `scripts/reproduce.sh` is a policy violation (AGENTS.md Rule 6).

| Module | Status | Not in live path because |
|---|---|---|
| `falsifier/pipeline/stages/classify.py` | Wired via API queue (opt-in); **deliberately not trained** | Classifier training is a deliberate refusal: train/serve feature skew means training on DR25 proxies produces a probability meaningless at inference time. The `NotImplementedError` guard is correct behaviour (see `docs/SKIPPED_TESTS.md`). |
| `falsifier/pipeline/stages/retrieve.py` | **Exploratory** — wired only via `scripts/run_batch.py` | Requires petitRADTRANS + dynesty |
| `falsifier/pipeline/stages/disequilibrium.py` | **Exploratory** — wired only via `scripts/run_batch.py` | Requires FastChem + VULCAN |
| `falsifier/pipeline/batch/runner.py` | **Exploratory** — CLI only via `scripts/run_batch.py` | Offline batch process; no API route calls it |
| `falsifier/pipeline/stages/search.py` `_MAX_PLANETS = 1` | **Known limitation** — iterative masking structurally present but inert | `_MAX_PLANETS = 1` means only the strongest signal is returned |
| `falsifier/api/queue 2.py` | **Scratch / macOS duplicate** — untracked, not importable | Filename contains a space (macOS Finder duplicate artefact); Python cannot import it. Contains the pre-fix version of `falsifier/api/queue.py` with the original `to_fits(output_fn=…)` defect. Not wired into any import chain or CLI entry point. |
| `falsifier/pipeline/ingest/cache 2.py` | **Scratch / macOS duplicate** — untracked, not importable | Same origin as above; duplicate of `falsifier/pipeline/ingest/cache.py`. Not wired into any import chain. |
| `falsifier/pipeline/ingest/sources/mast 2.py` | **Scratch / macOS duplicate** — untracked, not importable | Duplicate of `falsifier/pipeline/ingest/sources/mast.py` carrying the original `to_fits(output_fn=buf)` and `Table.get()` defects that were fixed in the live file. Not wired into any import chain. |

## Training refused: train/serve feature skew

**Classifier training is a deliberate refusal**, not a placeholder.
The classifier reads vet-stage `metric_value` fields at inference, but no DR25
catalog column maps to the same physical quantity or numeric scale.

See [`docs/decisions/0001-refuse-proxy-training.md`](decisions/0001-refuse-proxy-training.md)
for the full ADR and field-by-field skew table.
See [`docs/SKIPPED_TESTS.md`](SKIPPED_TESTS.md) for the proxy-mapping table and resolution options.
