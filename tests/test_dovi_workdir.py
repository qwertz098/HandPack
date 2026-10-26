"""Tests für dovi.make_workdir: bevorzugt lokalen Temp-Ordner bei genug
freiem Platz (vermeidet langsames Schreiben der riesigen DV-Zwischendateien
übers Netz), sonst Fallback neben die Ausgabedatei."""
import shutil
from pathlib import Path
from types import SimpleNamespace

import dovi
from models import HDRType, MediaFile


def make_mf(video_stream_size=0, file_exists=False) -> MediaFile:
    mf = MediaFile(path=Path("nonexistent_src.mkv"), video_stream_size=video_stream_size,
                   hdr=HDRType.SDR)
    return mf


def test_prefers_local_temp_when_enough_free_space(monkeypatch, tmp_path):
    output = tmp_path / "out" / "Movie.mkv"
    output.parent.mkdir(parents=True)
    monkeypatch.setattr(dovi.shutil, "disk_usage",
                        lambda p: SimpleNamespace(free=100 * 1024**3))
    mf = make_mf(video_stream_size=10 * 1024**3)

    wd = dovi.make_workdir(output, mf)
    try:
        assert wd.parent == Path(dovi.tempfile.gettempdir())
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def test_falls_back_to_output_parent_when_not_enough_local_space(monkeypatch, tmp_path):
    output = tmp_path / "out" / "Movie.mkv"
    output.parent.mkdir(parents=True)
    monkeypatch.setattr(dovi.shutil, "disk_usage",
                        lambda p: SimpleNamespace(free=1024))  # 1 KB frei
    mf = make_mf(video_stream_size=10 * 1024**3)

    wd = dovi.make_workdir(output, mf)
    try:
        assert wd.parent == output.parent
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def test_falls_back_when_size_unknown_and_no_mf(tmp_path):
    """Ohne mf (Größe unbekannt) im Zweifel konservativ -> Fallback, statt
    ins Blaue hinein lokal zu schreiben und evtl. den Datenträger zu füllen."""
    output = tmp_path / "out" / "Movie.mkv"
    output.parent.mkdir(parents=True)

    wd = dovi.make_workdir(output, None)
    try:
        assert wd.parent == output.parent
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def test_disk_usage_error_falls_back_gracefully(monkeypatch, tmp_path):
    output = tmp_path / "out" / "Movie.mkv"
    output.parent.mkdir(parents=True)

    def _raise(p):
        raise OSError("no such volume")
    monkeypatch.setattr(dovi.shutil, "disk_usage", _raise)
    mf = make_mf(video_stream_size=10 * 1024**3)

    wd = dovi.make_workdir(output, mf)
    try:
        assert wd.parent == output.parent
    finally:
        shutil.rmtree(wd, ignore_errors=True)
