"""Avvio automatico al login su Windows, macOS e Linux."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

APP_ID = "AnimalDesk"


def _command() -> str:
    exe = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):          # eseguibile PyInstaller
        return str(exe)
    return f'"{exe}" -m animaldesk'


def _launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"com.animaldesk.{APP_ID.lower()}.plist"


def _desktop_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / f"{APP_ID.lower()}.desktop"


def is_enabled() -> bool:
    try:
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                winreg.QueryValueEx(key, APP_ID)
            return True
        if sys.platform == "darwin":
            return _launch_agent_path().exists()
        return _desktop_path().exists()
    except (OSError, ImportError):
        return False


def set_enabled(enabled: bool) -> bool:
    """Ritorna True se l'operazione e' riuscita."""
    try:
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                                winreg.KEY_SET_VALUE) as key:
                if enabled:
                    winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, _command())
                else:
                    try:
                        winreg.DeleteValue(key, APP_ID)
                    except FileNotFoundError:
                        pass
            return True

        if sys.platform == "darwin":
            path = _launch_agent_path()
            if not enabled:
                path.unlink(missing_ok=True)
                return True
            path.parent.mkdir(parents=True, exist_ok=True)
            args = "".join(f"        <string>{a}</string>\n" for a in shlex.split(_command()))
            path.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                '<plist version="1.0">\n<dict>\n'
                f"    <key>Label</key>\n    <string>com.animaldesk.{APP_ID.lower()}</string>\n"
                f"    <key>ProgramArguments</key>\n    <array>\n{args}    </array>\n"
                "    <key>RunAtLoad</key>\n    <true/>\n"
                "</dict>\n</plist>\n",
                encoding="utf-8",
            )
            return True

        path = _desktop_path()
        if not enabled:
            path.unlink(missing_ok=True)
            return True
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[Desktop Entry]\nType=Application\nName=AnimalDesk\n"
            f"Exec={_command()}\nX-GNOME-Autostart-enabled=true\nTerminal=false\n",
            encoding="utf-8",
        )
        return True
    except (OSError, ImportError):
        return False
