from __future__ import annotations

import codegraphcontext.core as core_mod
import codegraphcontext.core.database_kuzu as kuzu_mod


def test_falkordb_unavailable_fallback_preserves_db_path(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeKuzu:
        def __init__(self, db_path=None, read_only=None):
            captured["db_path"] = db_path
            captured["read_only"] = read_only

    monkeypatch.setenv("CGC_RUNTIME_DB_TYPE", "falkordb")
    monkeypatch.setattr(core_mod, "_is_falkordb_available", lambda: False)
    monkeypatch.setattr(core_mod, "_is_kuzudb_available", lambda: True)
    monkeypatch.setattr(kuzu_mod, "KuzuDBManager", _FakeKuzu)

    core_mod.get_database_manager(db_path="/tmp/per-repo/kuzudb", read_only=True)

    assert captured["db_path"] == "/tmp/per-repo/kuzudb"
    assert captured["read_only"] is True
