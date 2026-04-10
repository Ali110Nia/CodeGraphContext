from __future__ import annotations

from types import SimpleNamespace

import codegraphcontext.cli.main as main_mod


def test_auto_promote_skips_when_no_write(monkeypatch):
    called = {"promoted": False}

    monkeypatch.setenv("CGC_MCP_AUTO_PROMOTE", "true")
    monkeypatch.setattr(
        main_mod,
        "resolve_context",
        lambda **_kwargs: SimpleNamespace(
            mode="named",
            context_name="mcp-build",
            database="kuzudb",
            db_path="/tmp/build.kuzu",
        ),
    )
    monkeypatch.setattr(main_mod, "_promote_db_snapshot", lambda *_args, **_kwargs: called.__setitem__("promoted", True))

    main_mod._maybe_auto_promote_after_write(context="mcp-build", write_performed=False, action="index")

    assert called["promoted"] is False


def test_auto_promote_runs_for_build_context(monkeypatch):
    calls = {"promote": 0}

    monkeypatch.setenv("CGC_MCP_AUTO_PROMOTE", "true")
    monkeypatch.setenv("CGC_MCP_BUILD_CONTEXT", "mcp-build")
    monkeypatch.setenv("CGC_MCP_READ_CONTEXT", "mcp-read")

    def _resolve_context(**kwargs):
        cli_context = kwargs.get("cli_context")
        if cli_context in (None, "mcp-build"):
            return SimpleNamespace(
                mode="named",
                context_name="mcp-build",
                database="kuzudb",
                db_path="/tmp/build.kuzu",
            )
        return SimpleNamespace(
            mode="named",
            context_name="mcp-read",
            database="kuzudb",
            db_path="/tmp/read.kuzu",
        )

    monkeypatch.setattr(main_mod, "resolve_context", _resolve_context)
    monkeypatch.setattr(main_mod, "acquire_mcp_lock", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_mod, "_promote_db_snapshot", lambda *_args, **_kwargs: calls.__setitem__("promote", calls["promote"] + 1))

    main_mod._maybe_auto_promote_after_write(context="mcp-build", write_performed=True, action="index")

    assert calls["promote"] == 1


def test_auto_promote_skips_non_build_context(monkeypatch):
    calls = {"promote": 0}

    monkeypatch.setenv("CGC_MCP_AUTO_PROMOTE", "true")
    monkeypatch.setenv("CGC_MCP_BUILD_CONTEXT", "mcp-build")

    def _resolve_context(**kwargs):
        cli_context = kwargs.get("cli_context")
        if cli_context in (None, "dev-context"):
            return SimpleNamespace(
                mode="named",
                context_name="dev-context",
                database="kuzudb",
                db_path="/tmp/dev.kuzu",
            )
        return SimpleNamespace(
            mode="named",
            context_name=cli_context,
            database="kuzudb",
            db_path=f"/tmp/{cli_context}.kuzu",
        )

    monkeypatch.setattr(main_mod, "resolve_context", _resolve_context)
    monkeypatch.setattr(main_mod, "_promote_db_snapshot", lambda *_args, **_kwargs: calls.__setitem__("promote", calls["promote"] + 1))

    main_mod._maybe_auto_promote_after_write(context="dev-context", write_performed=True, action="delete")

    assert calls["promote"] == 0
