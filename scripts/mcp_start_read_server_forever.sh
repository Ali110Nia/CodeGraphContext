#!/usr/bin/env bash
set -euo pipefail

READ_CONTEXT="${CGC_MCP_READ_CONTEXT:-mcp-read}"
SLEEP_SECONDS="${CGC_MCP_RESTART_DELAY_SECONDS:-2}"
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

stop_requested=0
trap 'stop_requested=1' INT TERM

while [[ "$stop_requested" -eq 0 ]]; do
  "$CGC_BIN" mcp start --readonly --global-context --context "$READ_CONTEXT" || true
  if [[ "$stop_requested" -eq 1 ]]; then
    break
  fi
  sleep "$SLEEP_SECONDS"
done
