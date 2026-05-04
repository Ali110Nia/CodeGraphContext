"""Heuristic resolution of function calls into CALLS edge payloads (no DB I/O)."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ....cli.config_manager import get_config_value
from ....utils.debug_log import info_logger

# Confidence score for each resolution tier.
# Higher = more certain the edge points to the correct target.
_TIER_CONFIDENCE: Dict[int, float] = {
    1: 1.00,  # explicit this/self/super receiver — definitionally same-class
    2: 0.95,  # local function or class defined in the same file
    3: 0.88,  # inferred receiver type + FQN import key (Phase 1 adds FQN entries)
    4: 0.72,  # inferred receiver type + short-name (possible first-match bias)
    5: 0.90,  # unique short name — only one file in the graph defines it
    6: 0.85,  # FQN key in imports_map via qualified import declaration
    7: 0.70,  # FQN matched as path-substring across multiple candidates
    8: 0.25,  # alphabetical-first of multiple candidates (wrong most of the time)
    9: 0.08,  # same-file fallback for obj.method() — definitionally wrong
}


def resolve_function_call(
    call: Dict[str, Any],
    caller_file_path: str,
    local_names: set,
    local_imports: dict,
    imports_map: dict,
    skip_external: bool,
) -> Optional[Dict[str, Any]]:
    """Resolve a single function call to its target. Returns call params dict or None if skipped."""
    called_name = call["name"]
    if called_name in __builtins__:
        return None

    resolved_called_name = called_name
    resolved_path = None
    resolution_tier = 9  # default: same-file fallback
    full_call = call.get("full_name", called_name)
    base_obj = full_call.split(".")[0] if "." in full_call else None

    is_chained_call = full_call.count(".") > 1 if "." in full_call else False

    if is_chained_call and base_obj in ("self", "this", "super", "super()", "cls", "@"):
        lookup_name = called_name
    else:
        lookup_name = base_obj if base_obj else called_name

    # ── Tier 1: explicit self/this/super — same-class, always correct ──────────
    if base_obj in ("self", "this", "super", "super()", "cls", "@") and not is_chained_call:
        resolved_path = caller_file_path
        resolution_tier = 1

    # ── Tier 2: call target defined locally in the same file ───────────────────
    elif lookup_name in local_names:
        resolved_path = caller_file_path
        resolution_tier = 2

    # ── Tier 3/4: receiver type inferred from variable declaration ─────────────
    elif call.get("inferred_obj_type"):
        obj_type = call["inferred_obj_type"]
        # Tier 3: FQN lookup — only when local import gives us the exact package.
        # Phase 1 adds FQN entries to imports_map so `imports_map[fqn]` has 1 path.
        if obj_type in local_imports:
            fqn = local_imports[obj_type]
            fqn_paths = imports_map.get(fqn, [])
            if len(fqn_paths) == 1:
                resolved_path = fqn_paths[0]
                resolution_tier = 3
        # Tier 4: short-name lookup (legacy — may be first-match biased)
        if not resolved_path:
            possible_paths = imports_map.get(obj_type, [])
            if possible_paths:
                resolved_path = possible_paths[0]
                resolution_tier = 4

    # ── Tier 5/6/7: lookup by call-site name (no inferred type) ───────────────
    if not resolved_path:
        possible_paths = imports_map.get(lookup_name, [])
        if not possible_paths and lookup_name in local_imports:
            imported_name = local_imports[lookup_name]
            alias_paths = imports_map.get(imported_name, [])
            if alias_paths:
                possible_paths = alias_paths
                lookup_name = imported_name
                if called_name == base_obj or called_name == call["name"]:
                    resolved_called_name = imported_name
        if len(possible_paths) == 1:
            # Tier 5: globally unique short name — high confidence
            resolved_path = possible_paths[0]
            resolution_tier = 5
        elif len(possible_paths) > 1 and lookup_name in local_imports:
            full_import_name = local_imports[lookup_name]
            # Tier 6: FQN key in imports_map (added by Phase 1 pre_scan changes)
            fqn_paths = imports_map.get(full_import_name, [])
            if fqn_paths and len(fqn_paths) == 1:
                resolved_path = fqn_paths[0]
                resolution_tier = 6
            # Tier 7: FQN as path-substring across candidates
            if not resolved_path:
                fqn_as_path = full_import_name.replace(".", "/")
                for p in possible_paths:
                    if fqn_as_path in p:
                        resolved_path = p
                        resolution_tier = 7
                        break

    # ── Tier 8/9: last-resort fallbacks ────────────────────────────────────────
    if not resolved_path:
        if called_name in local_names:
            # Re-check with the bare called_name (covers chained-call edge cases)
            resolved_path = caller_file_path
            resolution_tier = 2
        elif resolved_called_name in imports_map and imports_map[resolved_called_name]:
            candidates = imports_map[resolved_called_name]
            # Try to match any candidate via a local import path hint
            for p in candidates:
                for imp_fqn in local_imports.values():
                    if imp_fqn.replace(".", "/") in p:
                        resolved_path = p
                        resolution_tier = 7
                        break
                if resolved_path:
                    break
            # Tier 8: alphabetical first of multiple candidates
            if not resolved_path:
                resolved_path = candidates[0]
                resolution_tier = 8
        else:
            # Tier 9: same-file fallback — wrong for any obj.method() call
            resolved_path = caller_file_path
            resolution_tier = 9

    # Determine whether this resolution is "external" (unresolvable target).
    # Tier 9 for non-self/super calls means we gave up — treat as external.
    is_unresolved_external = (
        resolution_tier == 9
        and base_obj not in ("self", "this", "super", "super()", "cls", "@")
    )

    if skip_external and is_unresolved_external:
        return None

    confidence = _TIER_CONFIDENCE.get(resolution_tier, 0.1)

    caller_context = call.get("context")
    if caller_context and len(caller_context) == 3 and caller_context[0] is not None:
        caller_name, _, caller_line_number = caller_context
        return {
            "type": "function",
            "caller_name": caller_name,
            "caller_file_path": caller_file_path,
            "caller_line_number": caller_line_number,
            "called_name": resolved_called_name,
            "called_file_path": resolved_path,
            "line_number": call["line_number"],
            "args": call.get("args", []),
            "full_call_name": call.get("full_name", called_name),
            "confidence": confidence,
            "resolution_tier": resolution_tier,
        }
    return {
        "type": "file",
        "caller_file_path": caller_file_path,
        "called_name": resolved_called_name,
        "called_file_path": resolved_path,
        "line_number": call["line_number"],
        "args": call.get("args", []),
        "full_call_name": call.get("full_name", called_name),
        "confidence": confidence,
        "resolution_tier": resolution_tier,
    }


def build_function_call_groups(
    all_file_data: List[Dict[str, Any]],
    imports_map: dict,
    file_class_lookup: Optional[Dict[str, set]] = None,
) -> Tuple[
    List[Dict],
    List[Dict],
    List[Dict],
    List[Dict],
    List[Dict],
    List[Dict],
]:
    """Phase 1 of CALLS linking: resolve and bucket by (caller_label, called_label) pair."""
    skip_external = (get_config_value("SKIP_EXTERNAL_RESOLUTION") or "false").lower() == "true"

    if file_class_lookup is None:
        file_class_lookup = {}
    for fd in all_file_data:
        fp = str(Path(fd["path"]).resolve())
        file_class_lookup[fp] = {c["name"] for c in fd.get("classes", [])}

    info_logger(f"[CALLS] Resolving function calls across {len(all_file_data)} files...")
    fn_to_fn: List[Dict] = []
    fn_to_cls: List[Dict] = []
    cls_to_fn: List[Dict] = []
    cls_to_cls: List[Dict] = []
    file_to_fn: List[Dict] = []
    file_to_cls: List[Dict] = []

    # Pre-build per-language-extension filtered imports_map views.
    # When a caller is Java, we only want to resolve against Java files —
    # this prevents false-positive CALLS edges from names that coincidentally
    # exist in another language's file (e.g. Java `add()` -> JS `add`).
    _lang_imports_cache: Dict[str, dict] = {}

    def _get_lang_imports(caller_lang: str) -> dict:
        if caller_lang not in _lang_imports_cache:
            # Map language name to typical file extensions
            _LANG_EXTS: Dict[str, set] = {
                "java":       {".java"},
                "python":     {".py", ".ipynb"},
                "javascript": {".js", ".jsx", ".mjs", ".cjs"},
                "typescript": {".ts", ".tsx"},
                "go":         {".go"},
                "rust":       {".rs"},
                "cpp":        {".cpp", ".h", ".hpp", ".hh"},
                "c":          {".c"},
                "c_sharp":    {".cs"},
                "kotlin":     {".kt"},
                "scala":      {".scala", ".sc"},
                "ruby":       {".rb"},
                "swift":      {".swift"},
                "php":        {".php"},
                "dart":       {".dart"},
                "perl":       {".pl", ".pm"},
                "lua":        {".lua"},
                "haskell":    {".hs"},
                "elixir":     {".ex", ".exs"},
            }
            exts = _LANG_EXTS.get(caller_lang)
            if not exts:
                # Unknown language — use full imports_map unchanged
                _lang_imports_cache[caller_lang] = imports_map
            else:
                filtered: dict = {}
                for name, paths in imports_map.items():
                    same_lang = [p for p in paths if Path(p).suffix in exts]
                    if same_lang:
                        filtered[name] = same_lang
                    elif paths:
                        # Keep non-file entries (e.g. package names with no extension)
                        if not any(Path(p).suffix for p in paths):
                            filtered[name] = paths
                _lang_imports_cache[caller_lang] = filtered
        return _lang_imports_cache[caller_lang]

    for idx, file_data in enumerate(all_file_data):
        caller_file_path = str(Path(file_data["path"]).resolve())
        func_names = {f["name"] for f in file_data.get("functions", [])}
        class_names = {c["name"] for c in file_data.get("classes", [])}
        local_names = func_names | class_names
        local_imports = {
            imp.get("alias") or imp["name"].split(".")[-1]: imp["name"]
            for imp in file_data.get("imports", [])
        }

        caller_lang = file_data.get("lang", "")
        effective_imports_map = _get_lang_imports(caller_lang) if caller_lang else imports_map

        for call in file_data.get("function_calls", []):
            resolved = resolve_function_call(
                call, caller_file_path, local_names, local_imports, effective_imports_map, skip_external
            )
            if not resolved:
                continue

            called_path = resolved.get("called_file_path", "")
            called_name = resolved["called_name"]
            called_is_class = called_name in file_class_lookup.get(called_path, set())

            if resolved["type"] == "file":
                if called_is_class:
                    file_to_cls.append(resolved)
                else:
                    file_to_fn.append(resolved)
            else:
                caller_name = resolved["caller_name"]
                caller_is_class = caller_name in class_names
                if caller_is_class:
                    (cls_to_cls if called_is_class else cls_to_fn).append(resolved)
                else:
                    (fn_to_cls if called_is_class else fn_to_fn).append(resolved)

        if (idx + 1) % 1000 == 0:
            total = len(fn_to_fn) + len(fn_to_cls) + len(cls_to_fn) + len(cls_to_cls)
            file_total = len(file_to_fn) + len(file_to_cls)
            info_logger(
                f"[CALLS] Resolved {idx + 1}/{len(all_file_data)} files... "
                f"({total} fn/cls calls, {file_total} file calls)"
            )

    total_all = (
        len(fn_to_fn)
        + len(fn_to_cls)
        + len(cls_to_fn)
        + len(cls_to_cls)
        + len(file_to_fn)
        + len(file_to_cls)
    )
    info_logger(
        f"[CALLS] Resolution complete: fn→fn={len(fn_to_fn)}, fn→cls={len(fn_to_cls)}, "
        f"cls→fn={len(cls_to_fn)}, cls→cls={len(cls_to_cls)}, "
        f"file→fn={len(file_to_fn)}, file→cls={len(file_to_cls)}. Total={total_all}"
    )
    return fn_to_fn, fn_to_cls, cls_to_fn, cls_to_cls, file_to_fn, file_to_cls
