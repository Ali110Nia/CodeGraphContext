"""Process lock helpers for MCP server mode coordination."""

from __future__ import annotations

import os
from pathlib import Path

try:
    import fcntl  # Unix-only
except ImportError:  # pragma: no cover - non-Unix fallback
    fcntl = None


class MCPLockError(RuntimeError):
    """Raised when MCP lock acquisition fails."""


def lock_path_for_db(db_path: str) -> Path:
    """Return a lock file path colocated with the configured DB path."""
    p = Path(db_path).resolve()
    # Kùzu commonly uses suffixless file paths like ".../kuzudb".
    # Treat non-existent or file paths as files and append ".mcp.lock".
    # Only use a child lock file when the DB path is an actual directory.
    if p.exists() and p.is_dir():
        return p / ".mcp.lock"
    return Path(str(p) + ".mcp.lock")


def acquire_mcp_lock(lock_path: Path, *, read_only: bool) -> int | None:
    """Acquire a process lock for MCP mode.

    - read_only=True  -> shared lock (multiple readers allowed)
    - read_only=False -> exclusive lock (blocked by any active reader/writer)

    Returns an open file descriptor that must stay open for lock lifetime.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)

    if fcntl is None:
        # On non-Unix, retain fd without kernel lock semantics.
        return fd

    mode = fcntl.LOCK_SH if read_only else fcntl.LOCK_EX
    try:
        fcntl.flock(fd, mode | fcntl.LOCK_NB)
        return fd
    except OSError as exc:
        os.close(fd)
        if read_only:
            raise MCPLockError(
                f"Failed to acquire shared MCP lock at {lock_path}: {exc}"
            ) from exc
        raise MCPLockError(
            f"Cannot start MCP in read-write mode while another MCP process is active "
            f"(lock: {lock_path})."
        ) from exc
