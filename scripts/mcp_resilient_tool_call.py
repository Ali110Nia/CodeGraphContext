#!/usr/bin/env python3
"""Execute one MCP tool call with restart/replay-once transport resilience.

This helper is intentionally narrow: it starts a local read-only MCP server,
performs one tool call, and retries exactly once when transport closes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any, Dict


def _send(proc: subprocess.Popen, message: Dict[str, Any]) -> None:
    payload = json.dumps(message).encode("utf-8")
    proc.stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload)
    proc.stdin.flush()


def _recv(proc: subprocess.Popen, timeout: int = 30) -> Dict[str, Any]:
    start = time.time()
    header = b""
    while b"\r\n\r\n" not in header:
        if time.time() - start > timeout:
            raise TimeoutError("Timed out while waiting for MCP response header")
        ch = proc.stdout.read(1)
        if not ch:
            raise RuntimeError("Transport closed while reading response header")
        header += ch

    h, body = header.split(b"\r\n\r\n", 1)
    content_length = None
    for line in h.decode(errors="replace").split("\r\n"):
        if line.lower().startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip())
            break
    if content_length is None:
        raise RuntimeError("Missing Content-Length header in MCP response")

    while len(body) < content_length:
        chunk = proc.stdout.read(content_length - len(body))
        if not chunk:
            raise RuntimeError("Transport closed while reading response body")
        body += chunk

    return json.loads(body.decode("utf-8"))


def _start_server(command: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )


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
                "clientInfo": {"name": "mcp-resilient-tool-call", "version": "1"},
            },
        },
    )
    init = _recv(proc, timeout=30)
    if "result" not in init:
        raise RuntimeError(f"MCP initialize failed: {init}")
    _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})


def _single_tool_call(proc: subprocess.Popen, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
    _send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": tool_args},
        },
    )
    response = _recv(proc, timeout=120)
    if "error" in response:
        return {"ok": False, "response": response}
    try:
        parsed = json.loads(response["result"]["content"][0]["text"])
    except Exception:
        parsed = response
    return {"ok": True, "response": parsed}


def _build_server_command(context: str | None) -> list[str]:
    cmd = [sys.executable, "-m", "codegraphcontext.cli.main", "mcp", "start", "--readonly", "--global-context"]
    if context:
        cmd.extend(["--context", context])
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", default=None)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--args-json", default="{}")
    args = parser.parse_args()

    try:
        tool_args = json.loads(args.args_json)
    except Exception as exc:
        print(json.dumps({"ok": False, "error_code": "INVALID_ARGS_JSON", "error": str(exc)}))
        return 2

    command = _build_server_command(args.context)

    for attempt in (1, 2):
        proc = _start_server(command)
        try:
            _initialize(proc)
            result = _single_tool_call(proc, args.tool, tool_args)
            print(json.dumps({"ok": True, "attempt": attempt, "result": result["response"]}))
            return 0
        except Exception as exc:
            stderr_text = ""
            try:
                stderr_text = proc.stderr.read().decode("utf-8", errors="replace")[-1200:]
            except Exception:
                stderr_text = ""

            payload = {
                "ok": False,
                "attempt": attempt,
                "error_code": "MCP_TRANSPORT_CLOSED",
                "error": str(exc),
                "action_hint": "MCP_DISABLED_USE_NON_MCP_FALLBACK" if attempt == 2 else "MCP_RESTART_AND_RETRY",
                "stderr_tail": stderr_text,
            }
            if attempt == 2:
                print(json.dumps(payload))
                return 1
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                proc.kill()

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
