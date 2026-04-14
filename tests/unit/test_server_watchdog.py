from __future__ import annotations

import asyncio
import time
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


def test_tool_timeout_returns_structured_error(monkeypatch, patched_server_deps):
    srv = server_mod.MCPServer(read_only_mode=True, db_read_only=True)

    def _slow(**_kwargs):
        time.sleep(1.2)
        return {"success": True}

    monkeypatch.setenv("CGC_MCP_TOOL_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(srv, "find_code_tool", _slow)

    result = asyncio.run(srv.handle_tool_call("find_code", {}))

    assert result["error_code"] == "MCP_TOOL_TIMEOUT"
    assert result["tool_name"] == "find_code"
    assert result["retryable"] is False


def test_retryable_error_rebinds_and_retries(monkeypatch, patched_server_deps):
    srv = server_mod.MCPServer(read_only_mode=True, db_read_only=True)

    calls = {"n": 0}

    def _flaky(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"error": "scope unavailable", "error_code": "REPO_SCOPE_EMPTY"}
        return {"success": True, "results": []}

    monkeypatch.setattr(srv, "find_code_tool", _flaky)
    monkeypatch.setattr(srv, "_attempt_context_rebind", lambda _reason: True)

    result = asyncio.run(srv.handle_tool_call("find_code", {}))

    assert result["success"] is True
    assert calls["n"] == 2


def test_plain_error_is_augmented(monkeypatch, patched_server_deps):
    srv = server_mod.MCPServer(read_only_mode=True, db_read_only=True)

    monkeypatch.setattr(srv, "find_code_tool", lambda **_kwargs: {"error": "boom"})

    result = asyncio.run(srv.handle_tool_call("find_code", {}))

    assert result["error_code"] == "MCP_TOOL_FAILED"
    assert result["tool_name"] == "find_code"
    assert "db_path" in result
    assert "context_path" in result
