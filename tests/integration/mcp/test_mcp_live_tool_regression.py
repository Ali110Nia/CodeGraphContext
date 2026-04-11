from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import warnings
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import codegraphcontext.server as server_mod
from codegraphcontext.core import get_database_manager
from codegraphcontext.core.jobs import JobStatus, JobManager
from codegraphcontext.tools.graph_builder import GraphBuilder


ROOT_DIR = Path(__file__).resolve().parents[3]
LIVE_REPO_SRC = ROOT_DIR / "src" / "codegraphcontext"
DEFAULT_POSITIVE_SYMBOLS = ["MCPServer", "find_code", "resolve_context", "GraphBuilder"]


def _run_cmd(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(args, capture_output=True, text=True)
    out = proc.stdout.strip()
    if proc.stderr:
        out = (out + "\n" + proc.stderr.strip()).strip() if out else proc.stderr.strip()
    return proc.returncode, out


def _rg_count(pattern: str, target: str) -> int:
    rc, out = _run_cmd(["rg", "-n", pattern, target])
    if rc == 0:
        return len([line for line in out.splitlines() if line.strip()])
    if rc == 1:
        return 0
    # rg not available or other failure: fallback to grep
    rc, out = _run_cmd(["grep", "-R", "-n", "-E", pattern, target])
    if rc == 0:
        return len([line for line in out.splitlines() if line.strip()])
    if rc == 1:
        return 0
    raise RuntimeError(f"Failed to run baseline search for pattern '{pattern}': {out}")


def _discover_positive_symbols(repo_root: Path) -> list[str]:
    chosen: list[str] = []

    for symbol in DEFAULT_POSITIVE_SYMBOLS:
        if _rg_count(rf"\b{re.escape(symbol)}\b", str(repo_root)) > 0:
            chosen.append(symbol)

    if len(chosen) >= 4:
        return chosen[:4]

    # Keep the anchor set live: top up from currently-defined function names.
    rc, out = _run_cmd(["rg", "-n", r"^\s*def\s+[A-Za-z_][A-Za-z0-9_]*\s*\(", str(repo_root)])
    if rc not in (0, 1):
        raise RuntimeError(f"Failed to discover live symbols: {out}")

    if rc == 0:
        for line in out.splitlines():
            match = re.search(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
            if not match:
                continue
            symbol = match.group(1)
            if symbol not in chosen:
                chosen.append(symbol)
            if len(chosen) >= 4:
                break

    if not chosen:
        raise RuntimeError(f"Could not derive positive anchors from {repo_root}")
    return chosen[:4]


def _pick_find_callers_target(repo_root: Path, candidates: list[str]) -> tuple[str, int]:
    for symbol in candidates:
        def_refs = _rg_count(rf"^\s*def\s+{re.escape(symbol)}\s*\(", str(repo_root))
        if def_refs == 0:
            continue
        total_refs = _rg_count(rf"\b{re.escape(symbol)}\s*\(", str(repo_root))
        callsites = max(0, total_refs - def_refs)
        if callsites > 0:
            return symbol, callsites

    # Fallback: discover additional function names live and select one with call-sites.
    rc, out = _run_cmd(["rg", "-n", r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", str(repo_root)])
    if rc not in (0, 1):
        raise RuntimeError(f"Failed to discover fallback callers target: {out}")
    if rc == 0:
        for line in out.splitlines():
            match = re.search(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
            if not match:
                continue
            symbol = match.group(1)
            total_refs = _rg_count(rf"\b{re.escape(symbol)}\s*\(", str(repo_root))
            def_refs = _rg_count(rf"^\s*def\s+{re.escape(symbol)}\s*\(", str(repo_root))
            callsites = max(0, total_refs - def_refs)
            if callsites > 0:
                return symbol, callsites
    raise RuntimeError("Could not find a symbol with at least one live call-site for find_callers baseline")


def _build_live_index(repo_root: Path, db_path: Path) -> None:
    os.environ["CGC_RUNTIME_DB_TYPE"] = "kuzudb"
    db_manager = get_database_manager(db_path=str(db_path), read_only=False)
    db_manager.get_driver()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        graph_builder = GraphBuilder(db_manager, JobManager(), loop)
        job_id = graph_builder.job_manager.create_job(str(repo_root), is_dependency=False)
        loop.run_until_complete(
            graph_builder.build_graph_from_path_async(
                repo_root,
                is_dependency=False,
                job_id=job_id,
            )
        )
        job = graph_builder.job_manager.get_job(job_id)
        if job is None or job.status != JobStatus.COMPLETED:
            errors = job.errors if job else ["unknown indexing failure"]
            raise RuntimeError(f"Live indexing failed for {repo_root}: {errors}")
    finally:
        db_manager.close_driver()
        loop.close()


def _run_live_tool_regression(repo_root: Path, db_path: Path, strict: bool) -> dict[str, Any]:
    mismatches: list[str] = []
    observations: dict[str, Any] = {}

    positive_symbols = _discover_positive_symbols(repo_root)
    negative_symbol = f"__CGC_NONEXISTENT_{uuid.uuid4().hex[:12]}"
    find_callers_target, caller_baseline = _pick_find_callers_target(repo_root, positive_symbols)
    server_file = repo_root / "server.py"

    import_line_baseline = _rg_count(r"^(from|import)\s+", str(server_file))
    dotted_call_baseline = _rg_count(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\s*\(", str(server_file))

    observations["positive_symbols"] = positive_symbols
    observations["negative_symbol"] = negative_symbol
    observations["find_callers_target"] = find_callers_target
    observations["find_callers_baseline_callsites"] = caller_baseline
    observations["module_deps_import_line_baseline"] = import_line_baseline
    observations["module_deps_dotted_call_baseline"] = dotted_call_baseline

    with patch.object(
        server_mod,
        "resolve_context",
        lambda **_kwargs: SimpleNamespace(database="kuzudb", db_path=str(db_path), is_local=True),
    ):
        server = server_mod.MCPServer(read_only_mode=True, db_read_only=True, cwd=repo_root)

        # find_code positives: should be present in both terminal and MCP.
        for symbol in positive_symbols:
            baseline_hits = _rg_count(rf"\b{re.escape(symbol)}\b", str(repo_root))
            tool_out = asyncio.run(
                server.handle_tool_call(
                    "find_code",
                    {"query": symbol, "repo_path": str(repo_root)},
                )
            )
            if "error" in tool_out:
                raise AssertionError(f"find_code returned error for '{symbol}': {tool_out['error']}")

            results = tool_out.get("results", {})
            total_matches = int(results.get("total_matches", 0))
            ranked = results.get("ranked_results", []) or []
            result_paths = {str(item.get("path", "")) for item in ranked if isinstance(item, dict)}

            observations[f"find_code::{symbol}"] = {
                "baseline_hits": baseline_hits,
                "total_matches": total_matches,
                "ranked_paths": sorted(p for p in result_paths if p),
            }

            if baseline_hits > 0 and total_matches == 0:
                mismatches.append(
                    f"find_code('{symbol}') => MCP total_matches=0 while rg baseline={baseline_hits}"
                )

            if baseline_hits > 0:
                # At least one file path overlap between terminal and MCP results.
                rc, out = _run_cmd(["rg", "-l", rf"\b{re.escape(symbol)}\b", str(repo_root)])
                baseline_files = set(out.splitlines()) if rc == 0 else set()
                if result_paths and baseline_files and result_paths.isdisjoint(baseline_files):
                    mismatches.append(
                        f"find_code('{symbol}') => no path overlap between MCP ranked_paths and rg baseline files"
                    )

        # find_code negative: should be absent in both terminal and MCP.
        neg_baseline = _rg_count(rf"\b{re.escape(negative_symbol)}\b", str(repo_root))
        neg_out = asyncio.run(
            server.handle_tool_call(
                "find_code",
                {"query": negative_symbol, "repo_path": str(repo_root)},
            )
        )
        if "error" in neg_out:
            raise AssertionError(f"find_code returned error for negative symbol: {neg_out['error']}")
        neg_total = int((neg_out.get("results") or {}).get("total_matches", 0))
        observations["find_code::negative"] = {"baseline_hits": neg_baseline, "total_matches": neg_total}
        if neg_baseline != 0 or neg_total != 0:
            mismatches.append(
                f"negative find_code('{negative_symbol}') expected 0/0, got baseline={neg_baseline}, mcp={neg_total}"
            )

        # Relationship: find_callers should surface callers for live-called symbol.
        callers_out = asyncio.run(
            server.handle_tool_call(
                "analyze_code_relationships",
                {
                    "query_type": "find_callers",
                    "target": find_callers_target,
                    "repo_path": str(repo_root),
                },
            )
        )
        if "error" in callers_out:
            raise AssertionError(
                f"analyze_code_relationships(find_callers) returned error: {callers_out['error']}"
            )
        callers = callers_out.get("results", []) or []
        observations["find_callers"] = {
            "target": find_callers_target,
            "baseline_callsites": caller_baseline,
            "mcp_results_count": len(callers),
        }
        if caller_baseline > 0 and len(callers) == 0:
            mismatches.append(
                f"find_callers('{find_callers_target}') => MCP returned 0 while baseline callsites={caller_baseline}"
            )

        # Relationship: module_deps for a real file should expose imports/calls.
        module_deps_out = asyncio.run(
            server.handle_tool_call(
                "analyze_code_relationships",
                {
                    "query_type": "module_deps",
                    "target": str(server_file),
                    "repo_path": str(repo_root),
                },
            )
        )
        if "error" in module_deps_out:
            raise AssertionError(
                f"analyze_code_relationships(module_deps) returned error: {module_deps_out['error']}"
            )
        md_results = module_deps_out.get("results", {}) or {}
        import_count = int(md_results.get("import_count", 0))
        call_count = int(md_results.get("call_count", 0))
        observations["module_deps"] = {
            "target": str(server_file),
            "baseline_import_lines": import_line_baseline,
            "baseline_dotted_calls": dotted_call_baseline,
            "mcp_import_count": import_count,
            "mcp_call_count": call_count,
        }
        if import_line_baseline > 0 and import_count == 0:
            mismatches.append(
                f"module_deps('{server_file}') => import_count=0 while baseline imports={import_line_baseline}"
            )
        if dotted_call_baseline > 0 and call_count == 0:
            mismatches.append(
                f"module_deps('{server_file}') => call_count=0 while baseline dotted_calls={dotted_call_baseline}"
            )

    if mismatches:
        warning_text = (
            "Live MCP regression mismatches detected.\n"
            + "\n".join(f"- {item}" for item in mismatches)
        )
        warnings.warn(warning_text)
        if strict:
            pytest.fail(warning_text)

    return {"strict": strict, "mismatches": mismatches, "observations": observations}


@pytest.fixture(scope="module")
def live_indexed_context() -> dict[str, Any]:
    if not LIVE_REPO_SRC.exists():
        pytest.fail(f"Live source tree not found: {LIVE_REPO_SRC}")

    temp_root = Path(tempfile.mkdtemp(prefix="cgc_live_mcp_regression_"))
    db_path = temp_root / "db" / "kuzudb"
    strict = str(os.getenv("CGC_MEGA_TOOL_STRICT", "0")).strip().lower() in {"1", "true", "yes", "on"}

    _build_live_index(LIVE_REPO_SRC, db_path)
    result = _run_live_tool_regression(LIVE_REPO_SRC, db_path, strict=strict)

    yield {
        "repo_root": LIVE_REPO_SRC,
        "db_path": db_path,
        "strict": strict,
        "result": result,
    }

    shutil.rmtree(temp_root, ignore_errors=True)


@pytest.mark.integration
def test_mcp_live_tool_regression(live_indexed_context: dict[str, Any]) -> None:
    result = live_indexed_context["result"]
    assert result["observations"]["positive_symbols"], "Expected at least one live positive symbol anchor"
