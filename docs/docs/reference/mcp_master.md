# MCP Reference (Master List)

This page documents MCP tools currently exposed by CodeGraphContext in this branch.

## Scope

MCP is query-focused. Indexing and mutating operations are performed through CLI commands, not MCP tools.

## Context tools

| Tool | Description |
| :--- | :--- |
| `discover_codegraph_contexts` | Discover child `.codegraphcontext` databases from a root path. |
| `switch_context` | Switch active MCP query context to another DB. |

## Query and analysis tools

| Tool | Description |
| :--- | :--- |
| `find_code` | Search code by term/fuzzy query. |
| `analyze_code_relationships` | Relationship queries (callers/callees/importers/hierarchy/dead-code patterns). |
| `find_dead_code` | Find potentially unused functions. |
| `calculate_cyclomatic_complexity` | Complexity for a specific function. |
| `find_most_complex_functions` | Rank functions by complexity. |
| `execute_cypher_query` | Read-only Cypher query execution. |
| `visualize_graph_query` | Graph visualization URL generation. |

## Repository and registry tools

| Tool | Description |
| :--- | :--- |
| `list_indexed_repositories` | List indexed repositories in current DB. |
| `get_repository_stats` | Repository/global graph statistics. |
| `search_registry_bundles` | Search registry bundles metadata. |

## Job tools

| Tool | Description |
| :--- | :--- |
| `list_jobs` | List background jobs. |
| `check_job_status` | Check job status by id. |

## Read-only MCP + build/promote notes

- Start MCP read server with `--readonly` in a read context.
- Run indexing/writes in build context via terminal CLI.
- Promote build DB snapshots into read context when ready.

Guide:
- [Read-only MCP + Build/Promote Workflow](../guides/mcp_readonly_multi_workspace.md)
