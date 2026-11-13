"""Zentraler Log-Kanal.

Worker-Threads senden Zeilen über das Qt-Signal LOG.line; die GUI hängt
sich daran und zeigt sie im optionalen Log-Feld an. Die Verbindung ist
threadübergreifend (Queued Connection), das Senden ist daher aus jedem
Thread erlaubt.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

_MAX_LOG_BYTES = 2 * 1024 * 1024


def log_file_path() -> Path:
    """Logdatei im Config-Ordner (in Docker das gemountete Config-Volume,
    daher übersteht sie Container-Neustarts)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    return base / "Kristian" / "handpack.log"


class _LogBus(QObject):
    line = Signal(str)


LOG = _LogBus()


def _write_file(msg: str) -> None:
    try:
        path = log_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > _MAX_LOG_BYTES:
            path.replace(path.with_suffix(".log.1"))
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass  # Logdatei ist optional


def log(msg: str) -> None:
    msg = msg.rstrip()
    LOG.line.emit(msg)
    _write_file(msg)


def log_cmd(cmd: list[str]) -> None:
    log("$ " + subprocess.list2cmdline(cmd))
