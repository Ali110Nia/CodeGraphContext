from __future__ import annotations

import os
from pathlib import Path

import pytest

from codegraphcontext.core.mcp_lock import MCPLockError, acquire_mcp_lock, lock_path_for_db


pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="fcntl-based lock semantics are Unix-only",
)


def test_shared_locks_can_coexist(tmp_path: Path):
    lock_path = tmp_path / "db.kuzu.mcp.lock"
    fd1 = acquire_mcp_lock(lock_path, read_only=True)
    fd2 = acquire_mcp_lock(lock_path, read_only=True)
    try:
        assert isinstance(fd1, int)
        assert isinstance(fd2, int)
    finally:
        os.close(fd1)
        os.close(fd2)


def test_lock_path_for_suffixless_db_file(tmp_path: Path):
    db_path = tmp_path / "kuzudb"
    lock_path = lock_path_for_db(str(db_path))
    assert lock_path == Path(str(db_path) + ".mcp.lock")


def test_exclusive_lock_blocked_by_active_shared_locks(tmp_path: Path):
    lock_path = tmp_path / "db.kuzu.mcp.lock"
    fd = acquire_mcp_lock(lock_path, read_only=True)
    try:
        with pytest.raises(MCPLockError):
            acquire_mcp_lock(lock_path, read_only=False)
    finally:
        os.close(fd)


def test_shared_lock_blocked_by_active_exclusive_lock(tmp_path: Path):
    lock_path = tmp_path / "db.kuzu.mcp.lock"
    fd = acquire_mcp_lock(lock_path, read_only=False)
    try:
        with pytest.raises(MCPLockError):
            acquire_mcp_lock(lock_path, read_only=True)
    finally:
        os.close(fd)
