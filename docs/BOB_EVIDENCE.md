# Bob Evidence

Inventory of verifiable evidence of IBM Bob usage in this repository.
Each entry links to a file path; existence can be confirmed with `git ls-files`.

The README's "How IBM Bob was used" section points here rather than maintaining
a separate copy of this table that could drift.

---

## Artifact inventory

| Artifact | Location | Committed? |
|---|---|---|
| **AGENTS.md policy contracts** | [`AGENTS.md`](../AGENTS.md) | ✅ Yes |
| **Custom mode definition** | [`.bob/custom_modes.yaml`](../.bob/custom_modes.yaml) | ✅ Yes |
| **Plan-mode contract design output** | [`pipeline-contracts-plan.md`](../pipeline-contracts-plan.md) | ✅ Yes |
| **Bob evidence directory** | [`docs/bob-evidence/`](bob-evidence/) | ✅ Yes (directory created) |
| Bob session transcripts (per-stage implementation) | *(no canonical path)* | ❌ not yet committed |
| TDD scaffolding session (golden test stubs) | *(no canonical path)* | ❌ not yet committed |
| Defect-surfacing session (depth-formula bug) | *(no canonical path)* | ❌ not yet committed |
| Policy-enforcement session (SDE_THRESHOLD extraction) | *(no canonical path)* | ❌ not yet committed |
| Bobalytics / usage screenshots | *(no canonical path)* | ❌ not yet committed |

---

## Committed evidence — detail

### AGENTS.md

[`AGENTS.md`](../AGENTS.md) contains the six non-negotiable rules authored in Bob
sessions and enforced in CI.  Bob refused to violate Rule 1 (hardcoded values) and
Rule 5 (unregistered README claims) during implementation.  This file is read at the
start of every Bob session via the `project_rules` injection.

### .bob/custom_modes.yaml

[`.bob/custom_modes.yaml`](../.bob/custom_modes.yaml) defines the
`exoplanet-pipeline-engineer` mode: traceability enforcement, scientific-value refusal,
FLAG-block protocol.  This is a committed workspace configuration created in Bob.

### pipeline-contracts-plan.md

[`pipeline-contracts-plan.md`](../pipeline-contracts-plan.md) is a direct Bob Plan-mode
output.  It contains the schema design decisions that drove the contract-first
implementation of the pipeline stages:

- `VetInput` / `VetOutput` Pydantic schemas designed before any implementation.
- Contract tests were written from this document as failing stubs.
- The seven vetting test names as load-bearing identifiers are specified here.

---

## Not yet committed

The following artifacts are referenced in the README's "How IBM Bob was used"
table but do not exist as committed files in this repository.

| Referenced as | Expected path | Reason not committed |
|---|---|---|
| Bob session transcripts (per-stage implementation sessions) | *(no canonical path)* | Session transcripts were not exported or committed; work is evidenced indirectly by the implementation and the plan-mode output above |
| TDD scaffolding session (golden test stubs) | *(no canonical path)* | The generated stubs (`test_kepler10_recovery.py`, `test_known_eb_rejected.py`) are committed but the Bob session that produced them was not exported |
| Defect-surfacing session (depth-formula bug) | *(no canonical path)* | The fix is present in `falsifier/pipeline/stages/search.py` (line: `(1.0 - results.depth) * 1_000_000`) but no session log is committed |
| Policy-enforcement session (SDE_THRESHOLD extraction) | *(no canonical path)* | The constant lives in `scripts/pipeline_constants.py`; no session log is committed |
| Bobalytics / usage screenshots | `docs/bob-evidence/` | Not yet exported; directory is reserved for future Bob artifacts |

---

## Notes

- `AGENTS.md` is the primary machine-enforceable contract: it is read at the
  start of every Bob session (`project_rules` injection) and its rules are
  tested by CI.
- `.bob/custom_modes.yaml` is the Bob workspace configuration that activates
  the `exoplanet-pipeline-engineer` mode with traceability-enforcement
  instructions.
- `pipeline-contracts-plan.md` at the repository root is a direct Plan-mode
  output: it contains the schema design decisions that drove the contract-first
  implementation of the pipeline stages.
- `docs/bob-evidence/` is reserved for future Bob session exports (screenshots,
  Bobalytics CSVs, transcript excerpts). Session transcripts are not committed.
  The evidentiary chain for implementation sessions runs through the committed
  code, tests, and plan-mode document rather than raw transcripts.
