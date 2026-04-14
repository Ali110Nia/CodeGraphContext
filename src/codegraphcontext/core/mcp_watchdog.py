"""MCP stability watchdog helpers.

This module intentionally keeps diagnostics machine-readable and lightweight
for tool responses while writing richer telemetry as JSON lines to the MCP
log file.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from codegraphcontext.cli.config_manager import get_config_value, resolve_context
from codegraphcontext.core import get_database_manager
from codegraphcontext.tools.code_finder import CodeFinder


def startup_strict_mode_enabled() -> bool:
    """Return True when MCP startup should fail hard on health-gate errors."""
    return not str(os.getenv("CGC_MCP_STARTUP_STRICT", "true")).strip().lower() in {"0", "false", "no", "off"}


def _watchdog_log_path() -> Path:
    explicit = os.getenv("CGC_MCP_WATCHDOG_LOG_PATH")
    if explicit:
        return Path(explicit).expanduser()
    configured = get_config_value("LOG_FILE_PATH")
    if configured:
        return Path(str(configured)).expanduser()
    return Path.home() / ".codegraphcontext" / "logs" / "cgc.log"


def watchdog_log(event: str, payload: Dict[str, Any]) -> None:
    """Write structured watchdog telemetry to file only (never stdout/stderr)."""
    record = {
        "ts": int(time.time() * 1000),
        "component": "mcp_watchdog",
        "event": event,
        "payload": payload,
    }
    path = _watchdog_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True) + "\n")
    except Exception:
        # Never break server behavior on logging failures.
        return


def infer_context_path_from_db_path(db_path: str) -> Optional[str]:
    if not db_path:
        return None
    p = Path(db_path).resolve()
    s = str(p)
    marker = "/.codegraphcontext/db/"
    if marker in s:
        return s.split(marker, 1)[0] + "/.codegraphcontext"
    if s.endswith("/.codegraphcontext"):
        return s
    return str(p.parent)


def make_error_payload(
    *,
    error_code: str,
    message: str,
    db_path: Optional[str],
    context_path: Optional[str],
    retryable: bool,
    tool_name: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "error": message,
        "error_code": error_code,
        "retryable": retryable,
        "context_path": context_path,
        "db_path": db_path,
    }
    if tool_name:
        payload["tool_name"] = tool_name
    if extra:
        payload.update(extra)
    return payload


def run_startup_health_gate(
    *,
    resolved_context,
    cwd: Path,
    context_override: Optional[str],
    skip_local_context: bool,
    mcp_lock_fd: Optional[int],
    db_read_only: bool,
) -> Dict[str, Any]:
    """Run startup canaries and return a structured result payload."""
    started = time.perf_counter()
    canaries: list[Dict[str, Any]] = []

    context_path = infer_context_path_from_db_path(getattr(resolved_context, "db_path", ""))
    base = {
        "database": getattr(resolved_context, "database", None),
        "db_path": getattr(resolved_context, "db_path", None),
        "context_path": context_path,
        "cwd": str(cwd),
    }

    lock_ok = True
    lock_details = "not_applicable"
    if getattr(resolved_context, "database", "") == "kuzudb":
        lock_ok = mcp_lock_fd is not None
        lock_details = "lock_fd_present" if lock_ok else "missing_lock_fd"
    canaries.append({"name": "mcp_lock", "ok": lock_ok, "details": lock_details})

    context_ok = True
    context_details = "matched"
    try:
        expected = resolve_context(
            cli_context=context_override,
            cwd=cwd,
            skip_local=skip_local_context,
        )
        context_ok = (
            getattr(expected, "db_path", None) == getattr(resolved_context, "db_path", None)
            and getattr(expected, "database", None) == getattr(resolved_context, "database", None)
        )
        if not context_ok:
            context_details = {
                "expected_db_path": getattr(expected, "db_path", None),
                "resolved_db_path": getattr(resolved_context, "db_path", None),
                "expected_database": getattr(expected, "database", None),
                "resolved_database": getattr(resolved_context, "database", None),
            }
    except Exception as exc:
        context_ok = False
        context_details = f"resolve_context_failed: {exc}"
    canaries.append({"name": "context_integrity", "ok": context_ok, "details": context_details})

    manager = None
    try:
        manager = get_database_manager(
            db_path=getattr(resolved_context, "db_path", None),
            read_only=db_read_only,
        )
        manager.get_driver()
        finder = CodeFinder(manager)

        repos_ok = True
        repos_details: Any = "ok"
        try:
            repos = finder.list_indexed_repositories()
            repos_details = {"repository_count": len(repos)}
        except Exception as exc:
            repos_ok = False
            repos_details = f"list_indexed_repositories_failed: {exc}"
        canaries.append({"name": "list_indexed_repositories", "ok": repos_ok, "details": repos_details})

        stats_ok = True
        stats_details: Any = "ok"
        file_count_ok = True
        file_count_details: Any = "ok"
        with manager.get_driver().session() as session:
            try:
                repos_count = session.run("MATCH (r:Repository) RETURN count(r) as c").single()["c"]
                funcs_count = session.run("MATCH (f:Function) RETURN count(f) as c").single()["c"]
                stats_details = {
                    "repositories": int(repos_count or 0),
                    "functions": int(funcs_count or 0),
                }
            except Exception as exc:
                stats_ok = False
                stats_details = f"stats_query_failed: {exc}"

            try:
                file_count = session.run("MATCH (f:File) RETURN count(f) as c").single()["c"]
                file_count_details = {"file_count": int(file_count or 0)}
            except Exception as exc:
                file_count_ok = False
                file_count_details = f"file_count_query_failed: {exc}"

        canaries.append({"name": "stats_query", "ok": stats_ok, "details": stats_details})
        canaries.append({"name": "file_count_query", "ok": file_count_ok, "details": file_count_details})
    except Exception as exc:
        canaries.append({"name": "db_connectivity", "ok": False, "details": str(exc)})
    finally:
        if manager is not None:
            try:
                manager.close_driver()
            except Exception:
                pass

    ok = all(bool(item.get("ok")) for item in canaries)
    duration_ms = int((time.perf_counter() - started) * 1000)

    payload = {
        **base,
        "ok": ok,
        "duration_ms": duration_ms,
        "canary_results": canaries,
    }

    if not ok:
        payload.update(
            {
                "error_code": "MCP_STARTUP_HEALTH_GATE_FAILED",
                "message": "MCP startup health gate failed; avoid MCP and use non-MCP fallback.",
                "action_hint": "MCP_DISABLED_USE_NON_MCP_FALLBACK",
            }
        )

    watchdog_log("startup_health_gate", payload)
    return payload
