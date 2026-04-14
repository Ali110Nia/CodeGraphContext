# Merge Report: e288331 (`fixes- #701, #758, #728, #783, #804, #750`)

## Feasibility
- `git apply --check`: **heavy conflict**
- Files checked: 15
- Conflicts/errors: 10
  - docs files (`mcp_guide.md`, `mkdocs.yml`)
  - `cli_helpers.py`, `code_finder.py`, `analysis_handlers.py`
  - missing handler paths (`indexing_handlers.py`, `watcher_handlers.py`)
  - existing files already present (`repo_path.py`, tests)

## Conflict Matrix
| File/Area | Status | Decision | Rationale |
|---|---|---|---|
| `cli_helpers.py` repo matching/count fix | conflict | **already integrated** | `any_repo_matches_path` and `count(DISTINCT f)` already present. |
| `code_finder.py` fuzzy/case fixes | conflict | **already integrated/superseded** | Current implementation includes portable Levenshtein + backend-aware search flow. |
| `analysis_handlers.py` query lowercase fix | conflict | **already integrated** | current keeps case and only normalizes underscores. |
| `setup_wizard.py` OpenCode MCP instructions | clean residual | **apply** | Feature missing in current branch and low-risk usability improvement. |
| `main.py` MCP setup docs mention OpenCode | clean residual | **apply** | Keeps CLI docstring aligned with setup wizard support. |
| docs and old handler modules | conflict/missing | **no-op** | outside backend merge scope or removed by current architecture. |

## Accepted Deltas
1. Add OpenCode option and instruction flow to `setup_wizard.py`.
2. Update `mcp setup` CLI docstring to include OpenCode.

## Residual Risks
- None; changes are additive and isolated to setup UX.
