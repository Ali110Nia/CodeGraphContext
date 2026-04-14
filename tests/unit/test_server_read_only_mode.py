from __future__ import annotations

import asyncio
from dataclasses import dataclass
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


def test_discover_codegraph_contexts_tool(monkeypatch, patched_server_deps):
    @dataclass
    class _Ctx:
        path: str
        cgc_path: str
        repo_name: str
        database: str
        db_path: str
        cgcignore_path: str

    monkeypatch.setattr(
        server_mod,
        "discover_child_contexts",
        lambda **_kwargs: [
            _Ctx(
                path="/workspace/repo",
                cgc_path="/workspace/repo/.codegraphcontext",
                repo_name="repo",
                database="kuzudb",
                db_path="/workspace/repo/.codegraphcontext/db/kuzudb",
                cgcignore_path="/workspace/repo/.codegraphcontext/.cgcignore",
            )
        ],
    )

    srv = server_mod.MCPServer(read_only_mode=True, db_read_only=True)
    result = srv.discover_codegraph_contexts_tool(path="/workspace", max_depth=2)
    assert result["success"] is True
    assert result["count"] == 1
    assert result["contexts"][0]["database"] == "kuzudb"


def test_switch_context_tool_saves_mapping(monkeypatch, tmp_path, patched_server_deps):
    repo = tmp_path / "repo"
    cgc_dir = repo / ".codegraphcontext"
    cgc_dir.mkdir(parents=True)

    saved = {"called": False}

    monkeypatch.setattr(
        server_mod,
        "resolve_context",
        lambda **_kwargs: SimpleNamespace(
            is_local=True,
            database="kuzudb",
            db_path=str(cgc_dir / "db" / "kuzudb"),
        ),
    )
    monkeypatch.setattr(
        server_mod,
        "save_workspace_mapping",
        lambda *_args, **_kwargs: saved.__setitem__("called", True),
    )
    monkeypatch.setattr(server_mod, "remove_workspace_mapping", lambda *_args, **_kwargs: None)

    srv = server_mod.MCPServer(read_only_mode=True, db_read_only=True)
    monkeypatch.setattr(srv, "_connect_to_context", lambda _ctx: None)

    result = srv.switch_context_tool(context_path=str(repo), save=True)
    assert result["success"] is True
    assert result["database"] == "kuzudb"
    assert saved["called"] is True
