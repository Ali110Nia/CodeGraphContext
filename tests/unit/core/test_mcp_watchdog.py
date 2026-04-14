from __future__ import annotations

from types import SimpleNamespace

import codegraphcontext.core.mcp_watchdog as watchdog


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def single(self):
        return {"c": self._value}


class _FakeSession:
    def run(self, query, **_kwargs):
        if "count(r:Repository)" in query:
            return _FakeResult(1)
        if "count(f:Function)" in query:
            return _FakeResult(4)
        if "count(f:File)" in query:
            return _FakeResult(3)
        return _FakeResult(0)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeDriver:
    def session(self):
        return _FakeSession()


class _FakeManager:
    def get_driver(self):
        return _FakeDriver()

    def close_driver(self):
        return None


class _FakeFinder:
    def __init__(self, _manager):
        pass

    def list_indexed_repositories(self):
        return [{"name": "sample", "path": "/tmp/sample"}]


def test_startup_health_gate_ok(monkeypatch, tmp_path):
    resolved = SimpleNamespace(database="kuzudb", db_path=str(tmp_path / "db" / "kuzudb"))

    monkeypatch.setattr(watchdog, "resolve_context", lambda **_kwargs: resolved)
    monkeypatch.setattr(watchdog, "get_database_manager", lambda **_kwargs: _FakeManager())
    monkeypatch.setattr(watchdog, "CodeFinder", _FakeFinder)

    result = watchdog.run_startup_health_gate(
        resolved_context=resolved,
        cwd=tmp_path,
        context_override="mcp-read",
        skip_local_context=True,
        mcp_lock_fd=101,
        db_read_only=True,
    )

    assert result["ok"] is True
    assert result["database"] == "kuzudb"
    assert any(item["name"] == "list_indexed_repositories" and item["ok"] for item in result["canary_results"])


def test_startup_health_gate_reports_failure(monkeypatch, tmp_path):
    resolved = SimpleNamespace(database="kuzudb", db_path=str(tmp_path / "db" / "kuzudb"))

    monkeypatch.setattr(watchdog, "resolve_context", lambda **_kwargs: resolved)

    def _raise_manager(**_kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(watchdog, "get_database_manager", _raise_manager)

    result = watchdog.run_startup_health_gate(
        resolved_context=resolved,
        cwd=tmp_path,
        context_override="mcp-read",
        skip_local_context=True,
        mcp_lock_fd=None,
        db_read_only=True,
    )

    assert result["ok"] is False
    assert result["error_code"] == "MCP_STARTUP_HEALTH_GATE_FAILED"
    assert result["action_hint"] == "MCP_DISABLED_USE_NON_MCP_FALLBACK"
    assert any(item["name"] == "mcp_lock" and not item["ok"] for item in result["canary_results"])
