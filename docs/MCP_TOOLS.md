# MCP Tools Reference

This document describes the Model Context Protocol (MCP) tools currently exposed by CodeGraphContext.

CodeGraphContext MCP is query-focused in this branch: index/build/write operations are executed from terminal CLI commands, while MCP serves read/query tools.

## Tool catalog (14 tools)

The server registers tool definitions from `src/codegraphcontext/tool_definitions.py`.

### Context management

- `discover_codegraph_contexts`: Scan child directories for `.codegraphcontext` folders with indexed DBs.
- `switch_context`: Switch the MCP session to another context DB.

### Analysis and search

- `find_code`: Keyword/fuzzy code search.
- `analyze_code_relationships`: Callers/callees/imports/hierarchy/dead-code style relationship queries.
- `find_dead_code`: Find potentially unused functions.
- `calculate_cyclomatic_complexity`: Complexity for one function.
- `find_most_complex_functions`: Rank functions by complexity.

### Repository and stats

- `list_indexed_repositories`: List indexed repositories.
- `get_repository_stats`: Aggregate stats for one repo or overall DB.

### Jobs

- `list_jobs`: List background jobs.
- `check_job_status`: Inspect a specific job.

### Advanced query and registry

- `execute_cypher_query`: Read-only Cypher query execution.
- `visualize_graph_query`: Visualization URL for graph queries.
- `search_registry_bundles`: Search bundle registry metadata.

## Read-only MCP + Build/Promote workflow

For production-style operation, use MCP in read-only mode and run indexing/writes in a separate build context:

- MCP server: `cgc mcp start --readonly --context mcp-read --global-context`
- Build/index in terminal: `cgc index /path/to/repo --context mcp-build`
- Promote DB snapshot: `cgc context promote-db --from-context mcp-build --to-context mcp-read`

Detailed workflow:
- `docs/docs/guides/mcp_readonly_multi_workspace.md`
- `docs/mcp_readonly_multi_workspace.md` (repository-level note)
