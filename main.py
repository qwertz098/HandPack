"""FF-Transcoder – Start.

Voraussetzungen:
    pip install PySide6
Externe Tools (im PATH oder an üblichen Orten):
    ffmpeg, ffprobe          – Pflicht
    dovi_tool                – für Dolby-Vision-Erhalt (sonst HDR10-Fallback)
    mkvmerge (MKVToolNix)    – bevorzugter Muxer bei DV (sonst ffmpeg-Fallback)
"""
import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from gui import MainWindow
from version import APP_NAME


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon_path = Path(__file__).parent / "icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    # In Docker (Xvfb + fluxbox as window manager) the window would
    # otherwise open at its default size in the top-left corner, leaving
    # the rest of the virtual screen (RESOLUTION in docker-compose.yml)
    # black. showMaximized() relies on a window manager to honor the
    # maximize request (EWMH _NET_WM_STATE_MAXIMIZED) — fluxbox handles
    # that correctly, including reserving space for its own titlebar/
    # border, which manually forcing the full screen geometry would
    # overflow into.
    if os.environ.get("HANDPACK_MAXIMIZE") == "1":
        win.showMaximized()
    else:
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
