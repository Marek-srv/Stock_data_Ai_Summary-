import os
import plistlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from graph_stock.app import create_app
from graph_stock.startup import LABEL, StartupError, StartupManager


class Runner:
    def __init__(self): self.calls = []
    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="service = running", stderr="")


def project(tmp_path):
    root = tmp_path / "project"
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("python")
    return root


def test_definition_is_bounded_to_local_service_and_contains_no_credentials(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-appear")
    monkeypatch.setenv("GRAPH_STOCK_CODEX", "/secret/custom/path")
    manager = StartupManager(root, tmp_path / "home", "Darwin", 501, Runner())
    payload = plistlib.loads(manager.render())
    rendered = manager.render().decode()
    assert payload["Label"] == LABEL
    assert payload["ProgramArguments"][-4:] == ["--host", "127.0.0.1", "--port", "8765"]
    assert payload["RunAtLoad"] is True and payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["WorkingDirectory"] == str(root)
    assert payload["EnvironmentVariables"] == {
        "GRAPH_STOCK_AUTOSTART": "launchd",
        "GRAPH_STOCK_STATE_DIR": str(root / ".state"),
        "GRAPH_STOCK_VAULT": str(root / ".state" / "fixture-vault"),
    }
    assert "must-not-appear" not in rendered and "/secret/custom/path" not in rendered


def test_install_status_restart_and_removal_are_idempotent(tmp_path):
    root = project(tmp_path); runner = Runner()
    manager = StartupManager(root, tmp_path / "home", "Darwin", 501, runner)
    first = manager.install()
    assert first["installed"] and first["definition_valid"] and first["loaded"]
    content = manager.plist_path.read_bytes()
    second = manager.install()
    assert second["installed"] and manager.plist_path.read_bytes() == content
    commands = [call[0][1] for call in runner.calls]
    assert commands.count("bootstrap") == 2 and commands.count("kickstart") == 2
    removed = manager.uninstall()
    assert not removed["installed"] and not manager.plist_path.exists()
    assert manager.uninstall()["installed"] is False


def test_unsupported_host_and_foreign_file_are_left_unchanged(tmp_path):
    root = project(tmp_path)
    unsupported = StartupManager(root, tmp_path / "linux", "Linux", 1000, Runner())
    with pytest.raises(StartupError, match="macOS only"):
        unsupported.install()
    manager = StartupManager(root, tmp_path / "home", "Darwin", 501, Runner())
    manager.plist_path.parent.mkdir(parents=True)
    manager.plist_path.write_bytes(plistlib.dumps({"Label": "another.service"}))
    with pytest.raises(StartupError, match="another service"):
        manager.uninstall()
    assert manager.plist_path.exists()


def test_api_exposes_opt_in_status_without_mutating_host(tmp_path):
    root_home = tmp_path / "home"
    app = create_app(tmp_path / "state", startup_home=root_home, startup_platform="Darwin")
    with TestClient(app, base_url="http://localhost") as client:
        status = client.get("/api/v1/startup")
    assert status.status_code == 200
    body = status.json()
    assert body["supported"] and not body["installed"]
    assert body["current_process_started_by"] == os.environ.get("GRAPH_STOCK_AUTOSTART", "manual")
    assert "awake" in body["sleep_limit"] and not root_home.exists()
