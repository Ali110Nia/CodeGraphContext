from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import codegraphcontext.server as server_mod


class _FakeDBManager:
    def get_driver(self):
        return object()

    def is_connected(self):
        return True

    def close_driver(self):
        return None


class _FakeCodeFinder:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def list_indexed_repositories(self):
        return []


@pytest.fixture
def patched_server_deps(monkeypatch):
    monkeypatch.setattr(
        server_mod,
        "resolve_context",
        lambda **_kwargs: SimpleNamespace(database="kuzudb", db_path="/tmp/test.kuzu"),
    )
    monkeypatch.setattr(server_mod, "get_database_manager", lambda db_path=None, read_only=None: _FakeDBManager())
    monkeypatch.setattr(server_mod, "CodeFinder", _FakeCodeFinder)


def test_read_only_mode_hides_write_tools(patched_server_deps):
    srv = server_mod.MCPServer(read_only_mode=True, db_read_only=True)
    tool_names = set(srv.tools.keys())
    forbidden = {
        "add_code_to_graph",
        "add_package_to_graph",
        "watch_directory",
        "delete_repository",
        "unwatch_directory",
        "load_bundle",
        "list_watched_paths",
    }
    for tool in forbidden:
        assert tool not in tool_names


def test_read_write_mode_also_hides_write_tools(patched_server_deps):
    srv = server_mod.MCPServer(read_only_mode=False, db_read_only=False)
    tool_names = set(srv.tools.keys())
    forbidden = {
        "add_code_to_graph",
        "add_package_to_graph",
        "watch_directory",
        "delete_repository",
        "unwatch_directory",
        "load_bundle",
        "list_watched_paths",
    }
    for tool in forbidden:
        assert tool not in tool_names


def test_handle_tool_call_rejects_removed_write_tools(patched_server_deps):
    srv = server_mod.MCPServer(read_only_mode=True, db_read_only=True)
    result = asyncio.run(srv.handle_tool_call("add_code_to_graph", {"path": "/tmp/x"}))
    assert "error" in result
    assert "Unknown tool" in result["error"]


def test_repo_path_normalization_supports_workspace_shorthand_prefix(patched_server_deps):
    srv = server_mod.MCPServer(read_only_mode=True, db_read_only=True)
    srv.code_finder.list_indexed_repositories = lambda: [
        {"name": "hmm_pipeline_v3", "path": "/workspace/Subproject-HMM/hmm_pipeline_v3"},
    ]
    normalized = srv._normalize_repo_path_argument({"repo_path": "Subproject-HMM"})
    assert normalized["repo_path"] == "/workspace/Subproject-HMM"
