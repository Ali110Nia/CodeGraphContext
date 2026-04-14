import asyncio
from pathlib import Path
from unittest.mock import Mock

from codegraphcontext.tools.indexing import pipeline


class _DummyWriter:
    def __init__(self) -> None:
        self.add_repository_to_graph = Mock()
        self.add_file_to_graph = Mock()
        self.write_inheritance_links = Mock()
        self.write_function_call_groups = Mock()


class _DummyJobManager:
    def update_job(self, *args, **kwargs):
        return None


def _mk_parse_file():
    fn = Mock()

    def _parse(repo_path: Path, file: Path, is_dependency: bool):
        return {
            "path": str(file),
            "repo_path": str(repo_path),
            "functions": [],
            "classes": [],
            "imports": [],
        }

    fn.side_effect = _parse
    return fn


def test_run_tree_sitter_index_skips_unsupported_when_disabled(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    py_file = repo / "a.py"
    md_file = repo / "notes.md"
    py_file.write_text("def f():\n    return 1\n", encoding="utf-8")
    md_file.write_text("# Notes\n", encoding="utf-8")

    monkeypatch.setattr(pipeline, "discover_files_to_index", lambda *_, **__: ([py_file, md_file], repo))
    monkeypatch.setattr(pipeline, "pre_scan_for_imports", lambda *_: {})
    monkeypatch.setattr(pipeline, "build_inheritance_and_csharp_files", lambda *_: ([], []))
    monkeypatch.setattr(pipeline, "build_function_call_groups", lambda *_: ([], [], [], [], [], []))
    monkeypatch.setattr(pipeline, "get_config_value", lambda key: "false" if key == "INDEX_UNSUPPORTED_FILES" else None)

    writer = _DummyWriter()
    parse_file = _mk_parse_file()
    add_minimal = Mock()

    asyncio.run(
        pipeline.run_tree_sitter_index_async(
            path=repo,
            is_dependency=False,
            job_id=None,
            cgcignore_path=None,
            writer=writer,
            job_manager=_DummyJobManager(),
            parsers={".py": "python"},
            get_parser=lambda *_: None,
            parse_file=parse_file,
            add_minimal_file_node=add_minimal,
        )
    )

    assert parse_file.call_count == 1
    assert parse_file.call_args[0][1] == py_file
    add_minimal.assert_not_called()
    assert writer.add_file_to_graph.call_count == 1


def test_run_tree_sitter_index_adds_minimal_for_unsupported_when_enabled(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    py_file = repo / "a.py"
    md_file = repo / "notes.md"
    no_ext_file = repo / "README"
    py_file.write_text("def f():\n    return 1\n", encoding="utf-8")
    md_file.write_text("# Notes\n", encoding="utf-8")
    no_ext_file.write_text("text\n", encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "discover_files_to_index",
        lambda *_, **__: ([py_file, md_file, no_ext_file], repo),
    )
    monkeypatch.setattr(pipeline, "pre_scan_for_imports", lambda *_: {})
    monkeypatch.setattr(pipeline, "build_inheritance_and_csharp_files", lambda *_: ([], []))
    monkeypatch.setattr(pipeline, "build_function_call_groups", lambda *_: ([], [], [], [], [], []))
    monkeypatch.setattr(pipeline, "get_config_value", lambda key: "true" if key == "INDEX_UNSUPPORTED_FILES" else None)

    writer = _DummyWriter()
    parse_file = _mk_parse_file()
    add_minimal = Mock()

    asyncio.run(
        pipeline.run_tree_sitter_index_async(
            path=repo,
            is_dependency=False,
            job_id=None,
            cgcignore_path=None,
            writer=writer,
            job_manager=_DummyJobManager(),
            parsers={".py": "python"},
            get_parser=lambda *_: None,
            parse_file=parse_file,
            add_minimal_file_node=add_minimal,
        )
    )

    assert parse_file.call_count == 1
    add_minimal.assert_any_call(md_file, repo.resolve(), False)
    add_minimal.assert_any_call(no_ext_file, repo.resolve(), False)
    assert add_minimal.call_count == 2
    assert writer.add_file_to_graph.call_count == 1
