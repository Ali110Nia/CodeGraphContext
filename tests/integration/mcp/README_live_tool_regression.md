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
- Baseline layer: hybrid oracle (`rg`/`grep` + structural/path consistency checks)

## What It Checks

1. `find_code` positive anchors:
- Baseline has matches (`rg`) and MCP returns non-empty results
- MCP ranked result paths overlap baseline files
- MCP ranked paths are real files on disk
- Records recall/precision style path-overlap diagnostics

2. `find_code` negative anchor:
- Random non-existent symbol must be zero in baseline and MCP

3. `analyze_code_relationships` with `find_callers`:
- For a function with live call-sites, MCP caller results must be non-zero
- Caller file paths should overlap baseline call-site files

4. `analyze_code_relationships` with `module_deps`:
- On `server.py`, if baseline import/dotted-call signals exist, MCP `import_count`/`call_count` must be non-zero
- `import_count` / `call_count` must match returned list lengths
- Returned import/call file paths must remain in the requested file scope

5. Expanded read-tool regression coverage:
- `list_indexed_repositories`: must include the live indexed repository
- `get_repository_stats`: validates repo-specific/global stats shape and consistency
- `find_most_complex_functions`: validates limit, row shape, and descending complexity order
- `find_dead_code`: validates candidate row shape and repo path scope

## Mismatch Policy

- Always emits warnings when mismatches are detected.
- Tiered strictness:
  - `CGC_MEGA_TOOL_STRICT=1` forces strict failure on mismatches.
  - If `CGC_MEGA_TOOL_STRICT` is unset, strict mode defaults to `true` in CI (`CI=1`) and `false` locally.
- Hard failures (indexing failure, tool error payload) fail regardless of strict mode.
- Mismatches are grouped by stable mismatch codes for easier CI triage.
- A JSON report file is written on every run; its absolute path is stored in
  `observations.summary.report_path` and included in mismatch warnings.

## Run

From repo root:

```bash
pytest -q tests/integration/mcp/test_mcp_live_tool_regression.py -q
```

Strict mode:

```bash
CGC_MEGA_TOOL_STRICT=1 pytest -q tests/integration/mcp/test_mcp_live_tool_regression.py -q
```

Optional report directory override:

```bash
CGC_MEGA_TOOL_REPORT_DIR=/tmp/cgc-reports pytest -q tests/integration/mcp/test_mcp_live_tool_regression.py -q
```

## Notes

- This is a live test by design; anchor selection is derived from current code.
- Because code evolves, baselines are recomputed each run to avoid stale static fixtures.
