# Live MCP Tool Regression Test

This document describes the mega live regression test for MCP read/query tools:

- [`test_mcp_live_tool_regression.py`](/workspace/CodeGraphContext/tests/integration/mcp/test_mcp_live_tool_regression.py)

## Purpose

Detect regressions and false results in MCP tool outputs by comparing tool-call results against live filesystem baselines from terminal commands.

The test validates real tool behavior on current code, not mocked handlers.

## Scope

- Indexed target: `src/codegraphcontext` (live repository code)
- Backend: KuzuDB (fresh temp DB per test module)
- MCP call layer: in-process `MCPServer.handle_tool_call(...)`
- Baseline layer: live `rg`/`grep` queries executed at test runtime

## What It Checks

1. `find_code` positive anchors:
- Baseline has matches (`rg`), MCP returns `total_matches > 0`
- MCP ranked result paths overlap baseline files

2. `find_code` negative anchor:
- Random non-existent symbol must be zero in baseline and MCP

3. `analyze_code_relationships` with `find_callers`:
- For a function with live call-sites, MCP caller results must be non-zero

4. `analyze_code_relationships` with `module_deps`:
- On `server.py`, if baseline import/dotted-call signals exist, MCP `import_count`/`call_count` must be non-zero

## Mismatch Policy

- Always emits warnings when mismatches are detected (diagnostic mode).
- Fails on mismatches only when strict mode is enabled:
  - `CGC_MEGA_TOOL_STRICT=1`
- Hard failures (indexing failure, tool error payload) fail regardless of strict mode.

## Run

From repo root:

```bash
pytest -q tests/integration/mcp/test_mcp_live_tool_regression.py -q
```

Strict mode:

```bash
CGC_MEGA_TOOL_STRICT=1 pytest -q tests/integration/mcp/test_mcp_live_tool_regression.py -q
```

## Notes

- This is a live test by design; anchor selection is derived from current code.
- Because code evolves, baselines are recomputed each run to avoid stale static fixtures.
