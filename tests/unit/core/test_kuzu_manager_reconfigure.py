from __future__ import annotations

from codegraphcontext.core.database_kuzu import KuzuDBManager


def _reset_singleton():
    KuzuDBManager._instance = None
    KuzuDBManager._db = None
    KuzuDBManager._conn = None


def test_kuzu_manager_reconfigure_resets_existing_connection(monkeypatch):
    _reset_singleton()
    monkeypatch.setenv("CGC_KUZU_READ_ONLY", "false")

    manager = KuzuDBManager(db_path="/tmp/cgc-a/kuzudb", read_only=False)
    manager._conn = object()
    manager._db = object()

    manager2 = KuzuDBManager(db_path="/tmp/cgc-b/kuzudb", read_only=False)

    assert manager2 is manager
    assert manager2.db_path == "/tmp/cgc-b/kuzudb"
    assert manager2.read_only is False
    assert manager2._conn is None
    assert manager2._db is None


def test_kuzu_manager_same_config_keeps_existing_connection(monkeypatch):
    _reset_singleton()
    monkeypatch.setenv("CGC_KUZU_READ_ONLY", "false")

    manager = KuzuDBManager(db_path="/tmp/cgc-same/kuzudb", read_only=False)
    sentinel_conn = object()
    sentinel_db = object()
    manager._conn = sentinel_conn
    manager._db = sentinel_db

    manager2 = KuzuDBManager(db_path="/tmp/cgc-same/kuzudb", read_only=False)

    assert manager2 is manager
    assert manager2._conn is sentinel_conn
    assert manager2._db is sentinel_db
