"""Sicherung der Dateiliste/Warteschlange (JSON im Config-Ordner).

Wird beim Beenden und zwischendurch geschrieben und beim Start wieder
eingelesen, damit die Liste Neustarts und Container-Updates übersteht.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
from enum import Enum
from pathlib import Path

from models import (AudioMode, AudioStream, CropInfo, HDRType, JobStatus,
                    MediaFile, SubtitleStream, VideoMode)

VERSION = 1


def queue_file_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    return base / "Kristian" / "handpack_queue.json"


def _default(o):
    if isinstance(o, Enum):
        return o.name
    if isinstance(o, Path):
        return str(o)
    raise TypeError(type(o))


def dumps(files: list[MediaFile], pending: list[Path]) -> str:
    return json.dumps({
        "version": VERSION,
        "files": [dataclasses.asdict(mf) for mf in files],
        "pending": [str(p) for p in pending],
    }, default=_default, ensure_ascii=False, indent=1)


def _known(cls, d: dict) -> dict:
    names = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in d.items() if k in names}


def _enum(cls, name):
    if name is None:
        return None
    try:
        return cls[name]
    except KeyError:
        return None


def _audio(d: dict) -> AudioStream:
    d = _known(AudioStream, d)
    d["mode"] = _enum(AudioMode, d.get("mode"))
    return AudioStream(**d)


def _media_file(d: dict) -> MediaFile:
    d = _known(MediaFile, d)
    d["path"] = Path(d["path"])
    d["hdr"] = _enum(HDRType, d.get("hdr")) or HDRType.SDR
    d["status"] = _enum(JobStatus, d.get("status")) or JobStatus.READY
    d["video_mode"] = _enum(VideoMode, d.get("video_mode"))
    if d.get("output_path"):
        d["output_path"] = Path(d["output_path"])
    else:
        d["output_path"] = None
    d["crop"] = CropInfo(**_known(CropInfo, d.get("crop") or {}))
    d["audio_streams"] = [_audio(a) for a in d.get("audio_streams") or []]
    d["subtitle_streams"] = [
        SubtitleStream(**_known(SubtitleStream, s))
        for s in d.get("subtitle_streams") or []]
    return MediaFile(**d)


def loads(text: str) -> tuple[list[MediaFile], list[Path]]:
    data = json.loads(text)
    files = []
    for entry in data.get("files", []):
        try:
            files.append(_media_file(entry))
        except (KeyError, TypeError, ValueError):
            continue  # defekter Eintrag: überspringen, Rest behalten
    pending = [Path(p) for p in data.get("pending", [])]
    return files, pending


def save(text: str, path: Path | None = None) -> None:
    path = path or queue_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)  # atomar: kein halb geschriebenes File bei Abbruch


def load(path: Path | None = None) -> tuple[list[MediaFile], list[Path]]:
    path = path or queue_file_path()
    try:
        return loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], []
