"""Enumerate files to index with ignore rules."""

import os
from pathlib import Path
from typing import List, Optional, Set, Tuple

from ...core.cgcignore import build_ignore_spec
from ...utils.debug_log import debug_log, warning_logger
from .constants import DEFAULT_IGNORE_PATTERNS


def discover_files_to_index(
    path: Path,
    cgcignore_path: Optional[str] = None,
    supported_extensions: Optional[Set[str]] = None,
    include_unsupported: bool = True,
) -> Tuple[List[Path], Path]:
    """
    Returns (files, ignore_root). *ignore_root* is used for .cgcignore relative matching.
    """
    ignore_root = path.resolve() if path.is_dir() else path.resolve().parent

    spec = None
    try:
        spec, resolved_cgcignore = build_ignore_spec(
            ignore_root=ignore_root,
            default_patterns=DEFAULT_IGNORE_PATTERNS,
            explicit_path=cgcignore_path,
        )
        if resolved_cgcignore:
            debug_log(f"Using .cgcignore at {resolved_cgcignore} (filtering relative to {ignore_root})")
    except OSError as e:
        warning_logger(f"Could not load/create .cgcignore: {e}")

    from ...cli.config_manager import get_config_value

    ignore_dirs_str = get_config_value("IGNORE_DIRS") or ""
    ignore_dirs = {d.strip().lower() for d in ignore_dirs_str.split(",") if d.strip()}

    prunable_dirs = {
        pattern[:-1].lower()
        for pattern in DEFAULT_IGNORE_PATTERNS
        if pattern.endswith("/") and pattern[:-1] and not any(ch in pattern[:-1] for ch in "*?[]")
    }
    # Internal CGC state should never be traversed for source indexing.
    prunable_dirs.add(".codegraphcontext")
    prunable_dirs.update(ignore_dirs)

    files: List[Path] = []
    normalized_supported: Optional[Set[str]] = None
    if supported_extensions:
        normalized_supported = {ext.lower() for ext in supported_extensions}

    if path.is_dir():
        for root, dirs, filenames in os.walk(path, topdown=True):
            root_path = Path(root)
            kept_dirs = []
            for d in dirs:
                if d.lower() in prunable_dirs:
                    continue
                if spec:
                    try:
                        rel_dir = (root_path / d).relative_to(ignore_root).as_posix() + "/"
                        if spec.match_file(rel_dir):
                            debug_log(f"Ignored directory based on .cgcignore: {rel_dir}")
                            continue
                    except ValueError:
                        pass
                kept_dirs.append(d)
            dirs[:] = kept_dirs

            for filename in filenames:
                f = root_path / filename
                if normalized_supported is not None and not include_unsupported:
                    if f.suffix.lower() not in normalized_supported:
                        continue
                if spec:
                    try:
                        rel_path = f.relative_to(ignore_root).as_posix()
                        if spec.match_file(rel_path):
                            debug_log(f"Ignored file based on .cgcignore: {rel_path}")
                            continue
                    except ValueError:
                        pass
                files.append(f)
    else:
        if path.is_file():
            if normalized_supported is None or include_unsupported or path.suffix.lower() in normalized_supported:
                if spec:
                    try:
                        rel_path = path.relative_to(ignore_root).as_posix()
                        if spec.match_file(rel_path):
                            debug_log(f"Ignored file based on .cgcignore: {rel_path}")
                            return [], ignore_root
                    except ValueError:
                        pass
                files = [path]

    return files, ignore_root
