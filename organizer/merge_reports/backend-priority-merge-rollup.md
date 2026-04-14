# Backend Priority Merge Rollup

## Target Commits
1. `8d7a6dd`
2. `4bcbeb4`
3. `e288331`
4. `c8388a6` (backend-only residual audit)

## Outcome Summary
- `8d7a6dd`: **partially merged** (dynamic MCP version reporting imported).
- `4bcbeb4`: **already integrated/no-op** after conflict audit.
- `e288331`: **partially merged** (OpenCode setup flow + CLI docs imported).
- `c8388a6`: **backend already integrated/no-op**.

## Applied Files
- `src/codegraphcontext/server.py`
- `src/codegraphcontext/cli/setup_wizard.py`
- `src/codegraphcontext/cli/main.py`

## No-Op/Already-Integrated Areas
- `config_manager.py` workspace mapping/discovery
- `tool_definitions.py` context switch/discovery tools
- `cli_helpers.py` repo matching and distinct file counting
- `code_finder.py` backend-aware fuzzy search safeguards
- `graph_builder.py`/`indexing/pipeline.py` unsupported-file behavior

## Validation Plan
1. Unit tests for server/indexing/code-finder touched paths.
2. MCP startup smoke: `cgc mcp start --readonly`.
3. Runtime force-index smoke on Subproject-HMM.
