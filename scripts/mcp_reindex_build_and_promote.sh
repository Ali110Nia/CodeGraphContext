#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <repo-path> [<repo-path> ...] [--verify <query> ...]" >&2
  exit 1
fi

BUILD_CONTEXT="${CGC_MCP_BUILD_CONTEXT:-mcp-build}"
READ_CONTEXT="${CGC_MCP_READ_CONTEXT:-mcp-read}"
CGC_BIN="${CGC_BIN:-cgc}"
DB_TYPE="${CGC_MCP_DB_TYPE:-kuzudb}"
FORCE_REINDEX="${CGC_MCP_FORCE_REINDEX:-true}"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ "$CGC_BIN" == */cgc ]]; then
    cand="${CGC_BIN%/cgc}/python"
    if [[ -x "$cand" ]]; then
      PYTHON_BIN="$cand"
    fi
  fi
fi
if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python"
fi

repos=()
verify_queries=()
mode="repos"

for arg in "$@"; do
  if [[ "$arg" == "--verify" ]]; then
    mode="verify"
    continue
  fi
  if [[ "$mode" == "repos" ]]; then
    repos+=("$arg")
  else
    verify_queries+=("$arg")
  fi
done

if [[ ${#repos[@]} -eq 0 ]]; then
  echo "ERROR: at least one repo path is required." >&2
  exit 1
fi

for repo in "${repos[@]}"; do
  if [[ "$FORCE_REINDEX" == "true" ]]; then
    if ! CGC_RUNTIME_DB_TYPE="$DB_TYPE" "$CGC_BIN" index "$repo" --force --context "$BUILD_CONTEXT"; then
      echo "WARN: force reindex failed for $repo; retrying non-force index." >&2
      CGC_RUNTIME_DB_TYPE="$DB_TYPE" "$CGC_BIN" index "$repo" --context "$BUILD_CONTEXT"
    fi
  else
    CGC_RUNTIME_DB_TYPE="$DB_TYPE" "$CGC_BIN" index "$repo" --context "$BUILD_CONTEXT"
  fi
done

CGC_RUNTIME_DB_TYPE="$DB_TYPE" "$CGC_BIN" context promote-db --from-context "$BUILD_CONTEXT" --to-context "$READ_CONTEXT"

if [[ ${#verify_queries[@]} -gt 0 ]]; then
  "$PYTHON_BIN" - "$READ_CONTEXT" "${verify_queries[@]}" <<'PY'
import asyncio
import sys
from pathlib import Path
from codegraphcontext.server import MCPServer

read_context = sys.argv[1]
queries = sys.argv[2:]

async def main():
    srv = MCPServer(
        read_only_mode=True,
        db_read_only=True,
        context_override=read_context,
        skip_local_context=True,
        cwd=Path("/workspace"),
    )
    for q in queries:
        out = await srv.handle_tool_call("find_code", {"query": q})
        total = out.get("results", {}).get("total_matches")
        print(f"verify find_code[{q!r}] -> total_matches={total}")

asyncio.run(main())
PY
fi

echo "Promotion complete. Restart MCP read server to attach cleanly to the promoted snapshot."
