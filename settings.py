"""Tool-Pfade (ffmpeg, ffprobe, dovi_tool, mkvmerge) und QSettings-Persistenz."""
from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QSettings

from models import (AudioMode, DEFAULT_PRESET, DEFAULT_TUNE, ENCODE_PRESETS,
                    TUNE_PROFILES, VideoMode)

ORG = "Kristian"
APP = "HandPack"

# Zusätzliche Suchpfade je Plattform
_EXTRA_DIRS = {
    "Windows": [
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\ProgramData\chocolatey\bin",
    ],
    "Darwin": ["/opt/homebrew/bin", "/usr/local/bin"],
    "Linux": ["/usr/local/bin"],
}

TOOLS = ("ffmpeg", "ffprobe", "dovi_tool", "mkvmerge")


def subprocess_flags() -> dict:
    """Verhindert Konsolenfenster unter Windows."""
    if platform.system() == "Windows":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def find_tool(name: str, settings: QSettings) -> str | None:
    suffix = ".exe" if platform.system() == "Windows" else ""
    # 1) manuell gesetzter Pfad
    manual = settings.value(f"tools/{name}", "")
    if manual and Path(manual).exists():
        return str(manual)
    # 2) app-lokaler .tools/-Ordner (In-App-Download); bei PyInstaller-EXE
    #    liegt der Ordner neben der EXE. Punkt-Präfix: vom Sync ausgenommen.
    import sys
    base = (Path(sys.executable).resolve().parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent)
    # Migration VOR der Auflösung: sonst werden tools\-Pfade gemerkt,
    # die der spätere Rename (tools -> .tools) ungültig macht
    legacy = base / "tools"
    if not (base / ".tools").exists() and legacy.is_dir():
        try:
            legacy.rename(base / ".tools")
        except OSError:
            pass  # in Benutzung -> Fallback unten greift
    for d in (".tools", "tools"):  # "tools" = Altbestand, falls Rename scheitert
        local = base / d / (name + suffix)
        if local.exists():
            return str(local)
    # 3) PATH
    exe = shutil.which(name)
    if exe:
        return exe
    # 4) übliche Orte
    for d in _EXTRA_DIRS.get(platform.system(), []):
        cand = Path(d) / (name + suffix)
        if cand.exists():
            return str(cand)
    return None


class AppSettings:
    """Dünner Wrapper um QSettings mit typisierten Zugriffen."""

    def __init__(self) -> None:
        self.qs = QSettings(ORG, APP)
        self.tools: dict[str, str | None] = {}
        self.refresh_tools()

    def refresh_tools(self) -> None:
        for t in TOOLS:
            self.tools[t] = find_tool(t, self.qs)

    # --- globale Encode-Defaults ---
    @property
    def target_resolution(self) -> str:
        v = self.qs.value("encode/target", "Original")
        # Alte Bezeichnungen aus früheren Versionen migrieren
        return {"SD": "576p", "4K": "2160p"}.get(v, v)

    @target_resolution.setter
    def target_resolution(self, v: str) -> None:
        self.qs.setValue("encode/target", v)

    @property
    def crf(self) -> int:
        return int(self.qs.value("encode/crf", 20))

    @crf.setter
    def crf(self, v: int) -> None:
        self.qs.setValue("encode/crf", int(v))

    @property
    def encoder(self) -> str:
        return self.qs.value("encode/encoder", "libx265")

    @encoder.setter
    def encoder(self, v: str) -> None:
        self.qs.setValue("encode/encoder", v)

    @property
    def preset(self) -> str:
        v = self.qs.value("encode/preset", DEFAULT_PRESET)
        return v if v in ENCODE_PRESETS else DEFAULT_PRESET

    @preset.setter
    def preset(self, v: str) -> None:
        self.qs.setValue("encode/preset", v)

    @property
    def tune(self) -> str:
        v = self.qs.value("encode/tune", DEFAULT_TUNE)
        return v if v in TUNE_PROFILES else DEFAULT_TUNE

    @tune.setter
    def tune(self, v: str) -> None:
        self.qs.setValue("encode/tune", v)

    @property
    def output_override(self) -> str:
        return self.qs.value("encode/output_dir", "")

    @output_override.setter
    def output_override(self, v: str) -> None:
        self.qs.setValue("encode/output_dir", v)

    @property
    def name_tag(self) -> str:
        """Freies Kürzel, das ganz ans Ende jedes Ausgabedateinamens gehängt
        wird (z. B. Encoder-/Gruppen-/Versionskürzel)."""
        return self.qs.value("encode/name_tag", "")

    @name_tag.setter
    def name_tag(self, v: str) -> None:
        self.qs.setValue("encode/name_tag", v)

    @property
    def autocrop(self) -> bool:
        return self.qs.value("encode/autocrop", "true") in (True, "true", "1")

    @autocrop.setter
    def autocrop(self, v: bool) -> None:
        self.qs.setValue("encode/autocrop", "true" if v else "false")

    @property
    def crop_min_px(self) -> int:
        """Crop-Ränder unter diesem Wert (px je Seite) werden ignoriert."""
        return int(self.qs.value("encode/crop_min_px", 20))

    @crop_min_px.setter
    def crop_min_px(self, v: int) -> None:
        self.qs.setValue("encode/crop_min_px", int(v))

    @property
    def crop_first_only(self) -> bool:
        return self.qs.value("encode/crop_first_only", "false") in (True, "true", "1")

    @crop_first_only.setter
    def crop_first_only(self, v: bool) -> None:
        self.qs.setValue("encode/crop_first_only", "true" if v else "false")

    @property
    def show_log(self) -> bool:
        return self.qs.value("ui/show_log", "false") in (True, "true", "1")

    @show_log.setter
    def show_log(self, v: bool) -> None:
        self.qs.setValue("ui/show_log", "true" if v else "false")

    @property
    def audio_mode(self) -> AudioMode:
        v = self.qs.value("encode/audio_mode", AudioMode.COPY.value)
        try:
            return AudioMode(v)
        except ValueError:
            return AudioMode.COPY

    @audio_mode.setter
    def audio_mode(self, v: AudioMode) -> None:
        self.qs.setValue("encode/audio_mode", v.value)

    @property
    def video_mode(self) -> VideoMode:
        v = self.qs.value("encode/video_mode", VideoMode.ENCODE.value)
        try:
            return VideoMode(v)
        except ValueError:
            return VideoMode.ENCODE

    @video_mode.setter
    def video_mode(self, v: VideoMode) -> None:
        self.qs.setValue("encode/video_mode", v.value)

    def set_tool_path(self, name: str, path: str) -> None:
        self.qs.setValue(f"tools/{name}", path)
        self.refresh_tools()
