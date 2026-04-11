# Merge Report: 4bcbeb4 (`fixes kuzudb bug on windows, and context switching`)

## Feasibility
- `git apply --check`: **full conflict**
- Files checked: 4
- Conflicts: 4
  - `pyproject.toml`
  - `src/codegraphcontext/cli/config_manager.py`
  - `src/codegraphcontext/server.py`
  - `src/codegraphcontext/tool_definitions.py`

## Conflict Matrix
| File | Status | Decision | Rationale |
|---|---|---|---|
| `pyproject.toml` | conflict | **already integrated** | `kuzu` marker dependency already present. |
| `config_manager.py` | conflict | **already integrated** | workspace mapping + child context discovery functions already present. |
| `server.py` | conflict | **keep current** | context switching/discovery tools already implemented in current read-only server flow. |
| `tool_definitions.py` | conflict | **already integrated** | `discover_codegraph_contexts` and `switch_context` tool definitions already present. |

## Accepted Deltas
- No code changes required from this commit after conflict audit.

## Residual Risks
- Upstream also included legacy mutable MCP tool wiring not applicable to current read-only MCP architecture.
