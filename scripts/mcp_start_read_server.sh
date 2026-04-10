#!/usr/bin/env bash
set -euo pipefail

READ_CONTEXT="${CGC_MCP_READ_CONTEXT:-mcp-read}"
CGC_BIN="${CGC_BIN:-}"

if [[ -z "${CGC_BIN}" ]]; then
  if command -v cgc >/dev/null 2>&1; then
    CGC_BIN="$(command -v cgc)"
  elif [[ -x "/workspace/.venv-mcp/bin/cgc" ]]; then
    CGC_BIN="/workspace/.venv-mcp/bin/cgc"
  else
    echo "ERROR: Unable to locate 'cgc'. Set CGC_BIN or add cgc to PATH." >&2
    exit 1
  fi
fi

exec "$CGC_BIN" mcp start --readonly --global-context --context "$READ_CONTEXT"
