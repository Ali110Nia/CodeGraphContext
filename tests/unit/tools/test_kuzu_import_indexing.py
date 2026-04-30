from pathlib import Path

import pytest

from codegraphcontext.core.database_kuzu import KuzuDBManager
from codegraphcontext.tools.code_finder import CodeFinder
from codegraphcontext.tools.indexing.persistence.writer import GraphWriter


kuzu = pytest.importorskip("kuzu")


class _KuzuDBAdapter:
    def __init__(self, driver):
        self._driver = driver

    def get_driver(self):
        return self._driver

    def get_backend_type(self) -> str:
        return "kuzudb"


def _new_kuzu_driver(tmp_path: Path):
    manager = KuzuDBManager(str(tmp_path / "db"))
    return manager, manager.get_driver()


def test_kuzu_indexes_typescript_import_rows_without_full_import_name(tmp_path):
    repo = tmp_path / "repo"
    src = repo / "src"
    src.mkdir(parents=True)
    file_path = src / "page.ts"
    file_path.write_text("import React, { useMemo as memo } from 'react';\n", encoding="utf-8")

    manager, driver = _new_kuzu_driver(tmp_path)
    try:
        writer = GraphWriter(driver)
        writer.add_repository_to_graph(repo)
        writer.add_file_to_graph(
            {
                "path": str(file_path),
                "repo_path": str(repo),
                "lang": "typescript",
                "imports": [
                    {"name": "default", "source": "react", "alias": "React", "line_number": 1},
                    {"name": "useMemo", "source": "react", "alias": "memo", "line_number": 1},
                ],
                "functions": [],
                "classes": [],
                "variables": [],
            },
            repo.name,
            {},
            repo_path_str=str(repo.resolve()),
        )

        finder = CodeFinder(_KuzuDBAdapter(driver))
        deps = finder.find_module_dependencies("react")

        assert deps["importers"]
        assert deps["importers"][0]["importer_file_path"].endswith("page.ts")
    finally:
        manager.close_driver()


def test_kuzu_indexes_import_rows_with_missing_optional_fields(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    file_path = repo / "main.py"
    file_path.write_text("import os\n", encoding="utf-8")

    manager, driver = _new_kuzu_driver(tmp_path)
    try:
        writer = GraphWriter(driver)
        writer.add_repository_to_graph(repo)
        writer.add_file_to_graph(
            {
                "path": str(file_path),
                "repo_path": str(repo),
                "lang": "python",
                "imports": [{"name": "os", "line_number": 1}],
                "functions": [],
                "classes": [],
                "variables": [],
            },
            repo.name,
            {},
            repo_path_str=str(repo.resolve()),
        )

        with driver.session() as session:
            rows = session.run(
                """
                MATCH (:File)-[r:IMPORTS]->(m:Module)
                RETURN m.name as name, m.full_import_name as full_import_name, r.alias as alias
                """
            ).data()

        assert rows == [{"name": "os", "full_import_name": "os", "alias": ""}]
    finally:
        manager.close_driver()
