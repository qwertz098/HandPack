"""Zentraler Log-Kanal.

Worker-Threads senden Zeilen über das Qt-Signal LOG.line; die GUI hängt
sich daran und zeigt sie im optionalen Log-Feld an. Die Verbindung ist
threadübergreifend (Queued Connection), das Senden ist daher aus jedem
Thread erlaubt.
"""
from __future__ import annotations

import subprocess

from PySide6.QtCore import QObject, Signal


class _LogBus(QObject):
    line = Signal(str)


LOG = _LogBus()


def log(msg: str) -> None:
    LOG.line.emit(msg.rstrip())


def log_cmd(cmd: list[str]) -> None:
    log("$ " + subprocess.list2cmdline(cmd))
