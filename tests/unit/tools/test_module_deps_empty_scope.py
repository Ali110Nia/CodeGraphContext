from __future__ import annotations

from typing import Any, Dict, List

from codegraphcontext.tools.code_finder import CodeFinder


class _FakeResult:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows

    def data(self):
        return self._rows


class _FakeSession:
    def __init__(self, state: Dict[str, Any]):
        self._state = state

    def run(self, query: str, **kwargs: Any):
        self._state.setdefault("queries", []).append({"query": query, "params": kwargs})

        q = " ".join(query.split())
        if "MATCH (f:File)" in q and "RETURN count(f) as file_count" in q:
            return _FakeResult([{"file_count": self._state.get("file_count", 0)}])

        if "MATCH (file:File)-[imp:IMPORTS]->(module:Module" in q and "MATCH (caller:Function" in q:
            return _FakeResult(self._state.get("calls_rows", []))

        if "MATCH (file:File)-[imp:IMPORTS]->(module:Module" in q:
            return _FakeResult(self._state.get("imports_rows", []))

        if "MATCH (caller:Function)-[call:CALLS]->(callee)" in q:
            return _FakeResult(self._state.get("calls_rows", []))

        return _FakeResult([])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeDriver:
    def __init__(self, state: Dict[str, Any]):
        self._state = state

    def session(self):
        return _FakeSession(self._state)


class _FakeDBManager:
    def __init__(self, state: Dict[str, Any]):
        self._state = state

    def get_driver(self):
        return _FakeDriver(self._state)

    def get_backend_type(self) -> str:
        # Keep tests simple and avoid Kuzu FTS bootstrap side effects in __init__.
        return "neo4j"


def _make_finder(state: Dict[str, Any]) -> CodeFinder:
    return CodeFinder(_FakeDBManager(state))


def test_module_deps_reports_error_when_repo_scope_has_no_indexed_files():
    finder = _make_finder({"file_count": 0})

    result = finder.analyze_code_relationships(
        query_type="module_deps",
        target="hmm_pipeline_v3.modelling.tft.asp.training",
        repo_path="Subproject-HMM",
    )

    assert result["query_type"] == "module_dependencies"
    assert "error" in result
    assert "No indexed files found" in result["error"]
    assert result["results"]["diagnostic"]["code"] == "REPO_SCOPE_EMPTY"


def test_module_deps_preserves_existing_behavior_when_scope_is_indexed():
    state = {
        "file_count": 5,
        "imports_rows": [
            {
                "importer_file_path": "/workspace/Subproject-HMM/hmm_pipeline_v3/modelling/tft/asp/block.py",
                "import_line_number": 11,
                "import_alias": None,
                "imported_module": "hmm_pipeline_v3.modelling.tft.asp.training",
                "file_is_dependency": False,
            }
        ],
        "calls_rows": [
            {
                "caller_function": "run",
                "caller_file_path": "/workspace/Subproject-HMM/hmm_pipeline_v3/modelling/tft/asp/block.py",
                "call_line_number": 28,
                "full_call_name": "TftAspTraining",
                "callee_name": "TftAspTraining",
                "callee_file_path": "/workspace/Subproject-HMM/hmm_pipeline_v3/modelling/tft/asp/training.py",
                "resolution_source": "heuristic",
            }
        ],
    }
    finder = _make_finder(state)

    result = finder.analyze_code_relationships(
        query_type="module_deps",
        target="hmm_pipeline_v3.modelling.tft.asp.training",
        repo_path="Subproject-HMM",
    )

    assert "error" not in result
    assert result["results"]["import_count"] == 1
    assert result["results"]["call_count"] == 1
