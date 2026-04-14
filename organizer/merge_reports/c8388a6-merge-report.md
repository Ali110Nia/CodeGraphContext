# Merge Report: c8388a6 (`directory, folder confusion resolved`)

## Feasibility
- `git apply --check`: conflict on backend files due prior integration drift.

## Conflict Matrix
| File | Status | Decision | Rationale |
|---|---|---|---|
| `graph_builder.py` unsupported marker | conflict | **already integrated** | current `parse_file()` returns `unsupported: True`. |
| `indexing/pipeline.py` skip minimal node for unsupported | conflict | **already integrated** | current flow already guards `elif not file_data.get("unsupported")`. |
| `website/src/components/CodeGraphViewer.tsx` (`Folder`->`Directory`) | out of scope | **no-op** | user chose backend-only 4th priority item. |

## Accepted Deltas
- No backend code changes required.

## Residual Risks
- Frontend naming consistency remains deferred by scope choice.
