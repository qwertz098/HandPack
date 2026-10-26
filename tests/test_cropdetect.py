"""Tests für cropdetect.detect_crop: Mehrheitsentscheid über mehrere Samples,
Vollbild-Toleranz, und der Fall "ffmpeg liefert gar keine crop=-Zeilen"
(z. B. bei einem ffmpeg-Build, der sich beim cropdetect-Filter anders
verhält – der reale Bug, der diese Tests ausgelöst hat)."""
from pathlib import Path
from types import SimpleNamespace

import pytest

import cropdetect
from models import HDRType, MediaFile


def make_mf(width=1920, height=1080, duration=120.0) -> MediaFile:
    return MediaFile(path=Path("dummy.mkv"), width=width, height=height,
                     duration=duration, hdr=HDRType.SDR)


def fake_run_factory(stderr_lines_per_call):
    """Liefert ein subprocess.run-Replacement, das für jeden Aufruf die
    nächste vorbereitete stderr-Ausgabe zurückgibt (eine je Sample-Punkt)."""
    calls = {"n": 0}

    def _fake_run(cmd, **kwargs):
        idx = min(calls["n"], len(stderr_lines_per_call) - 1)
        calls["n"] += 1
        return SimpleNamespace(returncode=0, stdout="", stderr=stderr_lines_per_call[idx])

    return _fake_run, calls


def crop_line(w, h, x, y):
    return (f"[Parsed_cropdetect_0 @ 0x0] x1:{x} x2:{x+w-1} y1:{y} y2:{y+h-1} "
            f"w:{w} h:{h} x:{x} y:{y} pts:0 t:0.0 limit:24.000000 crop={w}:{h}:{x}:{y}\n")


def test_detects_majority_crop(monkeypatch):
    """Mehrere Samples mit demselben Crop-Wert -> der wird übernommen."""
    lines = [crop_line(1920, 800, 0, 140)] * cropdetect.SAMPLES
    fake_run, _ = fake_run_factory(lines)
    monkeypatch.setattr(cropdetect.subprocess, "run", fake_run)

    result = cropdetect.detect_crop(make_mf(), "ffmpeg")
    assert result.valid
    assert (result.w, result.h, result.x, result.y) == (1920, 800, 0, 140)


def test_full_frame_is_not_reported_as_crop(monkeypatch):
    """cropdetect meldet die volle Auflösung (kein wirklicher Crop) ->
    detect_crop soll das als "kein Crop" werten, nicht als Crop-Wert."""
    mf = make_mf(width=1920, height=1080)
    lines = [crop_line(1920, 1080, 0, 0)] * cropdetect.SAMPLES
    fake_run, _ = fake_run_factory(lines)
    monkeypatch.setattr(cropdetect.subprocess, "run", fake_run)

    result = cropdetect.detect_crop(mf, "ffmpeg")
    assert not result.valid


def test_no_crop_lines_at_all_returns_invalid(monkeypatch):
    """Regression: wenn der ffmpeg-Build/-Filter GAR KEINE 'crop='-Zeilen
    mehr ins stderr schreibt (z. B. anderes Log-Verhalten in einem neueren
    Build), darf detect_crop nicht abstürzen, sondern muss sauber
    'kein Crop' zurückgeben statt Datenmüll."""
    lines = ["frame=  100 fps=25 q=-1.0 size=N/A time=00:00:04.00\n"] * cropdetect.SAMPLES
    fake_run, _ = fake_run_factory(lines)
    monkeypatch.setattr(cropdetect.subprocess, "run", fake_run)

    result = cropdetect.detect_crop(make_mf(), "ffmpeg")
    assert not result.valid


def test_tie_prefers_larger_area(monkeypatch):
    """Bei Gleichstand der Häufigkeit gewinnt der konservativere (größere)
    Crop-Wert, nicht der zufällig zuerst gesehene."""
    lines = [crop_line(1920, 800, 0, 140), crop_line(1920, 1000, 0, 40)]
    # exakt gleich oft je Wert (ein Sample je Wert)
    fake_run, _ = fake_run_factory(lines)
    monkeypatch.setattr(cropdetect.subprocess, "run", fake_run)

    result = cropdetect.detect_crop(make_mf(), "ffmpeg")
    assert (result.w, result.h) == (1920, 1000)


def test_timeout_on_one_sample_does_not_abort_whole_detection(monkeypatch):
    """Ein einzelnes Sample, das timeoutet, darf die anderen Messpunkte
    nicht verhindern."""
    import subprocess as sp

    calls = {"n": 0}

    def _fake_run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sp.TimeoutExpired(cmd=cmd, timeout=120)
        return SimpleNamespace(returncode=0, stdout="",
                               stderr=crop_line(1920, 800, 0, 140))

    monkeypatch.setattr(cropdetect.subprocess, "run", _fake_run)
    result = cropdetect.detect_crop(make_mf(), "ffmpeg")
    assert result.valid
    assert calls["n"] == cropdetect.SAMPLES


def test_min_px_ignores_small_horizontal_borders(monkeypatch):
    """Seitenränder < min_px werden ignoriert, große Letterbox-Balken bleiben."""
    lines = [crop_line(1900, 800, 10, 140)] * cropdetect.SAMPLES
    fake_run, _ = fake_run_factory(lines)
    monkeypatch.setattr(cropdetect.subprocess, "run", fake_run)

    result = cropdetect.detect_crop(make_mf(), "ffmpeg", min_px=20)
    assert (result.w, result.h, result.x, result.y) == (1920, 800, 0, 140)


def test_min_px_only_small_borders_means_no_crop(monkeypatch):
    lines = [crop_line(1900, 1060, 10, 10)] * cropdetect.SAMPLES
    fake_run, _ = fake_run_factory(lines)
    monkeypatch.setattr(cropdetect.subprocess, "run", fake_run)

    assert not cropdetect.detect_crop(make_mf(), "ffmpeg", min_px=20).valid
