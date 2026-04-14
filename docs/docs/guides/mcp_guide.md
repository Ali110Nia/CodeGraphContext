# Using with AI (MCP Guide)

The Model Context Protocol (MCP) allows AI assistants to query CodeGraphContext directly.

## 1. Run the MCP setup wizard

```bash
cgc mcp setup
```

The wizard writes client MCP config and server command/env wiring.

## 2. Start MCP server

Recommended command:

```bash
cgc mcp start --readonly --global-context --context mcp-read
```

For long-running usage, you can install a user service:

```bash
cgc mcp-service-install --context mcp-read --unit-name cgc-mcp-read.service
cgc mcp-service-status cgc-mcp-read.service
```

## 3. Supported clients

| Client | Setup Method | Notes |
| :--- | :--- | :--- |
| Cursor | Automatic | MCP feature enabled in client settings. |
| Claude Desktop | Automatic | Standard stdio MCP config. |
| VS Code | Semi-automatic | Use an MCP-capable extension/client. |
| OpenCode | Manual | Configure stdio MCP server (`cgc mcp start ...`) with matching env. |

## 4. Query workflow vs write workflow

In this branch, MCP is query-focused. Use terminal CLI for writes/indexing:

- Query via MCP tools: `find_code`, `analyze_code_relationships`, `execute_cypher_query`, etc.
- Write/index via CLI: `cgc index`, `cgc delete`, `cgc clean`, `cgc add-package`, `cgc bundle import`

Recommended split:

- Read context for MCP: `mcp-read`
- Build context for writes: `mcp-build`
- Promote from build -> read when ready.

Detailed step-by-step guide:
- [Read-only MCP + Build/Promote Workflow](mcp_readonly_multi_workspace.md)

## 5. Troubleshooting

- **MCP fails on empty read-only Kùzu DB**: startup now bootstraps schema once and reopens read-only.
- **Context mismatch**: ensure MCP uses `--global-context` and explicit `--context`.
- **General diagnostics**: run `cgc doctor`.
