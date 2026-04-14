"""All graph DB writes for indexing (single persistence entry point)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ....utils.debug_log import info_logger, warning_logger
from ..sanitize import sanitize_props


class GraphWriter:
    """Persists repository/file/symbol nodes and relationships via the Neo4j-like driver API."""

    def __init__(self, driver: Any, db_manager: Any = None):
        self.driver = driver
        self.db_manager = db_manager
        self._kuzu_table_props_cache: Dict[str, set[str]] = {}

    def _backend_type(self) -> str:
        return getattr(self.db_manager, "get_backend_type", lambda: "neo4j")()

    def _get_kuzu_table_properties(self, label: str) -> set[str]:
        if label in self._kuzu_table_props_cache:
            return self._kuzu_table_props_cache[label]

        props: set[str] = set()
        with self.driver.session() as session:
            try:
                rows = session.run(f"CALL table_info('{label}') RETURN *").data()
                for row in rows:
                    name = row.get("name")
                    if isinstance(name, str) and name:
                        props.add(name)
            except Exception as e:
                warning_logger(f"Could not read Kuzu table_info for {label}: {e}")

        self._kuzu_table_props_cache[label] = props
        return props

    def _run_node_batch_upsert(
        self,
        session: Any,
        *,
        label: str,
        batch: List[Dict[str, Any]],
        file_path_str: str,
    ) -> None:
        if not batch:
            return

        if self._backend_type() != "kuzudb":
            session.run(
                f"""
                UNWIND $batch AS row
                MERGE (n:{label} {{name: row.name, path: $file_path, line_number: row.line_number}})
                SET n += row
                """,
                batch=batch,
                file_path=file_path_str,
            )
            return

        table_props = self._get_kuzu_table_properties(label)
        banned_for_kuzu = {"source", "docstring"}
        for row in batch:
            for banned in banned_for_kuzu:
                row.pop(banned, None)

        key_fields = {"name", "path", "line_number", "uid"}
        row_keys = set(batch[0].keys())
        settable = sorted((row_keys - key_fields) & table_props)

        if settable:
            set_clause = ",\n                    ".join(f"n.{k} = row.{k}" for k in settable)
            query = f"""
                UNWIND $batch AS row
                MERGE (n:{label} {{name: row.name, path: $file_path, line_number: row.line_number}})
                SET {set_clause}
            """
        else:
            query = f"""
                UNWIND $batch AS row
                MERGE (n:{label} {{name: row.name, path: $file_path, line_number: row.line_number}})
            """

        session.run(query, batch=batch, file_path=file_path_str)

    def add_repository_to_graph(self, repo_path: Path, is_dependency: bool = False) -> None:
        repo_name = repo_path.name
        repo_path_str = str(repo_path.resolve())
        with self.driver.session() as session:
            session.run(
                """
                MERGE (r:Repository {path: $path})
                SET r.name = $name, r.is_dependency = $is_dependency
                """,
                path=repo_path_str,
                name=repo_name,
                is_dependency=is_dependency,
            )

    @staticmethod
    def _python_importer_module_context(file_path_str: str, repo_path_str: str) -> Tuple[str, bool]:
        """Return (importer_module_path, is_package_init_file) for a Python file."""
        file_path = Path(file_path_str)
        repo_path = Path(repo_path_str)
        try:
            rel = file_path.relative_to(repo_path)
        except ValueError:
            rel = Path(file_path.name)
        rel_no_suffix = rel.with_suffix("")
        parts = list(rel_no_suffix.parts)
        is_init = bool(parts and parts[-1] == "__init__")
        if is_init:
            parts = parts[:-1]
        return ".".join(parts), is_init

    @staticmethod
    def _resolve_python_module_ref(
        module_ref: str,
        importer_module: str,
        importer_is_init: bool,
    ) -> str:
        """Resolve relative Python import refs (e.g. '.x', '..core.y') to canonical module path."""
        raw = (module_ref or "").strip()
        if not raw:
            return raw
        dot_count = len(raw) - len(raw.lstrip("."))
        if dot_count == 0:
            return raw

        tail = raw.lstrip(".")
        importer_parts = [p for p in importer_module.split(".") if p]
        package_parts = importer_parts if importer_is_init else importer_parts[:-1]
        levels_up = max(0, dot_count - 1)
        if levels_up > len(package_parts):
            return tail
        base = package_parts[: len(package_parts) - levels_up]
        if tail:
            base.extend([p for p in tail.split(".") if p])
        return ".".join(base)

    def _normalize_import_rows(
        self,
        imports: List[Dict[str, Any]],
        *,
        lang: Optional[str],
        file_path_str: str,
        repo_path_str: str,
    ) -> List[Dict[str, Any]]:
        """Normalize import payloads to canonical module-path + symbol semantics."""
        normalized: List[Dict[str, Any]] = []
        importer_module = ""
        importer_is_init = False
        if lang == "python":
            importer_module, importer_is_init = self._python_importer_module_context(
                file_path_str=file_path_str,
                repo_path_str=repo_path_str,
            )

        for imp in imports:
            row = dict(imp)
            name = str(row.get("name", "")).strip()
            alias = row.get("alias")
            full_import_name = str(row.get("full_import_name", "")).strip() or name

            imported_symbol = name
            module_ref = full_import_name
            if name and full_import_name and full_import_name != name and full_import_name.endswith(f".{name}"):
                module_ref = full_import_name[: -(len(name) + 1)]

            if lang == "python":
                canonical_module = self._resolve_python_module_ref(
                    module_ref=module_ref,
                    importer_module=importer_module,
                    importer_is_init=importer_is_init,
                )
            else:
                canonical_module = module_ref

            canonical_module = canonical_module.strip()
            if not canonical_module:
                canonical_module = name

            canonical_full_import_name = canonical_module
            if imported_symbol and canonical_module and imported_symbol != canonical_module:
                if full_import_name.endswith(f".{name}") or "." not in name:
                    canonical_full_import_name = f"{canonical_module}.{imported_symbol}"

            row["module_name"] = canonical_module
            row["imported_name"] = imported_symbol
            row["full_import_name"] = canonical_full_import_name
            row["alias"] = alias
            normalized.append(row)

        return normalized

    def add_file_to_graph(
        self,
        file_data: Dict[str, Any],
        repo_name: str,
        imports_map: dict,
        repo_path_str: Optional[str] = None,
    ) -> None:
        file_path_str = str(Path(file_data["path"]).resolve())
        file_name = Path(file_path_str).name
        is_dependency = file_data.get("is_dependency", False)
        lang = file_data.get("lang")

        with self.driver.session() as session:
            if repo_path_str:
                resolved_repo_str = repo_path_str
            else:
                repo_result = session.run(
                    "MATCH (r:Repository {path: $repo_path}) RETURN r.path as path",
                    repo_path=str(Path(file_data["repo_path"]).resolve()),
                ).single()
                resolved_repo_str = (
                    repo_result["path"] if repo_result else str(Path(file_data["repo_path"]).resolve())
                )
                if not repo_result:
                    warning_logger(
                        f"Repository node not found for {file_data['repo_path']} during indexing of {file_name}."
                    )

            try:
                relative_path = str(Path(file_path_str).relative_to(Path(resolved_repo_str)))
            except ValueError:
                relative_path = file_name

            session.run(
                """
                MERGE (f:File {path: $path})
                SET f.name = $name, f.relative_path = $relative_path, f.is_dependency = $is_dependency
            """,
                path=file_path_str,
                name=file_name,
                relative_path=relative_path,
                is_dependency=is_dependency,
            )

            file_path_obj = Path(file_path_str)
            repo_path_obj = Path(resolved_repo_str)
            relative_path_to_file = file_path_obj.relative_to(repo_path_obj)
            parent_path = resolved_repo_str
            parent_label = "Repository"
            for part in relative_path_to_file.parts[:-1]:
                current_path_str = str(Path(parent_path) / part)
                session.run(
                    f"""
                    MATCH (p:{parent_label} {{path: $parent_path}})
                    MERGE (d:Directory {{path: $current_path}})
                    SET d.name = $part
                    MERGE (p)-[:CONTAINS]->(d)
                """,
                    parent_path=parent_path,
                    current_path=current_path_str,
                    part=part,
                )
                parent_path = current_path_str
                parent_label = "Directory"
            session.run(
                f"""
                MATCH (p:{parent_label} {{path: $parent_path}})
                MATCH (f:File {{path: $path}})
                MERGE (p)-[:CONTAINS]->(f)
            """,
                parent_path=parent_path,
                path=file_path_str,
            )

            item_mappings = [
                (file_data.get("functions", []), "Function"),
                (file_data.get("classes", []), "Class"),
                (file_data.get("traits", []), "Trait"),
                (file_data.get("variables", []), "Variable"),
                (file_data.get("interfaces", []), "Interface"),
                (file_data.get("macros", []), "Macro"),
                (file_data.get("structs", []), "Struct"),
                (file_data.get("enums", []), "Enum"),
                (file_data.get("unions", []), "Union"),
                (file_data.get("records", []), "Record"),
                (file_data.get("properties", []), "Property"),
            ]
            params_batch: List[Dict[str, Any]] = []
            class_fn_batch: List[Dict[str, Any]] = []
            nested_fn_batch: List[Dict[str, Any]] = []

            for item_list, label in item_mappings:
                if not item_list:
                    continue
                batch: List[Dict[str, Any]] = []
                for item in item_list:
                    row = dict(item)
                    if label == "Function" and "cyclomatic_complexity" not in row:
                        row["cyclomatic_complexity"] = 1
                    batch.append(sanitize_props(row))
                    if label == "Function":
                        for arg_name in item.get("args", []):
                            params_batch.append(
                                {
                                    "func_name": item["name"],
                                    "line_number": item["line_number"],
                                    "arg_name": arg_name,
                                }
                            )
                        if item.get("class_context"):
                            class_fn_batch.append(
                                {
                                    "class_name": item["class_context"],
                                    "func_name": item["name"],
                                    "func_line": item["line_number"],
                                }
                            )
                        if item.get("context_type") == "function_definition":
                            nested_fn_batch.append(
                                {
                                    "outer": item["context"],
                                    "inner_name": item["name"],
                                    "inner_line": item["line_number"],
                                }
                            )

                if batch:
                    import json as _json

                    all_keys = set()
                    for b in batch:
                        all_keys.update(b.keys())

                    for k in all_keys:
                        counts: Dict[str, int] = {}
                        for b in batch:
                            v = b.get(k)
                            if v is not None:
                                tname = type(v).__name__
                                counts[tname] = counts.get(tname, 0) + 1

                        dominant = max(counts, key=counts.get) if counts else "str"

                        for b in batch:
                            v = b.get(k)
                            if dominant == "list":
                                if isinstance(v, list):
                                    b[k] = [str(x) for x in v] if v else [""]
                                elif isinstance(v, str) and v:
                                    try:
                                        p = _json.loads(v)
                                        b[k] = [str(x) for x in p] if isinstance(p, list) and p else [""]
                                    except Exception:
                                        b[k] = [v]
                                else:
                                    b[k] = [""]
                            elif dominant == "int":
                                if v is None or v == "":
                                    b[k] = 0
                                elif not isinstance(v, int):
                                    try:
                                        b[k] = int(v)
                                    except Exception:
                                        b[k] = 0
                            elif dominant == "bool":
                                b[k] = bool(v) if v is not None else False
                            else:
                                if v is None:
                                    b[k] = ""
                                elif isinstance(v, list):
                                    b[k] = _json.dumps(v)
                                elif not isinstance(v, str):
                                    b[k] = str(v)

                    key_order = sorted(all_keys)
                    batch[:] = [{k: b[k] for k in key_order} for b in batch]

                self._run_node_batch_upsert(
                    session,
                    label=label,
                    batch=batch,
                    file_path_str=file_path_str,
                )
                session.run(
                    f"""
                    UNWIND $batch AS row
                    MATCH (f:File {{path: $file_path}})
                    MATCH (n:{label} {{name: row.name, path: $file_path, line_number: row.line_number}})
                    MERGE (f)-[:CONTAINS]->(n)
                """,
                    batch=batch,
                    file_path=file_path_str,
                )

            if params_batch:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (fn:Function {name: row.func_name, path: $file_path, line_number: row.line_number})
                    MERGE (p:Parameter {name: row.arg_name, path: $file_path, function_line_number: row.line_number})
                    MERGE (fn)-[:HAS_PARAMETER]->(p)
                """,
                    batch=params_batch,
                    file_path=file_path_str,
                )

            if class_fn_batch:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (c:Class {name: row.class_name, path: $file_path})
                    MATCH (fn:Function {name: row.func_name, path: $file_path, line_number: row.func_line})
                    MERGE (c)-[:CONTAINS]->(fn)
                """,
                    batch=class_fn_batch,
                    file_path=file_path_str,
                )

            if nested_fn_batch:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (outer:Function {name: row.outer, path: $file_path})
                    MATCH (inner:Function {name: row.inner_name, path: $file_path, line_number: row.inner_line})
                    MERGE (outer)-[:CONTAINS]->(inner)
                """,
                    batch=nested_fn_batch,
                    file_path=file_path_str,
                )

            ruby_modules = file_data.get("modules", [])
            if ruby_modules:
                session.run(
                    """
                    UNWIND $batch AS row
                    MERGE (mod:Module {name: row.name})
                    ON CREATE SET mod.lang = row.lang
                    ON MATCH  SET mod.lang = coalesce(mod.lang, row.lang)
                """,
                    batch=[{"name": m["name"], "lang": lang} for m in ruby_modules],
                )

            js_imports = []
            other_imports = []
            for imp in file_data.get("imports", []):
                if lang == "javascript":
                    module_name = imp.get("source")
                    if module_name:
                        js_imports.append(
                            {
                                "module_name": module_name,
                                "imported_name": imp.get("name", "*"),
                                "alias": imp.get("alias"),
                                "line_number": imp.get("line_number"),
                            }
                        )
                else:
                    other_imports.append(imp)

            if js_imports:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (f:File {path: $file_path})
                    MERGE (m:Module {name: row.module_name})
                    MERGE (f)-[r:IMPORTS]->(m)
                    SET r.imported_name = row.imported_name,
                        r.alias = row.alias,
                        r.line_number = row.line_number
                """,
                    batch=js_imports,
                    file_path=file_path_str,
                )

            if other_imports:
                normalized_other_imports = self._normalize_import_rows(
                    other_imports,
                    lang=lang,
                    file_path_str=file_path_str,
                    repo_path_str=resolved_repo_str,
                )
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (f:File {path: $file_path})
                    MERGE (m:Module {name: row.module_name})
                    SET m.alias = row.alias,
                        m.full_import_name = coalesce(row.full_import_name, m.full_import_name)
                    MERGE (f)-[r:IMPORTS]->(m)
                    SET r.line_number = row.line_number,
                        r.alias = row.alias,
                        r.imported_name = row.imported_name,
                        r.full_import_name = row.full_import_name
                """,
                    batch=normalized_other_imports,
                    file_path=file_path_str,
                )

            module_inclusions = file_data.get("module_inclusions", [])
            if module_inclusions:
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (c:Class {name: row.class_name, path: $file_path})
                    MERGE (m:Module {name: row.module_name})
                    MERGE (c)-[:INCLUDES]->(m)
                """,
                    batch=[
                        {"class_name": i["class"], "module_name": i["module"]} for i in module_inclusions
                    ],
                    file_path=file_path_str,
                )

    def add_minimal_file_node(
        self, file_path: Path, repo_path: Path, is_dependency: bool = False
    ) -> None:
        file_path_str = str(file_path.resolve())
        file_name = file_path.name
        repo_name = repo_path.name
        repo_path_str = str(repo_path.resolve())

        with self.driver.session() as session:
            session.run(
                """
                MERGE (r:Repository {path: $repo_path})
                SET r.name = $repo_name
                """,
                repo_path=repo_path_str,
                repo_name=repo_name,
            )

            session.run(
                """
                MERGE (f:File {path: $file_path})
                SET f.name = $file_name,
                    f.is_dependency = $is_dependency
                """,
                file_path=file_path_str,
                file_name=file_name,
                is_dependency=is_dependency,
            )

            file_path_obj = Path(file_path_str)
            repo_path_obj = Path(repo_path_str)
            try:
                relative_path_to_file = file_path_obj.relative_to(repo_path_obj)
            except ValueError:
                relative_path_to_file = Path(file_path_obj.name)

            parent_path = repo_path_str
            parent_label = "Repository"

            for part in relative_path_to_file.parts[:-1]:
                current_path = Path(parent_path) / part
                current_path_str = str(current_path)

                session.run(
                    f"""
                    MATCH (p:{parent_label} {{path: $parent_path}})
                    MERGE (d:Directory {{path: $current_path}})
                    SET d.name = $part
                    MERGE (p)-[:CONTAINS]->(d)
                """,
                    parent_path=parent_path,
                    current_path=current_path_str,
                    part=part,
                )

                parent_path = current_path_str
                parent_label = "Directory"

            session.run(
                f"""
                MATCH (p:{parent_label} {{path: $parent_path}})
                MATCH (f:File {{path: $file_path}})
                MERGE (p)-[:CONTAINS]->(f)
            """,
                parent_path=parent_path,
                file_path=file_path_str,
            )

    def write_function_call_groups(
        self,
        fn_to_fn: List[Dict],
        fn_to_cls: List[Dict],
        cls_to_fn: List[Dict],
        cls_to_cls: List[Dict],
        file_to_fn: List[Dict],
        file_to_cls: List[Dict],
    ) -> None:
        batch_size = 1000
        q_fn_to_fn = """
            UNWIND $batch AS row
            MATCH (caller:Function {name: row.caller_name, path: row.caller_file_path, line_number: row.caller_line_number})
            MATCH (called:Function {name: row.called_name, path: row.called_file_path})
            CREATE (caller)-[:CALLS {line_number: row.line_number, args: row.args, full_call_name: row.full_call_name}]->(called)
        """
        q_fn_to_cls = """
            UNWIND $batch AS row
            MATCH (caller:Function {name: row.caller_name, path: row.caller_file_path, line_number: row.caller_line_number})
            MATCH (called:Class {name: row.called_name, path: row.called_file_path})
            CREATE (caller)-[:CALLS {line_number: row.line_number, args: row.args, full_call_name: row.full_call_name}]->(called)
        """
        q_cls_to_fn = """
            UNWIND $batch AS row
            MATCH (caller:Class {name: row.caller_name, path: row.caller_file_path, line_number: row.caller_line_number})
            MATCH (called:Function {name: row.called_name, path: row.called_file_path})
            CREATE (caller)-[:CALLS {line_number: row.line_number, args: row.args, full_call_name: row.full_call_name}]->(called)
        """
        q_cls_to_cls = """
            UNWIND $batch AS row
            MATCH (caller:Class {name: row.caller_name, path: row.caller_file_path, line_number: row.caller_line_number})
            MATCH (called:Class {name: row.called_name, path: row.called_file_path})
            CREATE (caller)-[:CALLS {line_number: row.line_number, args: row.args, full_call_name: row.full_call_name}]->(called)
        """
        q_file_to_fn = """
            UNWIND $batch AS row
            MATCH (caller:File {path: row.caller_file_path})
            MATCH (called:Function {name: row.called_name, path: row.called_file_path})
            CREATE (caller)-[:CALLS {line_number: row.line_number, args: row.args, full_call_name: row.full_call_name}]->(called)
        """
        q_file_to_cls = """
            UNWIND $batch AS row
            MATCH (caller:File {path: row.caller_file_path})
            MATCH (called:Class {name: row.called_name, path: row.called_file_path})
            CREATE (caller)-[:CALLS {line_number: row.line_number, args: row.args, full_call_name: row.full_call_name}]->(called)
        """
        groups: List[Tuple[str, List[Dict], str]] = [
            ("fn→fn", fn_to_fn, q_fn_to_fn),
            ("fn→cls", fn_to_cls, q_fn_to_cls),
            ("cls→fn", cls_to_fn, q_cls_to_fn),
            ("cls→cls", cls_to_cls, q_cls_to_cls),
            ("file→fn", file_to_fn, q_file_to_fn),
            ("file→cls", file_to_cls, q_file_to_cls),
        ]
        total_all = sum(len(g[1]) for g in groups)
        with self.driver.session() as session:
            for label, calls, query in groups:
                if not calls:
                    info_logger(f"[CALLS] {label}: 0 (skipped)")
                    continue
                t0 = time.time()
                for i in range(0, len(calls), batch_size):
                    batch = calls[i : i + batch_size]
                    session.run(query, batch=batch)
                    written = min(i + batch_size, len(calls))
                    if written % 5000 < batch_size or written == len(calls):
                        elapsed = time.time() - t0
                        info_logger(f"[CALLS] {label}: {written}/{len(calls)} ({elapsed:.1f}s)")
                elapsed = time.time() - t0
                info_logger(f"[CALLS] {label} done: {len(calls)} in {elapsed:.1f}s")
        info_logger(f"[CALLS] All complete: {total_all} CALLS relationships processed.")

    def _create_csharp_inheritance_and_interfaces(
        self, session: Any, file_data: Dict[str, Any], imports_map: dict
    ) -> None:
        if file_data.get("lang") != "c_sharp":
            return

        caller_file_path = str(Path(file_data["path"]).resolve())

        for type_list_name, type_label in [
            ("classes", "Class"),
            ("structs", "Struct"),
            ("records", "Record"),
            ("interfaces", "Interface"),
        ]:
            for type_item in file_data.get(type_list_name, []):
                if not type_item.get("bases"):
                    continue

                for base_str in type_item["bases"]:
                    base_name = base_str.split("<")[0].strip()

                    is_interface = False
                    resolved_path = caller_file_path

                    for iface in file_data.get("interfaces", []):
                        if iface["name"] == base_name:
                            is_interface = True
                            break

                    if base_name in imports_map:
                        possible_paths = imports_map[base_name]
                        if len(possible_paths) > 0:
                            resolved_path = possible_paths[0]

                    base_index = type_item["bases"].index(base_str)

                    if is_interface or (base_index > 0 and type_label == "Class"):
                        session.run(
                            """
                            MATCH (child {name: $child_name, path: $path})
                            WHERE child:Class OR child:Struct OR child:Record
                            MATCH (iface:Interface {name: $interface_name})
                            MERGE (child)-[:IMPLEMENTS]->(iface)
                        """,
                            child_name=type_item["name"],
                            path=caller_file_path,
                            interface_name=base_name,
                        )
                    else:
                        session.run(
                            """
                            MATCH (child {name: $child_name, path: $path})
                            WHERE child:Class OR child:Record OR child:Interface
                            MATCH (parent {name: $parent_name})
                            WHERE parent:Class OR parent:Record OR parent:Interface
                            MERGE (child)-[:INHERITS]->(parent)
                        """,
                            child_name=type_item["name"],
                            path=caller_file_path,
                            parent_name=base_name,
                        )

    def write_inheritance_links(
        self,
        inheritance_batch: List[Dict[str, Any]],
        csharp_files: List[Dict[str, Any]],
        imports_map: dict,
    ) -> None:
        info_logger(
            f"[INHERITS] Resolved {len(inheritance_batch)} inheritance links, "
            f"{len(csharp_files)} C# files. Writing to Neo4j..."
        )
        batch_size = 500
        with self.driver.session() as session:
            for i in range(0, len(inheritance_batch), batch_size):
                batch = inheritance_batch[i : i + batch_size]
                session.run(
                    """
                    UNWIND $batch AS row
                    MATCH (child:Class {name: row.child_name, path: row.path})
                    MATCH (parent:Class {name: row.parent_name, path: row.resolved_parent_file_path})
                    MERGE (child)-[:INHERITS]->(parent)
                """,
                    batch=batch,
                )

            for file_data in csharp_files:
                self._create_csharp_inheritance_and_interfaces(session, file_data, imports_map)

        info_logger(f"[INHERITS] Complete: {len(inheritance_batch)} inheritance links processed.")

    def write_scip_call_edges(
        self, files_data: Dict[str, Any], name_from_symbol: Callable[[str], str]
    ) -> None:
        with self.driver.session() as session:
            for file_data in files_data.values():
                for edge in file_data.get("function_calls_scip", []):
                    try:
                        session.run(
                            """
                            MATCH (caller:Function {name: $caller_name, path: $caller_file, line_number: $caller_line})
                            MATCH (callee:Function {name: $callee_name, path: $callee_file, line_number: $callee_line})
                            MERGE (caller)-[:CALLS {line_number: $ref_line, source: 'scip'}]->(callee)
                        """,
                            caller_name=name_from_symbol(edge["caller_symbol"]),
                            caller_file=edge["caller_file"],
                            caller_line=edge["caller_line"],
                            callee_name=edge["callee_name"],
                            callee_file=edge["callee_file"],
                            callee_line=edge["callee_line"],
                            ref_line=edge["ref_line"],
                        )
                    except Exception:
                        pass

    def delete_file_from_graph(self, path: str) -> None:
        file_path_str = str(Path(path).resolve())
        with self.driver.session() as session:
            parents_res = session.run(
                """
                MATCH (f:File {path: $path})<-[:CONTAINS*]-(d:Directory)
                RETURN d.path as path ORDER BY d.path DESC
            """,
                path=file_path_str,
            )
            parent_paths = [record["path"] for record in parents_res]

            session.run(
                """
                MATCH (f:File {path: $path})
                OPTIONAL MATCH (f)-[:CONTAINS]->(element)
                DETACH DELETE f, element
            """,
                path=file_path_str,
            )
            info_logger(f"Deleted file and its elements from graph: {file_path_str}")

            for p in parent_paths:
                session.run(
                    """
                    MATCH (d:Directory {path: $path})
                    WHERE NOT (d)-[:CONTAINS]->()
                    DETACH DELETE d
                """,
                    path=p,
                )

    def delete_repository_from_graph(self, repo_path: str) -> bool:
        repo_path_str = str(Path(repo_path).resolve())
        path_prefix = repo_path_str + "/"
        with self.driver.session() as session:
            result = session.run(
                "MATCH (r:Repository {path: $path}) RETURN count(r) as cnt", path=repo_path_str
            ).single()
            if not result or result["cnt"] == 0:
                warning_logger(f"Attempted to delete non-existent repository: {repo_path_str}")
                return False

        if self._backend_type() == "kuzudb":
            # Kuzu can be unstable on large relationship/node delete operations.
            # Use small batches, clear relationships first, then delete nodes.
            for rel_type in ("CALLS", "INHERITS", "IMPORTS", "HAS_PARAMETER", "CONTAINS", "IMPLEMENTS", "INCLUDES"):
                while True:
                    with self.driver.session() as session:
                        if rel_type == "CONTAINS":
                            result = session.run(
                                "MATCH (a)-[r:CONTAINS]->(b) "
                                "WHERE a.path STARTS WITH $prefix OR a.path = $path OR b.path STARTS WITH $prefix "
                                "WITH r LIMIT 500 DELETE r RETURN count(r) AS deleted",
                                prefix=path_prefix,
                                path=repo_path_str,
                            ).single()
                        else:
                            result = session.run(
                                f"MATCH (a)-[r:{rel_type}]->(b) "
                                "WHERE a.path STARTS WITH $prefix OR b.path STARTS WITH $prefix "
                                "WITH r LIMIT 500 DELETE r RETURN count(r) AS deleted",
                                prefix=path_prefix,
                            ).single()
                        deleted = result["deleted"] if result else 0
                    if deleted == 0:
                        break
                    info_logger(f"[DELETE] Removed {deleted} {rel_type} rels for {repo_path_str}")

            labels = (
                "Parameter",
                "Function",
                "Class",
                "Variable",
                "Trait",
                "Interface",
                "Macro",
                "Struct",
                "Enum",
                "Union",
                "Annotation",
                "Record",
                "Property",
                "File",
                "Directory",
            )
            for label in labels:
                while True:
                    with self.driver.session() as session:
                        result = session.run(
                            f"MATCH (n:{label}) WHERE n.path STARTS WITH $prefix "
                            "WITH n LIMIT 500 DELETE n RETURN count(n) AS deleted",
                            prefix=path_prefix,
                        ).single()
                        deleted = result["deleted"] if result else 0
                    if deleted == 0:
                        break
                    info_logger(f"[DELETE] Removed {deleted} {label} nodes for {repo_path_str}")

            with self.driver.session() as session:
                session.run("MATCH (r:Repository {path: $path}) DETACH DELETE r", path=repo_path_str)

            info_logger(f"Deleted repository and its contents from graph: {repo_path_str}")
            return True

        for rel_type in ("CALLS", "INHERITS", "IMPORTS"):
            while True:
                with self.driver.session() as session:
                    result = session.run(
                        f"MATCH (a)-[r:{rel_type}]->(b) "
                        "WHERE a.path STARTS WITH $prefix OR b.path STARTS WITH $prefix "
                        "WITH r LIMIT 5000 DELETE r RETURN count(r) AS deleted",
                        prefix=path_prefix,
                    ).single()
                    deleted = result["deleted"] if result else 0
                if deleted == 0:
                    break
                info_logger(f"[DELETE] Removed {deleted} {rel_type} rels for {repo_path_str}")

        while True:
            with self.driver.session() as session:
                result = session.run(
                    "MATCH (a)-[r:CONTAINS]->(b) "
                    "WHERE a.path STARTS WITH $prefix OR a.path = $path "
                    "WITH r LIMIT 10000 DELETE r RETURN count(r) AS deleted",
                    prefix=path_prefix,
                    path=repo_path_str,
                ).single()
                deleted = result["deleted"] if result else 0
            if deleted == 0:
                break
            info_logger(f"[DELETE] Removed {deleted} CONTAINS rels for {repo_path_str}")

        for label in ("Function", "Class", "File"):
            while True:
                with self.driver.session() as session:
                    result = session.run(
                        f"MATCH (n:{label}) WHERE n.path STARTS WITH $prefix "
                        "WITH n LIMIT 10000 DETACH DELETE n RETURN count(n) AS deleted",
                        prefix=path_prefix,
                    ).single()
                    deleted = result["deleted"] if result else 0
                if deleted == 0:
                    break
                info_logger(f"[DELETE] Removed {deleted} {label} nodes for {repo_path_str}")

        with self.driver.session() as session:
            session.run("MATCH (r:Repository {path: $path}) DETACH DELETE r", path=repo_path_str)

        info_logger(f"Deleted repository and its contents from graph: {repo_path_str}")
        return True

    def get_caller_file_paths(self, file_path_str: str) -> set:
        with self.driver.session() as session:
            result = session.run(
                "MATCH (caller)-[:CALLS]->(callee) "
                "WHERE callee.path = $path "
                "RETURN DISTINCT coalesce(caller.path, '') AS p",
                path=file_path_str,
            )
            return {r["p"] for r in result if r["p"] and r["p"] != file_path_str}

    def get_inheritance_neighbor_paths(self, file_path_str: str) -> set:
        with self.driver.session() as session:
            result = session.run(
                "MATCH (a)-[:INHERITS]->(b) "
                "WHERE a.path = $path OR b.path = $path "
                "RETURN DISTINCT CASE WHEN a.path = $path THEN b.path ELSE a.path END AS p",
                path=file_path_str,
            )
            return {r["p"] for r in result if r["p"] and r["p"] != file_path_str}

    def delete_outgoing_calls_from_files(self, file_paths: List[str]) -> None:
        with self.driver.session() as session:
            result = session.run(
                "MATCH (a)-[r:CALLS]->(b) WHERE a.path IN $paths DELETE r RETURN count(r) AS cnt",
                paths=file_paths,
            ).single()
            cnt = result["cnt"] if result else 0
        info_logger(f"[RELINK] Deleted {cnt} outgoing CALLS from {len(file_paths)} caller files")

    def delete_inherits_for_files(self, file_paths: List[str]) -> None:
        with self.driver.session() as session:
            result = session.run(
                "MATCH (a)-[r:INHERITS]->(b) WHERE a.path IN $paths OR b.path IN $paths "
                "DELETE r RETURN count(r) AS cnt",
                paths=file_paths,
            ).single()
            cnt = result["cnt"] if result else 0
        info_logger(f"[RELINK] Deleted {cnt} INHERITS for {len(file_paths)} affected files")

    def get_repo_class_lookup(self, repo_path: Path) -> Dict[str, set]:
        prefix = str(repo_path.resolve()) + "/"
        result_map: Dict[str, set] = {}
        with self.driver.session() as session:
            result = session.run(
                "MATCH (c:Class) WHERE c.path STARTS WITH $prefix "
                "RETURN c.name AS name, c.path AS path",
                prefix=prefix,
            )
            for record in result:
                path = record["path"]
                if path not in result_map:
                    result_map[path] = set()
                result_map[path].add(record["name"])
        return result_map

    def delete_relationship_links(self, repo_path: Path) -> None:
        repo_path_str = str(repo_path.resolve()) + "/"
        with self.driver.session() as session:
            result = session.run(
                "MATCH (a)-[r:CALLS]->(b) WHERE a.path STARTS WITH $prefix DELETE r RETURN count(r) AS cnt",
                prefix=repo_path_str,
            ).single()
            calls_deleted = result["cnt"] if result else 0

            result = session.run(
                "MATCH (a)-[r:INHERITS]->(b) WHERE a.path STARTS WITH $prefix DELETE r RETURN count(r) AS cnt",
                prefix=repo_path_str,
            ).single()
            inherits_deleted = result["cnt"] if result else 0

        info_logger(
            f"[RELINK] Cleared {calls_deleted} CALLS and {inherits_deleted} INHERITS before re-linking: {repo_path}"
        )
