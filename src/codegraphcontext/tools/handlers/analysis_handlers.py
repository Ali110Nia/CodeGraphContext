import re
from typing import Any, Dict, List
from ..code_finder import CodeFinder
from ...utils.debug_log import debug_log

def find_dead_code(code_finder: CodeFinder, **args) -> Dict[str, Any]:
    """Tool to find potentially dead code across the entire project."""
    exclude_decorated_with = args.get("exclude_decorated_with", [])
    repo_path = args.get("repo_path")
    try:
        debug_log(f"Finding dead code. repo_path={repo_path}")
        results = code_finder.find_dead_code(exclude_decorated_with=exclude_decorated_with, repo_path=repo_path)
        
        return {
            "success": True,
            "query_type": "dead_code",
            "results": results
        }
    except Exception as e:
        debug_log(f"Error finding dead code: {str(e)}")
        return {"error": f"Failed to find dead code: {str(e)}"}

def calculate_cyclomatic_complexity(code_finder: CodeFinder, **args) -> Dict[str, Any]:
    """Tool to calculate cyclomatic complexity for a given function."""
    function_name = args.get("function_name")
    path = args.get("path")
    repo_path = args.get("repo_path")

    try:
        debug_log(f"Calculating cyclomatic complexity for function: {function_name}, repo_path={repo_path}")
        results = code_finder.get_cyclomatic_complexity(function_name, path, repo_path=repo_path)
        
        response = {
            "success": True,
            "function_name": function_name,
            "results": results
        }
        if path:
            response["path"] = path
        
        return response
    except Exception as e:
        debug_log(f"Error calculating cyclomatic complexity: {str(e)}")
        return {"error": f"Failed to calculate cyclomatic complexity: {str(e)}"}

def find_most_complex_functions(code_finder: CodeFinder, **args) -> Dict[str, Any]:
    """Tool to find the most complex functions."""
    limit = args.get("limit", 10)
    repo_path = args.get("repo_path")
    try:
        debug_log(f"Finding the top {limit} most complex functions. repo_path={repo_path}")
        results = code_finder.find_most_complex_functions(limit, repo_path=repo_path)
        return {
            "success": True,
            "limit": limit,
            "results": results
        }
    except Exception as e:
        debug_log(f"Error finding most complex functions: {str(e)}")
        return {"error": f"Failed to find most complex functions: {str(e)}"}

def analyze_code_relationships(code_finder: CodeFinder, **args) -> Dict[str, Any]:
    """Tool to analyze code relationships"""
    query_type = args.get("query_type")
    target = args.get("target")
    context = args.get("context")
    repo_path = args.get("repo_path")

    if not query_type or not target:
        return {
            "error": "Both 'query_type' and 'target' are required",
            "supported_query_types": [
                "find_callers", "find_callees", "find_all_callers", "find_all_callees", "find_importers", "who_modifies",
                "class_hierarchy", "overrides", "dead_code", "call_chain",
                "module_deps", "variable_scope", "find_complexity", "find_functions_by_argument", "find_functions_by_decorator"
            ]
        }
    
    try:
        debug_log(f"Analyzing relationships: {query_type} for {target}, repo_path={repo_path}")
        analysis = code_finder.analyze_code_relationships(query_type, target, context, repo_path=repo_path)
        if not isinstance(analysis, dict):
            return {
                "success": True,
                "query_type": query_type,
                "target": target,
                "context": context,
                "results": analysis,
            }

        response: Dict[str, Any] = {"success": "error" not in analysis}

        # Prefer analyzer-provided metadata, fall back to request args.
        response["query_type"] = analysis.get("query_type", query_type)
        response["target"] = analysis.get("target", target)
        response["context"] = analysis.get("context", context)

        # Keep payload flat at top-level to avoid results.results nesting.
        for key, value in analysis.items():
            if key in {"query_type", "target", "context"}:
                continue
            response[key] = value

        return response
    
    except Exception as e:
        debug_log(f"Error analyzing relationships: {str(e)}")
        return {"error": f"Failed to analyze relationships: {str(e)}"}

def find_code(code_finder: CodeFinder, **args) -> Dict[str, Any]:
    """Tool to find relevant code snippets"""
    query = args.get("query")
    DEFAULT_EDIT_DISTANCE = 2
    DEFAULT_FUZZY_SEARCH = False
    
    fuzzy_search = args.get("fuzzy_search", DEFAULT_FUZZY_SEARCH)
    edit_distance = args.get("edit_distance", DEFAULT_EDIT_DISTANCE)
    repo_path = args.get("repo_path")

    if fuzzy_search:
        # Preserve case for Lucene / Levenshtein name matching; lowercasing breaks
        # camelCase fuzzy hits.
        query = query.replace("_", " ").strip()

    def _candidate_queries(raw: str) -> List[str]:
        candidates: List[str] = []
        base = (raw or "").strip()
        if not base:
            return candidates
        candidates.append(base)

        class_match = re.match(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", base)
        if class_match:
            candidates.append(class_match.group(1))

        def_match = re.match(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", base)
        if def_match:
            candidates.append(def_match.group(1))

        # Preserve order but drop duplicates.
        uniq: List[str] = []
        seen = set()
        for q in candidates:
            if q not in seen:
                uniq.append(q)
                seen.add(q)
        return uniq
        
    try:
        debug_log(f"Finding code for query: {query} with fuzzy_search={fuzzy_search}, edit_distance={edit_distance}, repo_path={repo_path}")

        candidates = _candidate_queries(query)
        if not candidates:
            return {"error": "Query cannot be empty."}

        best_results = None
        best_count = -1
        for candidate in candidates:
            result = code_finder.find_related_code(candidate, fuzzy_search, edit_distance, repo_path=repo_path)
            total = int(result.get("total_matches", 0))
            if total > best_count:
                best_results = result
                best_count = total
            if total > 0:
                break

        results = best_results if best_results is not None else code_finder.find_related_code(query, fuzzy_search, edit_distance, repo_path=repo_path)

        return {"success": True, "query": query, "results": results}
    
    except Exception as e:
        debug_log(f"Error finding code: {str(e)}")
        return {"error": f"Failed to find code: {str(e)}"}
