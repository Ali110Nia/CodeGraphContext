# Merge Report: 8d7a6dd (`fixes misc bugs`)

## Feasibility
- `git apply --check`: **partial conflict**
- Files checked: 28
- Conflicts: 4
  - `src/codegraphcontext/server.py`
  - `src/codegraphcontext/tools/code_finder.py`
  - `src/codegraphcontext/tools/handlers/management_handlers.py`
  - `src/codegraphcontext/tools/handlers/watcher_handlers.py` (path missing in current architecture)

## Conflict Matrix
| File | Status | Decision | Rationale |
|---|---|---|---|
| `server.py` | conflict | **combine** | Keep read-only MCP architecture, import dynamic MCP version reporting. |
| `code_finder.py` | conflict | **keep current** | Current branch already contains stronger backend-aware fuzzy/FTS logic and missing-path safeguards. |
| `management_handlers.py` | conflict | **keep current** | Upstream hunk targets `load_bundle` path not used in current read-only handler surface. |
| `watcher_handlers.py` | missing path | **no-op** | Watcher handlers were removed from current MCP read-only architecture. |

## Accepted Deltas
1. Add `_get_version()` helper in `MCPServer`.
2. Use `self._get_version()` in MCP `initialize` response `serverInfo.version`.

## Residual Risks
- None from skipped hunks; skipped paths are either architectural removals or already superseded.
