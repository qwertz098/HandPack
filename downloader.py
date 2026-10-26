"""In-App-Download von ffmpeg/ffprobe und dovi_tool.

Die Binaries landen in einem app-lokalen Ordner "tools/", der von der
Tool-Suche (settings.py) mit höchster Priorität nach dem manuellen Pfad
berücksichtigt wird. Keine Adminrechte nötig.

Quellen:
- Windows ffmpeg:  gyan.dev release-essentials (ZIP); mit installiertem
                   7-Zip stattdessen release-full (.7z, inkl. libvmaf)
- Linux ffmpeg:    johnvansickle static build (tar.xz)
- macOS ffmpeg:    evermeet.cx (ffmpeg & ffprobe als einzelne ZIPs)
- dovi_tool:       GitHub-Releases (quietvoid/dovi_tool), Asset je Plattform
- mkvmerge:        mkvtoolnix.download, portables Windows-7z. Das Archiv
                   nutzt den BCJ2-Filter, den weder py7zr noch Windows-tar
                   entpacken koennen -> braucht ein installiertes 7-Zip.
                   Unter Linux/macOS nur per Paketmanager -> kein Auto-Download
"""
from __future__ import annotations

import gzip
import json
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

from settings import subprocess_flags

ProgressCb = Callable[[str, float], None]  # (statustext, 0..100 / -1=indeterminate)

USER_AGENT = {"User-Agent": "FF-Transcoder/1.0"}

FFMPEG_URLS = {
    "Windows": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    # "full" build enthält libvmaf (für den Qualitäts-Vergleich), existiert bei
    # gyan.dev aber nur als .7z, nicht als .zip -> braucht installiertes 7-Zip
    # (siehe download_ffmpeg / _find_7zip). Ohne 7-Zip: Fallback auf essentials.
    "Windows-full": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z",
    "Linux": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
    "Darwin-ffmpeg": "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip",
    "Darwin-ffprobe": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
}

DOVI_API = "https://api.github.com/repos/quietvoid/dovi_tool/releases/latest"

MKVTOOLNIX_LATEST = "https://mkvtoolnix.download/latest-release.xml.gz"
MKVTOOLNIX_WIN_7Z = ("https://mkvtoolnix.download/windows/releases/"
                     "{v}/mkvtoolnix-64-bit-{v}.7z")


def _find_7zip() -> str | None:
    exe = shutil.which("7z")
    if exe:
        return exe
    for d in (r"C:\Program Files\7-Zip", r"C:\Program Files (x86)\7-Zip"):
        cand = Path(d) / "7z.exe"
        if cand.exists():
            return str(cand)
    return None


def mkvmerge_downloadable() -> bool:
    """Auto-Download nur unter Windows und nur mit installiertem 7-Zip
    (das MKVToolNix-7z nutzt BCJ2, das py7zr/tar nicht entpacken können)."""
    return platform.system() == "Windows" and _find_7zip() is not None

DOVI_ASSET_PATTERNS = {
    "Windows": ("windows", ".zip"),
    "Linux": ("linux", ".tar.gz"),
    "Darwin": ("macos", ".tar.gz"),  # universal-Build heißt z.B. ...-macOS...
}


def app_dir() -> Path:
    """Verzeichnis der App – bei PyInstaller-EXE neben der EXE."""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def tools_dir() -> Path:
    d = app_dir() / ".tools"
    # Migration: früherer Ordnername "tools" (ohne Punkt, wurde mitgesynct)
    legacy = app_dir() / "tools"
    if not d.exists() and legacy.is_dir():
        try:
            legacy.rename(d)
        except OSError:
            pass  # z.B. Datei gerade in Benutzung -> beim nächsten Start
    d.mkdir(exist_ok=True)
    return d


def _exe(name: str) -> str:
    return name + (".exe" if platform.system() == "Windows" else "")


def _download(url: str, dest: Path, cb: ProgressCb, label: str) -> None:
    req = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        read = 0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            read += len(chunk)
            if total:
                cb(f"{label}: {read // 1048576} / {total // 1048576} MB",
                   100.0 * read / total)
            else:
                cb(f"{label}: {read // 1048576} MB", -1)


def _make_executable(p: Path) -> None:
    if platform.system() != "Windows":
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _extract_members(archive: Path, wanted: dict[str, str], cb: ProgressCb) -> None:
    """Sucht in ZIP/TAR nach Dateien, deren Name auf einen Key in `wanted`
    endet, und legt sie unter tools/<wert> ab."""
    out = tools_dir()
    found: set[str] = set()

    def place(name: str, reader) -> None:
        base = Path(name).name.lower()
        for suffix, target in wanted.items():
            if base == suffix.lower() and target not in found:
                dest = out / target
                with open(dest, "wb") as f:
                    shutil.copyfileobj(reader, f)
                _make_executable(dest)
                found.add(target)
                cb(f"Entpackt: {target}", -1)

    if archive.suffix == ".zip" or zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if not info.is_dir():
                    with z.open(info) as r:
                        place(info.filename, r)
    else:
        with tarfile.open(archive) as t:
            for member in t.getmembers():
                if member.isfile():
                    r = t.extractfile(member)
                    if r:
                        place(member.name, r)

    missing = set(wanted.values()) - found
    if missing:
        raise RuntimeError(f"Im Archiv nicht gefunden: {', '.join(missing)}")


def download_ffmpeg(cb: ProgressCb) -> None:
    sysname = platform.system()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        if sysname == "Darwin":
            for tool in ("ffmpeg", "ffprobe"):
                arc = tmp / f"{tool}.zip"
                _download(FFMPEG_URLS[f"Darwin-{tool}"], arc, cb,
                          f"Lade {tool}")
                _extract_members(arc, {tool: tool}, cb)
        elif sysname == "Windows" and _find_7zip():
            # Full-Build (libvmaf) existiert nur als .7z -> mit installiertem
            # 7-Zip entpacken; sonst Fallback auf essentials.zip unten.
            url = FFMPEG_URLS["Windows-full"]
            arc = tmp / Path(url).name
            _download(url, arc, cb, "Lade ffmpeg (full)")
            cb("Entpacke ffmpeg…", -1)
            sevenzip = _find_7zip()
            r = subprocess.run(
                [sevenzip, "e", str(arc), f"-o{td}",
                 "ffmpeg.exe", "ffprobe.exe", "-r", "-y"],
                capture_output=True, text=True, **subprocess_flags())
            ff, fp = tmp / "ffmpeg.exe", tmp / "ffprobe.exe"
            if r.returncode != 0 or not ff.exists() or not fp.exists():
                raise RuntimeError(
                    f"7-Zip-Entpacken fehlgeschlagen: {r.stderr or r.stdout}")
            out = tools_dir()
            shutil.copyfile(ff, out / "ffmpeg.exe")
            shutil.copyfile(fp, out / "ffprobe.exe")
            cb("Entpackt: ffmpeg.exe, ffprobe.exe", -1)
        else:
            url = FFMPEG_URLS[sysname]
            arc = tmp / Path(url).name
            _download(url, arc, cb, "Lade ffmpeg")
            cb("Entpacke ffmpeg…", -1)
            _extract_members(arc, {
                _exe("ffmpeg"): _exe("ffmpeg"),
                _exe("ffprobe"): _exe("ffprobe"),
            }, cb)


def download_dovi_tool(cb: ProgressCb) -> None:
    cb("Suche dovi_tool-Release…", -1)
    req = urllib.request.Request(DOVI_API, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=30) as resp:
        release = json.loads(resp.read())
    key, ext = DOVI_ASSET_PATTERNS[platform.system()]
    assets = release.get("assets", [])
    # Auf Windows explizit x86_64 bevorzugen (verhindert versehentlichen ARM-Download)
    if platform.system() == "Windows":
        asset = next(
            (a for a in assets
             if key in a["name"].lower() and "x86_64" in a["name"].lower()
             and a["name"].lower().endswith(ext)),
            None)
        if asset is None:  # Fallback: beliebige Windows-Variante
            asset = next(
                (a for a in assets
                 if key in a["name"].lower() and a["name"].lower().endswith(ext)),
                None)
    else:
        asset = next(
            (a for a in assets
             if key in a["name"].lower() and a["name"].lower().endswith(ext)),
            None)
    if not asset:
        raise RuntimeError(
            f"Kein dovi_tool-Asset für {platform.system()} gefunden "
            f"({release.get('tag_name', '?')})")
    with tempfile.TemporaryDirectory() as td:
        arc = Path(td) / asset["name"]
        _download(asset["browser_download_url"], arc, cb,
                  f"Lade dovi_tool {release.get('tag_name', '')}")
        cb("Entpacke dovi_tool…", -1)
        _extract_members(arc, {_exe("dovi_tool"): _exe("dovi_tool")}, cb)


def download_mkvmerge(cb: ProgressCb) -> None:
    sevenzip = _find_7zip() if platform.system() == "Windows" else None
    if not sevenzip:
        raise RuntimeError(
            "mkvmerge-Auto-Download braucht Windows + installiertes 7-Zip; "
            "sonst MKVToolNix manuell installieren: "
            "https://mkvtoolnix.download/downloads.html")
    cb("Suche MKVToolNix-Release…", -1)
    ver = _mkvtoolnix_latest_version()
    if not ver:
        raise RuntimeError("MKVToolNix-Version nicht ermittelbar")
    with tempfile.TemporaryDirectory() as td:
        arc = Path(td) / f"mkvtoolnix-{ver}.7z"
        _download(MKVTOOLNIX_WIN_7Z.format(v=ver), arc, cb,
                  f"Lade MKVToolNix {ver}")
        cb("Entpacke mkvmerge…", -1)
        r = subprocess.run(
            [sevenzip, "e", str(arc), f"-o{td}", "mkvmerge.exe", "-r", "-y"],
            capture_output=True, text=True, **subprocess_flags())
        extracted = Path(td) / "mkvmerge.exe"
        if r.returncode != 0 or not extracted.exists():
            raise RuntimeError(
                f"7-Zip-Entpacken fehlgeschlagen: {r.stderr or r.stdout}")
        shutil.copyfile(extracted, tools_dir() / "mkvmerge.exe")
        cb("Entpackt: mkvmerge.exe", -1)


# ------------------------------------------------------------ Update-Check

FFMPEG_VERSION_SOURCES = {
    # (URL, Regex auf den Antworttext)
    "Windows": ("https://www.gyan.dev/ffmpeg/builds/release-version",
                r"(\d+(?:\.\d+)+)"),
    "Linux": ("https://johnvansickle.com/ffmpeg/release-readme.txt",
              r"version:\s*(\d+(?:\.\d+)+)"),
    "Darwin": ("https://evermeet.cx/ffmpeg/info/ffmpeg/release",
               r'"version":\s*"(\d+(?:\.\d+)+)'),
}


def _http_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if url.endswith(".gz"):
        data = gzip.decompress(data)
    return data.decode("utf-8", "replace")


def _mkvtoolnix_latest_version() -> str | None:
    xml = _http_text(MKVTOOLNIX_LATEST)
    m = re.search(r"<latest-source>.*?<version>([\d.]+)</version>", xml, re.S)
    return m.group(1) if m else None


def local_version(exe: str) -> str | None:
    """Erste Versionsnummer aus `<tool> --version` bzw. `-version`."""
    for flag in ("--version", "-version"):
        try:
            r = subprocess.run([exe, flag], capture_output=True, text=True,
                               timeout=10, **subprocess_flags())
        except OSError:
            return None
        except subprocess.TimeoutExpired:
            return None
        m = re.search(r"(\d+(?:\.\d+)+)", (r.stdout or "") + (r.stderr or ""))
        if m:
            return m.group(1)
    return None


def remote_version(tool: str) -> str | None:
    """Aktuellste verfügbare Version aus der jeweiligen Download-Quelle."""
    if tool == "ffmpeg":
        src = FFMPEG_VERSION_SOURCES.get(platform.system())
        if not src:
            return None
        m = re.search(src[1], _http_text(src[0]))
        return m.group(1) if m else None
    if tool == "dovi_tool":
        release = json.loads(_http_text(DOVI_API))
        m = re.search(r"(\d+(?:\.\d+)+)", release.get("tag_name", ""))
        return m.group(1) if m else None
    if tool == "mkvmerge":
        return _mkvtoolnix_latest_version()
    return None


def _ver_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v))


class UpdateCheckWorker(QThread):
    """Vergleicht lokale mit verfügbaren Versionen.
    candidates: name -> Pfad der lokalen Binary (nur app-eigene tools/).
    done liefert name -> (lokal, remote) für alle veralteten Tools."""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, candidates: dict[str, str]):
        super().__init__()
        self.candidates = candidates

    def run(self) -> None:
        try:
            outdated: dict[str, tuple[str, str]] = {}
            for name, exe in self.candidates.items():
                loc = local_version(exe)
                rem = remote_version(name)
                if loc and rem and _ver_tuple(rem) > _ver_tuple(loc):
                    outdated[name] = (loc, rem)
            self.done.emit(outdated)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class DownloadWorker(QThread):
    """Lädt fehlende Tools im Hintergrund. targets: Teilmenge von
    {'ffmpeg', 'dovi_tool', 'mkvmerge'} ('ffmpeg' umfasst ffprobe)."""

    progress = Signal(str, float)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, targets: list[str]):
        super().__init__()
        self.targets = targets

    def run(self) -> None:
        try:
            cb = lambda txt, pct: self.progress.emit(txt, pct)  # noqa: E731
            if "ffmpeg" in self.targets:
                download_ffmpeg(cb)
            if "dovi_tool" in self.targets:
                download_dovi_tool(cb)
            if "mkvmerge" in self.targets:
                download_mkvmerge(cb)
            self.finished_ok.emit()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
