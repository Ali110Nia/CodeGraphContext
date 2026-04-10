from __future__ import annotations

import json

from codegraphcontext.cli import setup_wizard


def test_generate_mcp_json_includes_readonly_arg(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(setup_wizard, "_save_neo4j_credentials", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup_wizard, "_configure_ide", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup_wizard.shutil, "which", lambda _name: "/usr/local/bin/cgc")

    setup_wizard._generate_mcp_json(
        {"uri": "neo4j://localhost:7687", "username": "neo4j", "password": "password"}
    )

    mcp_config = json.loads((tmp_path / "mcp.json").read_text(encoding="utf-8"))
    args = mcp_config["mcpServers"]["CodeGraphContext"]["args"]
    assert "--readonly" in args

