from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
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


def _normalize_path(value: str) -> str:
    try:
        return str(Path(value).resolve())
    except Exception:
        return value


def _rg_lines(pattern: str, target: str) -> list[str]:
    rc, out = _run_cmd(["rg", "-n", pattern, target])
    if rc == 0:
        return [line for line in out.splitlines() if line.strip()]
    if rc == 1:
        return []

    # rg missing/unavailable: fallback to grep
    rc, out = _run_cmd(["grep", "-R", "-n", "-E", pattern, target])
    if rc == 0:
        return [line for line in out.splitlines() if line.strip()]
    if rc == 1:
        return []
    raise RuntimeError(f"Failed to run baseline search for pattern '{pattern}': {out}")


def _rg_count(pattern: str, target: str) -> int:
    return len(_rg_lines(pattern, target))


def _rg_files(pattern: str, target: str) -> set[str]:
    rc, out = _run_cmd(["rg", "-l", pattern, target])
    if rc == 0:
        return {_normalize_path(p.strip()) for p in out.splitlines() if p.strip()}
    if rc == 1:
        return set()

    rc, out = _run_cmd(["grep", "-R", "-l", "-E", pattern, target])
    if rc == 0:
        return {_normalize_path(p.strip()) for p in out.splitlines() if p.strip()}
    if rc == 1:
        return set()
    raise RuntimeError(f"Failed to run baseline file search for pattern '{pattern}': {out}")


def _count_function_defs(repo_root: Path) -> int:
    return _rg_count(r"^\s*(async\s+def|def)\s+[A-Za-z_][A-Za-z0-9_]*\s*\(", str(repo_root))


def _baseline_callsite_files(repo_root: Path, symbol: str) -> set[str]:
    lines = _rg_lines(rf"\b{re.escape(symbol)}\s*\(", str(repo_root))
    out: set[str] = set()
    def_re = re.compile(rf"^\s*(async\s+def|def)\s+{re.escape(symbol)}\s*\(")

    for line in lines:
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        file_part, _, code_part = parts
        if def_re.search(code_part):
            continue
        out.add(_normalize_path(file_part))
    return out


def _truthy_env(var_name: str) -> bool:
    return str(os.getenv(var_name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_strict_mode() -> bool:
    explicit = os.getenv("CGC_MEGA_TOOL_STRICT")
    if explicit is not None:
        return str(explicit).strip().lower() in {"1", "true", "yes", "on"}
    # Tiered policy: strict by default in CI, diagnostic otherwise.
    return _truthy_env("CI")


def _discover_positive_symbols(repo_root: Path) -> list[str]:
    chosen: list[str] = []

    for symbol in DEFAULT_POSITIVE_SYMBOLS:
        if _rg_count(rf"\b{re.escape(symbol)}\b", str(repo_root)) > 0:
            chosen.append(symbol)

    if len(chosen) >= 4:
        return chosen[:4]

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


def _add_mismatch(mismatches: list[dict[str, Any]], code: str, message: str, **details: Any) -> None:
    mismatches.append({"code": code, "message": message, "details": details})


def _format_mismatch_lines(mismatches: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in mismatches:
        details = item.get("details", {})
        detail_text = ""
        if details:
            detail_text = f" | details={json.dumps(details, sort_keys=True)}"
        lines.append(f"- [{item.get('code')}] {item.get('message')}{detail_text}")
    return "\n".join(lines)


def _write_report_file(payload: dict[str, Any]) -> str:
    report_dir_env = os.getenv("CGC_MEGA_TOOL_REPORT_DIR", "").strip()
    report_dir = Path(report_dir_env).expanduser().resolve() if report_dir_env else Path(tempfile.gettempdir())
    report_dir.mkdir(parents=True, exist_ok=True)

    filename = f"cgc_live_mcp_regression_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    report_path = report_dir / filename
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return str(report_path)


def _run_live_tool_regression(repo_root: Path, db_path: Path, strict: bool) -> dict[str, Any]:
    started_at = time.monotonic()
    mismatches: list[dict[str, Any]] = []
    observations: dict[str, Any] = {}

    repo_root_norm = _normalize_path(str(repo_root))
    positive_symbols = _discover_positive_symbols(repo_root)
    negative_symbol = f"__CGC_NONEXISTENT_{uuid.uuid4().hex[:12]}"
    find_callers_target, caller_baseline = _pick_find_callers_target(repo_root, positive_symbols)
    find_callers_baseline_files = _baseline_callsite_files(repo_root, find_callers_target)
    server_file = repo_root / "server.py"
    server_file_norm = _normalize_path(str(server_file))

    import_line_baseline = _rg_count(r"^(from|import)\s+", str(server_file))
    dotted_call_baseline = _rg_count(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\s*\(", str(server_file))
    function_def_baseline = _count_function_defs(repo_root)

    observations["positive_symbols"] = positive_symbols
    observations["negative_symbol"] = negative_symbol
    observations["find_callers_target"] = find_callers_target
    observations["find_callers_baseline_callsites"] = caller_baseline
    observations["find_callers_baseline_files"] = sorted(find_callers_baseline_files)
    observations["module_deps_import_line_baseline"] = import_line_baseline
    observations["module_deps_dotted_call_baseline"] = dotted_call_baseline
    observations["function_def_baseline"] = function_def_baseline

    with patch.object(
        server_mod,
        "resolve_context",
        lambda **_kwargs: SimpleNamespace(database="kuzudb", db_path=str(db_path), is_local=True),
    ):
        server = server_mod.MCPServer(read_only_mode=True, db_read_only=True, cwd=repo_root)

        def _tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
            payload = asyncio.run(server.handle_tool_call(tool_name, args))
            if "error" in payload:
                raise AssertionError(f"{tool_name} returned error: {payload['error']}")
            return payload

        # 1) find_code positive anchors with path-level overlap checks.
        for symbol in positive_symbols:
            baseline_hits = _rg_count(rf"\b{re.escape(symbol)}\b", str(repo_root))
            baseline_files = _rg_files(rf"\b{re.escape(symbol)}\b", str(repo_root))

            tool_out = _tool("find_code", {"query": symbol, "repo_path": str(repo_root)})
            results = tool_out.get("results", {})
            total_matches = int(results.get("total_matches", 0))
            ranked = results.get("ranked_results", []) or []

            result_paths = {
                _normalize_path(str(item.get("path", "")))
                for item in ranked
                if isinstance(item, dict) and item.get("path")
            }
            overlap = baseline_files & result_paths

            observations[f"find_code::{symbol}"] = {
                "baseline_hits": baseline_hits,
                "baseline_files": len(baseline_files),
                "total_matches": total_matches,
                "mcp_ranked_paths": len(result_paths),
                "path_overlap": len(overlap),
                "recall_ratio": (len(overlap) / len(baseline_files)) if baseline_files else 1.0,
                "precision_ratio": (len(overlap) / len(result_paths)) if result_paths else 0.0,
            }

            if baseline_hits > 0 and total_matches == 0:
                _add_mismatch(
                    mismatches,
                    "FIND_CODE_ZERO_MATCHES",
                    f"find_code('{symbol}') returned zero matches despite baseline hits",
                    baseline_hits=baseline_hits,
                    total_matches=total_matches,
                )

            if baseline_files and not result_paths:
                _add_mismatch(
                    mismatches,
                    "FIND_CODE_EMPTY_PATHS",
                    f"find_code('{symbol}') produced no ranked result paths",
                    baseline_file_count=len(baseline_files),
                )

            if baseline_files and result_paths and not overlap:
                _add_mismatch(
                    mismatches,
                    "FIND_CODE_NO_PATH_OVERLAP",
                    f"find_code('{symbol}') produced disjoint files from baseline",
                    baseline_sample=sorted(list(baseline_files))[:5],
                    mcp_sample=sorted(list(result_paths))[:5],
                )

            missing_paths = sorted(p for p in result_paths if not Path(p).exists())
            if missing_paths:
                _add_mismatch(
                    mismatches,
                    "FIND_CODE_PATH_NOT_FOUND",
                    f"find_code('{symbol}') returned non-existent paths",
                    missing_paths=missing_paths[:10],
                )

        # 2) find_code negative anchor should be absent in baseline + MCP.
        neg_baseline = _rg_count(rf"\b{re.escape(negative_symbol)}\b", str(repo_root))
        neg_out = _tool("find_code", {"query": negative_symbol, "repo_path": str(repo_root)})
        neg_total = int((neg_out.get("results") or {}).get("total_matches", 0))
        observations["find_code::negative"] = {"baseline_hits": neg_baseline, "total_matches": neg_total}
        if neg_baseline != 0 or neg_total != 0:
            _add_mismatch(
                mismatches,
                "FIND_CODE_NEGATIVE_LEAK",
                "negative anchor returned matches",
                baseline_hits=neg_baseline,
                total_matches=neg_total,
                symbol=negative_symbol,
            )

        # 3) find_callers: overlap against baseline callsite files.
        callers_out = _tool(
            "analyze_code_relationships",
            {
                "query_type": "find_callers",
                "target": find_callers_target,
                "repo_path": str(repo_root),
            },
        )
        callers = callers_out.get("results", []) or []
        caller_paths = {
            _normalize_path(str(item.get("caller_file_path", "")))
            for item in callers
            if isinstance(item, dict) and item.get("caller_file_path")
        }
        caller_overlap = caller_paths & find_callers_baseline_files

        observations["find_callers"] = {
            "target": find_callers_target,
            "baseline_callsites": caller_baseline,
            "baseline_files": len(find_callers_baseline_files),
            "mcp_results_count": len(callers),
            "mcp_files": len(caller_paths),
            "path_overlap": len(caller_overlap),
        }

        if caller_baseline > 0 and len(callers) == 0:
            _add_mismatch(
                mismatches,
                "FIND_CALLERS_ZERO",
                f"find_callers('{find_callers_target}') returned no callers despite baseline callsites",
                baseline_callsites=caller_baseline,
            )

        if find_callers_baseline_files and caller_paths and not caller_overlap:
            _add_mismatch(
                mismatches,
                "FIND_CALLERS_NO_PATH_OVERLAP",
                f"find_callers('{find_callers_target}') has no file overlap with baseline callsites",
                baseline_sample=sorted(list(find_callers_baseline_files))[:5],
                mcp_sample=sorted(list(caller_paths))[:5],
            )

        # 4) module_deps for server.py with consistency checks.
        module_deps_out = _tool(
            "analyze_code_relationships",
            {
                "query_type": "module_deps",
                "target": str(server_file),
                "repo_path": str(repo_root),
            },
        )
        md_results = module_deps_out.get("results", {}) or {}
        imports = md_results.get("imports", []) or []
        calls = md_results.get("calls", []) or []
        import_count = int(md_results.get("import_count", 0))
        call_count = int(md_results.get("call_count", 0))

        import_paths = {
            _normalize_path(str(item.get("importer_file_path", "")))
            for item in imports
            if isinstance(item, dict) and item.get("importer_file_path")
        }
        call_paths = {
            _normalize_path(str(item.get("caller_file_path", "")))
            for item in calls
            if isinstance(item, dict) and item.get("caller_file_path")
        }

        observations["module_deps"] = {
            "target": str(server_file),
            "baseline_import_lines": import_line_baseline,
            "baseline_dotted_calls": dotted_call_baseline,
            "mcp_import_count": import_count,
            "mcp_call_count": call_count,
            "imports_len": len(imports),
            "calls_len": len(calls),
            "import_paths": sorted(import_paths),
            "call_paths": sorted(call_paths),
        }

        if import_line_baseline > 0 and import_count == 0:
            _add_mismatch(
                mismatches,
                "MODULE_DEPS_IMPORT_ZERO",
                "module_deps import_count is zero despite baseline import lines",
                baseline_import_lines=import_line_baseline,
            )

        if dotted_call_baseline > 0 and call_count == 0:
            _add_mismatch(
                mismatches,
                "MODULE_DEPS_CALL_ZERO",
                "module_deps call_count is zero despite baseline dotted calls",
                baseline_dotted_calls=dotted_call_baseline,
            )

        if import_count != len(imports):
            _add_mismatch(
                mismatches,
                "MODULE_DEPS_IMPORT_COUNT_MISMATCH",
                "module_deps import_count != len(imports)",
                import_count=import_count,
                imports_len=len(imports),
            )

        if call_count != len(calls):
            _add_mismatch(
                mismatches,
                "MODULE_DEPS_CALL_COUNT_MISMATCH",
                "module_deps call_count != len(calls)",
                call_count=call_count,
                calls_len=len(calls),
            )

        if import_paths and import_paths != {server_file_norm}:
            _add_mismatch(
                mismatches,
                "MODULE_DEPS_IMPORT_PATH_SCOPE",
                "module_deps imports include files outside target module path scope",
                target=server_file_norm,
                observed=sorted(import_paths),
            )

        if call_paths and call_paths != {server_file_norm}:
            _add_mismatch(
                mismatches,
                "MODULE_DEPS_CALL_PATH_SCOPE",
                "module_deps calls include files outside target module path scope",
                target=server_file_norm,
                observed=sorted(call_paths),
            )

        # 5) list_indexed_repositories (Phase 1 expanded coverage).
        repos_out = _tool("list_indexed_repositories", {})
        repositories = repos_out.get("repositories", []) or []
        repo_paths = {
            _normalize_path(str(item.get("path", "")))
            for item in repositories
            if isinstance(item, dict) and item.get("path")
        }
        observations["list_indexed_repositories"] = {
            "repository_count": len(repositories),
            "paths_count": len(repo_paths),
            "contains_live_repo": repo_root_norm in repo_paths,
        }

        if not repositories:
            _add_mismatch(
                mismatches,
                "LIST_REPOS_EMPTY",
                "list_indexed_repositories returned no repositories",
            )

        if repo_root_norm not in repo_paths:
            _add_mismatch(
                mismatches,
                "LIST_REPOS_MISSING_LIVE_REPO",
                "list_indexed_repositories did not include the live indexed repo",
                expected_repo=repo_root_norm,
                observed_repos=sorted(list(repo_paths))[:10],
            )

        # 6) get_repository_stats (repo-specific + global).
        repo_stats_out = _tool("get_repository_stats", {"repo_path": str(repo_root)})
        repo_stats = repo_stats_out.get("stats", {}) or {}
        observations["get_repository_stats::repo"] = repo_stats

        for key in ["files", "functions", "classes", "modules"]:
            value = repo_stats.get(key)
            if not isinstance(value, int) or value < 0:
                _add_mismatch(
                    mismatches,
                    "REPO_STATS_INVALID_FIELD",
                    f"get_repository_stats(repo) invalid field '{key}'",
                    value=value,
                )

        if int(repo_stats.get("files", 0) or 0) <= 0:
            _add_mismatch(
                mismatches,
                "REPO_STATS_ZERO_FILES",
                "get_repository_stats(repo) reported zero files for indexed live repo",
                repo_stats=repo_stats,
            )

        global_stats_out = _tool("get_repository_stats", {})
        global_stats = global_stats_out.get("stats", {}) or {}
        observations["get_repository_stats::global"] = global_stats

        global_repo_count = int(global_stats.get("repositories", 0) or 0)
        if global_repo_count <= 0:
            _add_mismatch(
                mismatches,
                "GLOBAL_STATS_ZERO_REPOS",
                "get_repository_stats(global) reported zero repositories",
                global_stats=global_stats,
            )

        repo_files = int(repo_stats.get("files", 0) or 0)
        global_files = int(global_stats.get("files", 0) or 0)
        if repo_files > 0 and global_files > 0 and global_files < repo_files:
            _add_mismatch(
                mismatches,
                "GLOBAL_STATS_LESS_THAN_REPO",
                "global file count is less than repo-specific file count",
                repo_files=repo_files,
                global_files=global_files,
            )

        # 7) find_most_complex_functions.
        complex_limit = 10
        complex_out = _tool(
            "find_most_complex_functions",
            {"limit": complex_limit, "repo_path": str(repo_root)},
        )
        complex_results = complex_out.get("results", []) or []
        complexities: list[int] = []
        bad_complex_rows: list[dict[str, Any]] = []
        for row in complex_results:
            if not isinstance(row, dict):
                bad_complex_rows.append({"row": row})
                continue
            value = row.get("complexity")
            if not isinstance(value, int):
                bad_complex_rows.append({"row": row})
                continue
            complexities.append(value)

        observations["find_most_complex_functions"] = {
            "limit": complex_limit,
            "result_count": len(complex_results),
            "complexity_values": complexities,
        }

        if len(complex_results) > complex_limit:
            _add_mismatch(
                mismatches,
                "MOST_COMPLEX_EXCEEDS_LIMIT",
                "find_most_complex_functions returned more rows than limit",
                limit=complex_limit,
                returned=len(complex_results),
            )

        if bad_complex_rows:
            _add_mismatch(
                mismatches,
                "MOST_COMPLEX_BAD_ROW_SHAPE",
                "find_most_complex_functions returned rows with invalid shape",
                bad_rows=bad_complex_rows[:5],
            )

        if complexities and complexities != sorted(complexities, reverse=True):
            _add_mismatch(
                mismatches,
                "MOST_COMPLEX_NOT_SORTED",
                "find_most_complex_functions results are not sorted by descending complexity",
                values=complexities,
            )

        if function_def_baseline > 0 and len(complex_results) == 0:
            _add_mismatch(
                mismatches,
                "MOST_COMPLEX_EMPTY",
                "find_most_complex_functions returned no rows despite detected function definitions",
                function_def_baseline=function_def_baseline,
            )

        # 8) find_dead_code.
        dead_out = _tool("find_dead_code", {"repo_path": str(repo_root)})
        dead_results = dead_out.get("results", {}) or {}
        dead_candidates = dead_results.get("potentially_unused_functions", []) or []
        bad_dead_rows: list[dict[str, Any]] = []

        for row in dead_candidates:
            if not isinstance(row, dict):
                bad_dead_rows.append({"row": row})
                continue
            if not row.get("function_name"):
                bad_dead_rows.append({"row": row, "reason": "missing function_name"})
                continue
            path = str(row.get("path", "")).strip()
            if not path:
                bad_dead_rows.append({"row": row, "reason": "missing path"})
                continue
            path_norm = _normalize_path(path)
            if not path_norm.startswith(repo_root_norm):
                bad_dead_rows.append({"row": row, "reason": "path outside repo scope"})

        observations["find_dead_code"] = {
            "result_count": len(dead_candidates),
            "has_note": bool(dead_results.get("note")),
        }

        if bad_dead_rows:
            _add_mismatch(
                mismatches,
                "DEAD_CODE_BAD_ROW_SHAPE",
                "find_dead_code returned invalid candidate rows",
                bad_rows=bad_dead_rows[:5],
            )

    mismatch_codes: dict[str, int] = {}
    for item in mismatches:
        code = str(item.get("code", "UNKNOWN"))
        mismatch_codes[code] = mismatch_codes.get(code, 0) + 1

    observations["summary"] = {
        "strict": strict,
        "mismatch_count": len(mismatches),
        "mismatch_codes": mismatch_codes,
        "duration_sec": round(time.monotonic() - started_at, 3),
    }

    result = {"strict": strict, "mismatches": mismatches, "observations": observations}
    report_path = _write_report_file(result)
    observations["summary"]["report_path"] = report_path

    if mismatches:
        warning_text = (
            "Live MCP regression mismatches detected.\n"
            + _format_mismatch_lines(mismatches)
            + f"\nReport file: {report_path}"
        )
        warnings.warn(warning_text)
        if strict:
            pytest.fail(warning_text)

    return result


@pytest.fixture(scope="module")
def live_indexed_context() -> dict[str, Any]:
    if not LIVE_REPO_SRC.exists():
        pytest.fail(f"Live source tree not found: {LIVE_REPO_SRC}")

    temp_root = Path(tempfile.mkdtemp(prefix="cgc_live_mcp_regression_"))
    db_path = temp_root / "db" / "kuzudb"
    strict = _resolve_strict_mode()

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
    observations = result["observations"]
    assert observations["positive_symbols"], "Expected at least one live positive symbol anchor"
    assert "summary" in observations, "Expected regression summary payload"
    assert observations["summary"]["mismatch_count"] == len(result["mismatches"])
    assert observations["summary"].get("report_path"), "Expected report_path in summary"
