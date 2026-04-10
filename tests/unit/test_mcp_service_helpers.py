from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from codegraphcontext.cli import cli_helpers


def test_systemd_mcp_unit_name_defaults_and_custom():
    assert cli_helpers._systemd_mcp_unit_name("mcp-read") == "cgc-mcp-mcp-read.service"
    assert cli_helpers._systemd_mcp_unit_name("mcp-read", unit_name="custom") == "custom.service"
    assert cli_helpers._systemd_mcp_unit_name("mcp-read", unit_name="custom.service") == "custom.service"


def test_mcp_service_install_helper_writes_readonly_unit(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(
        cli_helpers,
        "resolve_context",
        lambda **_kwargs: SimpleNamespace(database="kuzudb", db_path=str(tmp_path / "db" / "kuzudb")),
    )

    calls: list[list[str]] = []

    def _fake_systemctl(args: list[str]):
        calls.append(args)
        return 0, "", ""

    monkeypatch.setattr(cli_helpers, "_run_systemctl_user", _fake_systemctl)

    cli_helpers.mcp_service_install_helper(
        context="mcp-read",
        unit_name="cgc-mcp-test.service",
        enable=True,
        start=True,
        global_context=True,
    )

    unit_file = tmp_path / ".config" / "systemd" / "user" / "cgc-mcp-test.service"
    text = unit_file.read_text(encoding="utf-8")

    assert "mcp start --readonly" in text
    assert "--context mcp-read" in text
    assert "--global-context" in text
    assert "Restart=always" in text

    assert ["daemon-reload"] in calls
    assert ["enable", "cgc-mcp-test.service"] in calls
    assert ["restart", "cgc-mcp-test.service"] in calls
