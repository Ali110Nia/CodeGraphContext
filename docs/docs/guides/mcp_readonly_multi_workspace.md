# Read-only MCP + Build/Promote Workflow (Multi-Workspace)

This setup keeps MCP strictly read-only and moves all write/index operations to terminal commands.

## Goals

- One long-lived MCP instance.
- Read-only MCP tools (no graph mutation from MCP).
- Build/index in a separate context DB.
- Promote build snapshots into read context when ready.

## 1. Create contexts

```bash
cgc context create mcp-read --database kuzudb
cgc context create mcp-build --database kuzudb
```

## 2. Start read-only MCP server

```bash
./scripts/mcp_start_read_server.sh
```

For auto-restart behavior (keep one MCP instance alive across disconnects):

```bash
./scripts/mcp_start_read_server_forever.sh
```

Equivalent command:

```bash
cgc mcp start --readonly --global-context --context mcp-read
```

### Optional: systemd user service for MCP

```bash
cgc mcp-service-install --context mcp-read --unit-name cgc-mcp-read.service
cgc mcp-service-status cgc-mcp-read.service
```

Manage lifecycle:

```bash
cgc mcp-service-stop cgc-mcp-read.service --disable
cgc mcp-service-remove cgc-mcp-read.service
```

## 3. Build/reindex from terminal only

```bash
cgc index /path/to/repo --force --context mcp-build
```

Or build + promote in one step:

```bash
./scripts/mcp_reindex_build_and_promote.sh /path/to/repo [/path/to/repo2 ...]
```

### Optional: auto-promote after successful write commands

When you run write commands against `mcp-build`, CGC can automatically promote the DB snapshot to `mcp-read`.

```bash
# Enabled by default
export CGC_MCP_AUTO_PROMOTE=true
export CGC_MCP_BUILD_CONTEXT=mcp-build
export CGC_MCP_READ_CONTEXT=mcp-read
```

This auto-promote hook is applied to CLI write flows like `index`, `delete`, `clean`, `add-package`, and `bundle import`.

## 4. Promote build DB to read DB

```bash
cgc context promote-db --from-context mcp-build --to-context mcp-read
```

## Notes and edge cases

- `cgc mcp start --read-write` is rejected by policy.
- MCP uses global/shared context resolution by default (`--global-context`) to avoid CWD-local DB mismatches.
- If `promote-db` fails with lock error, stop MCP read server and retry.
- If auto-promote is enabled and target MCP is busy, write succeeds but promotion is skipped with a warning.
- MCP query calls accept `repo_path` as absolute path or unambiguous repo short-name (best-effort normalization).
- For reliable operations, avoid running promote while MCP is actively serving requests.
