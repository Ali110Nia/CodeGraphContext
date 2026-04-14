#!/usr/bin/env python3
"""MCP-mode regression sentinel for read-only stability checks."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_REPO = REPO_ROOT / "tests" / "fixtures" / "sample_projects" / "sample_project"
CONTEXT_NAME = "mcp-build"


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True, text=True, capture_output=True)


def _send(proc: subprocess.Popen, message: Dict[str, Any]) -> None:
    payload = json.dumps(message).encode("utf-8")
    proc.stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload)
    proc.stdin.flush()


def _recv(proc: subprocess.Popen, timeout: int = 60) -> Dict[str, Any]:
    start = time.time()
    header = b""
    while b"\r\n\r\n" not in header:
        if time.time() - start > timeout:
            raise TimeoutError("Timeout while waiting for MCP header")
        ch = proc.stdout.read(1)
        if not ch:
            raise RuntimeError("MCP transport closed")
        header += ch

    h, body = header.split(b"\r\n\r\n", 1)
    content_length = None
    for line in h.decode(errors="replace").split("\r\n"):
        if line.lower().startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip())
            break
    if content_length is None:
        raise RuntimeError("Missing Content-Length")

    while len(body) < content_length:
        chunk = proc.stdout.read(content_length - len(body))
        if not chunk:
            raise RuntimeError("MCP transport closed while reading body")
        body += chunk

    return json.loads(body.decode("utf-8"))


def _tool_call(proc: subprocess.Popen, req_id: int, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    _send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    response = _recv(proc, timeout=120)
    if "error" in response:
        raise RuntimeError(f"Tool '{name}' RPC error: {response['error']}")
    payload = json.loads(response["result"]["content"][0]["text"])
    if isinstance(payload, dict) and "error" in payload:
        raise RuntimeError(f"Tool '{name}' returned error payload: {payload}")
    return payload


def _initialize(proc: subprocess.Popen) -> None:
    _send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "mcp-regression-canary", "version": "1"},
            },
        },
    )
    init = _recv(proc)
    if "result" not in init:
        raise RuntimeError(f"initialize failed: {init}")
    _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})


def main() -> int:
    if not FIXTURE_REPO.exists():
        print(f"fixture repo missing: {FIXTURE_REPO}")
        return 2

    py = sys.executable

    _run([py, "-m", "codegraphcontext.cli.main", "context", "create", CONTEXT_NAME, "--database", "kuzudb"], cwd=REPO_ROOT)
    _run([py, "-m", "codegraphcontext.cli.main", "index", str(FIXTURE_REPO), "--context", CONTEXT_NAME], cwd=REPO_ROOT)

    proc = subprocess.Popen(
        [
            py,
            "-m",
            "codegraphcontext.cli.main",
            "mcp",
            "start",
            "--readonly",
            "--global-context",
            "--context",
            CONTEXT_NAME,
        ],
        cwd=str(REPO_ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        _initialize(proc)

        repos = _tool_call(proc, 2, "list_indexed_repositories", {})
        if not repos.get("repositories"):
            raise RuntimeError("list_indexed_repositories returned empty repositories")

        stats = _tool_call(proc, 3, "get_repository_stats", {})
        files = int((stats.get("stats") or {}).get("files", 0))
        if files <= 0:
            raise RuntimeError(f"expected files > 0, got {files}")

        _tool_call(
            proc,
            4,
            "analyze_code_relationships",
            {"query_type": "find_all_callers", "target": "process_data", "repo_path": str(FIXTURE_REPO)},
        )
        _tool_call(
            proc,
            5,
            "analyze_code_relationships",
            {"query_type": "find_all_callees", "target": "bar", "repo_path": str(FIXTURE_REPO)},
        )
        _tool_call(
            proc,
            6,
            "analyze_code_relationships",
            {"query_type": "find_importers", "target": "module_b", "repo_path": str(FIXTURE_REPO)},
        )
        _tool_call(
            proc,
            7,
            "execute_cypher_query",
            {"cypher_query": "MATCH (f:File) RETURN count(f) as file_count"},
        )

        print("MCP_REGRESSION_CANARY_OK")
        return 0
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=4)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
