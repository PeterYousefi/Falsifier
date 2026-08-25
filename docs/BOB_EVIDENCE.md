# Bob Evidence

Inventory of verifiable evidence of IBM Bob usage in this repository.
Each entry links to a file path; existence can be confirmed with `git ls-files`.

---

## Committed evidence

| Artifact | File path | What it shows |
|---|---|---|
| **AGENTS.md policy contracts** | [`AGENTS.md`](../AGENTS.md) | Six non-negotiable rules authored in Bob sessions and enforced in CI; Bob refused to violate Rule 1 (hardcoded values) and Rule 5 (unregistered README claims) during implementation |
| **Custom mode definition** | [`.bob/custom_modes.yaml`](../.bob/custom_modes.yaml) | `exoplanet-pipeline-engineer` mode: traceability enforcement, scientific-value refusal, FLAG-block protocol — committed configuration created in Bob |
| **Plan-mode contract design output** | [`pipeline-contracts-plan.md`](../pipeline-contracts-plan.md) | Bob Plan mode output: `VetInput` / `VetOutput` Pydantic schema design produced before any implementation; contract tests were written from this document as failing stubs |

---

## Not yet committed

The following artifacts are referenced in the README's "How IBM Bob was used"
table but do not exist as committed files in this repository.

| Referenced as | Expected path | Reason not committed |
|---|---|---|
| Bob session transcripts (per-stage implementation sessions) | *(no canonical path)* | Session transcripts were not exported or committed; work is evidenced indirectly by the implementation and the plan-mode output above |
| TDD scaffolding session (golden test stubs) | *(no canonical path)* | The generated stubs (`test_kepler10_recovery.py`, `test_known_eb_rejected.py`) are committed but the Bob session that produced them was not exported |
| Defect-surfacing session (depth-formula bug) | *(no canonical path)* | The fix is present in `falsifier/pipeline/stages/search.py` (line: `(1.0 - results.depth) * 1_000_000`) but no session log is committed |
| Policy-enforcement session (SDE_THRESHOLD extraction) | *(no canonical path)* | The constant lives in `falsifier/pipeline/constants/pipeline_constants.py`; no session log is committed |

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
- No session transcripts have been committed. The evidentiary chain for
  implementation sessions runs through the committed code, tests, and
  plan-mode document rather than raw transcripts.
