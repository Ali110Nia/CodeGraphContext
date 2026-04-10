# MCP Tools Reference (Query-Only)

CodeGraphContext MCP is intentionally **read/query-only**.
All graph mutation workflows (indexing, deleting, bundle import/load, watch setup) are **CLI terminal commands only**.

## Available MCP Tools

### `find_code`
Find code snippets related to a keyword.
- Args: `query` (string), `fuzzy_search` (boolean), `edit_distance` (number), `repo_path` (optional)
- Returns: Name/content matches, ranked results

### `analyze_code_relationships`
Analyze relationships between code elements.
- Args:
  - `query_type` (enum): `find_callers`, `find_callees`, `find_all_callers`, `find_all_callees`, `find_importers`, `who_modifies`, `class_hierarchy`, `overrides`, `dead_code`, `call_chain`, `module_deps`, `variable_scope`, `find_complexity`, `find_functions_by_argument`, `find_functions_by_decorator`
  - `target` (string)
  - `context` (optional string)
  - `repo_path` (optional string)
- Returns: Relationship analysis results and summary

### `find_dead_code`
Find potentially unused functions.
- Args: `exclude_decorated_with` (optional string array), `repo_path` (optional)
- Returns: Potentially unused function list

### `calculate_cyclomatic_complexity`
Get complexity of a specific function.
- Args: `function_name` (string), `path` (optional), `repo_path` (optional)
- Returns: Function complexity details

### `find_most_complex_functions`
Get top complex functions.
- Args: `limit` (integer, optional), `repo_path` (optional)
- Returns: Functions sorted by complexity

### `list_indexed_repositories`
List currently indexed repositories.
- Args: none
- Returns: Repository list with path metadata

### `get_repository_stats`
Get repository statistics.
- Args: `repo_path` (optional)
- Returns: Counts for repositories/files/functions/classes/modules

### `check_job_status`
Check status of a background job.
- Args: `job_id` (string)
- Returns: Job state and progress

### `list_jobs`
List tracked jobs.
- Args: none
- Returns: Job list with status metadata

### `search_registry_bundles`
Search the bundle registry.
- Args: `query` (optional), `unique_only` (optional boolean)
- Returns: Bundle registry matches

### `execute_cypher_query`
Run a direct **read-only** Cypher query.
- Args: `cypher_query` (string)
- Returns: Raw query results

### `visualize_graph_query`
Generate a URL to visualize a Cypher query result.
- Args: `cypher_query` (string)
- Returns: Visualization URL

---

## Not Available in MCP (CLI-only)

Use terminal commands for these workflows:
- Code indexing (`cgc index`, `cgc add-package`)
- Repository deletion (`cgc delete`)
- Bundle import/load (`cgc bundle import`, `cgc bundle load`)
- File watcher workflows (`cgc watch`, `cgc watch-service-*`)
