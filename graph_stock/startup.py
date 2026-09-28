"""Optional, reversible macOS LaunchAgent integration for the local service."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import platform
import subprocess
import sys
from pathlib import Path


LABEL = "com.graphstock.local"
STARTUP_VERSION = "macos-launch-agent/v1"


class StartupError(RuntimeError):
    pass


class StartupManager:
    def __init__(self, project_root: Path | None = None, home: Path | None = None,
                 system: str | None = None, uid: int | None = None, runner=None):
        self.project_root = (project_root or Path(__file__).resolve().parent.parent).resolve()
        self.home = (home or Path.home()).resolve()
        self.system = system or platform.system()
        self.uid = os.getuid() if uid is None else uid
        self.runner = runner or subprocess.run

    @property
    def plist_path(self):
        return self.home / "Library" / "LaunchAgents" / f"{LABEL}.plist"

    @property
    def state_dir(self):
        return self.project_root / ".state"

    def _require_macos(self):
        if self.system != "Darwin":
            raise StartupError("Automatic login startup is currently supported on macOS only.")

    def definition(self):
        python = self.project_root / ".venv" / "bin" / "python"
        if not python.is_file():
            raise StartupError("Create the project virtual environment before enabling login startup.")
        logs = self.state_dir / "startup"
        return {
            "Label": LABEL,
            "ProgramArguments": [
                str(python), "-m", "uvicorn", "graph_stock.app:app",
                "--host", "127.0.0.1", "--port", "8765",
            ],
            "WorkingDirectory": str(self.project_root),
            "EnvironmentVariables": {
                "GRAPH_STOCK_AUTOSTART": "launchd",
                "GRAPH_STOCK_STATE_DIR": str(self.state_dir),
                "GRAPH_STOCK_VAULT": str(self.state_dir / "fixture-vault"),
            },
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "ProcessType": "Background",
            "ThrottleInterval": 10,
            "StandardOutPath": str(logs / "stdout.log"),
            "StandardErrorPath": str(logs / "stderr.log"),
        }

    def render(self):
        self._require_macos()
        return plistlib.dumps(self.definition(), fmt=plistlib.FMT_XML, sort_keys=True)

    def _run(self, args, check=True):
        return self.runner(args, check=check, capture_output=True, text=True)

    def install(self, load=True):
        self._require_macos()
        content = self.render()
        self.plist_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_dir.joinpath("startup").mkdir(parents=True, exist_ok=True)
        if self.plist_path.is_symlink():
            raise StartupError("Refusing to replace a symbolic-link startup definition.")
        temporary = self.plist_path.with_suffix(".plist.tmp")
        temporary.write_bytes(content)
        os.chmod(temporary, 0o600)
        temporary.replace(self.plist_path)
        if load:
            domain = f"gui/{self.uid}"
            self._run(["launchctl", "bootout", domain, str(self.plist_path)], check=False)
            try:
                self._run(["launchctl", "bootstrap", domain, str(self.plist_path)])
                self._run(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"])
            except Exception as error:
                raise StartupError("The startup file was saved, but launchd could not load it. Run status for details.") from error
        return self.status(inspect_service=load)

    def uninstall(self, unload=True):
        self._require_macos()
        if self.plist_path.exists() and self.plist_path.is_symlink():
            raise StartupError("Refusing to remove a symbolic-link startup definition.")
        if self.plist_path.exists():
            try:
                saved = plistlib.loads(self.plist_path.read_bytes())
            except Exception as error:
                raise StartupError("The startup file is unreadable and was left unchanged.") from error
            if saved.get("Label") != LABEL:
                raise StartupError("The startup file belongs to another service and was left unchanged.")
        if unload:
            self._run(["launchctl", "bootout", f"gui/{self.uid}", str(self.plist_path)], check=False)
        self.plist_path.unlink(missing_ok=True)
        return self.status(inspect_service=False)

    def status(self, inspect_service=False):
        supported = self.system == "Darwin"
        installed = self.plist_path.is_file() and not self.plist_path.is_symlink()
        valid = False
        if installed:
            try:
                saved = plistlib.loads(self.plist_path.read_bytes())
                valid = saved.get("Label") == LABEL and saved.get("WorkingDirectory") == str(self.project_root)
            except Exception:
                pass
        loaded = None
        detail = None
        if inspect_service and supported and installed:
            result = self._run(["launchctl", "print", f"gui/{self.uid}/{LABEL}"], check=False)
            loaded = result.returncode == 0
            detail = "loaded" if loaded else "saved but not loaded"
        return {
            "schema_version": STARTUP_VERSION,
            "platform": self.system,
            "supported": supported,
            "installed": installed,
            "definition_valid": valid,
            "loaded": loaded,
            "detail": detail,
            "current_process_started_by": os.environ.get("GRAPH_STOCK_AUTOSTART", "manual"),
            "plist_path": str(self.plist_path),
            "logs": {
                "stdout": str(self.state_dir / "startup" / "stdout.log"),
                "stderr": str(self.state_dir / "startup" / "stderr.log"),
            },
            "sleep_limit": "Jobs run only while the Mac is awake; persisted catch-up runs after restart.",
            "install_command": ".venv/bin/python -m graph_stock.startup install",
            "remove_command": ".venv/bin/python -m graph_stock.startup uninstall",
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage optional graph_stock login startup on macOS")
    parser.add_argument("action", choices=("render", "install", "status", "uninstall"))
    parser.add_argument("--no-load", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    manager = StartupManager()
    try:
        if args.action == "render":
            sys.stdout.buffer.write(manager.render())
            return 0
        result = (manager.install(not args.no_load) if args.action == "install" else
                  manager.uninstall(not args.no_load) if args.action == "uninstall" else
                  manager.status(inspect_service=True))
        print(json.dumps(result, indent=2))
        return 0 if result["supported"] else 2
    except StartupError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
