from codegraphcontext.tools.indexing import discovery


def test_discovery_prunes_default_and_config_ignore_dirs(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")

    (repo / ".codegraphcontext").mkdir()
    (repo / ".codegraphcontext" / "state.py").write_text("print('skip')\n", encoding="utf-8")

    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "pkg.js").write_text("console.log('skip')\n", encoding="utf-8")

    (repo / "custom_ignore").mkdir()
    (repo / "custom_ignore" / "ignored.py").write_text("print('skip')\n", encoding="utf-8")

    monkeypatch.setattr(discovery, "build_ignore_spec", lambda **_: (None, None))

    def _cfg(key):
        if key == "IGNORE_DIRS":
            return "custom_ignore"
        return None

    monkeypatch.setattr("codegraphcontext.cli.config_manager.get_config_value", _cfg)

    files, _ = discovery.discover_files_to_index(repo)
    file_names = sorted(f.name for f in files)
    assert file_names == ["main.py"]


def test_discovery_filters_unsupported_when_requested(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / "notes.md").write_text("# md\n", encoding="utf-8")
    (repo / "README").write_text("no ext\n", encoding="utf-8")

    monkeypatch.setattr(discovery, "build_ignore_spec", lambda **_: (None, None))
    monkeypatch.setattr("codegraphcontext.cli.config_manager.get_config_value", lambda _key: None)

    files, _ = discovery.discover_files_to_index(
        repo,
        supported_extensions={".py"},
        include_unsupported=False,
    )
    assert sorted(f.name for f in files) == ["a.py"]

    files_all, _ = discovery.discover_files_to_index(
        repo,
        supported_extensions={".py"},
        include_unsupported=True,
    )
    assert sorted(f.name for f in files_all) == ["README", "a.py", "notes.md"]
