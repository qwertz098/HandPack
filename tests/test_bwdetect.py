"""Tests für bwdetect.is_grayscale: Mittelwertbildung über mehrere Samples,
Schwellwert-Entscheidung, Robustheit bei fehlenden Messwerten."""
from pathlib import Path
from types import SimpleNamespace

import bwdetect
from models import HDRType, MediaFile


def make_mf(duration=120.0) -> MediaFile:
    return MediaFile(path=Path("dummy.mkv"), duration=duration, hdr=HDRType.SDR)


def satavg_stderr(*values: float) -> str:
    lines = []
    for v in values:
        lines.append(f"[Parsed_metadata_1 @ 0x0] lavfi.signalstats.SATAVG={v}")
    return "\n".join(lines) + "\n"


def fake_run_factory(stderr_per_call):
    calls = {"n": 0}

    def _fake_run(cmd, **kwargs):
        idx = min(calls["n"], len(stderr_per_call) - 1)
        calls["n"] += 1
        return SimpleNamespace(returncode=0, stdout="", stderr=stderr_per_call[idx])

    return _fake_run, calls


def test_low_saturation_detected_as_grayscale(monkeypatch):
    lines = [satavg_stderr(0.0, 0.3, 0.1)] * bwdetect.SAMPLES
    fake_run, _ = fake_run_factory(lines)
    monkeypatch.setattr(bwdetect.subprocess, "run", fake_run)

    assert bwdetect.is_grayscale(make_mf(), "ffmpeg") is True


def test_high_saturation_is_not_grayscale(monkeypatch):
    lines = [satavg_stderr(85.0, 90.2, 88.5)] * bwdetect.SAMPLES
    fake_run, _ = fake_run_factory(lines)
    monkeypatch.setattr(bwdetect.subprocess, "run", fake_run)

    assert bwdetect.is_grayscale(make_mf(), "ffmpeg") is False


def test_borderline_saturation_uses_threshold(monkeypatch):
    just_under = [satavg_stderr(1.5)] * bwdetect.SAMPLES
    fake_run, _ = fake_run_factory(just_under)
    monkeypatch.setattr(bwdetect.subprocess, "run", fake_run)
    assert bwdetect.is_grayscale(make_mf(), "ffmpeg") is True

    just_over = [satavg_stderr(2.5)] * bwdetect.SAMPLES
    fake_run2, _ = fake_run_factory(just_over)
    monkeypatch.setattr(bwdetect.subprocess, "run", fake_run2)
    assert bwdetect.is_grayscale(make_mf(), "ffmpeg") is False


def test_no_measurements_defaults_to_not_grayscale(monkeypatch):
    """Kein Messwert gefunden (z. B. Filter-/Parsing-Problem) -> im Zweifel
    NICHT automatisch auf Monochrome umschalten (würde bei Farbmaterial die
    Farbe zerstören); sicherer Default ist False."""
    lines = ["frame=  10 fps=25 q=-1.0\n"] * bwdetect.SAMPLES
    fake_run, _ = fake_run_factory(lines)
    monkeypatch.setattr(bwdetect.subprocess, "run", fake_run)

    assert bwdetect.is_grayscale(make_mf(), "ffmpeg") is False


def test_timeout_on_one_sample_does_not_abort_detection(monkeypatch):
    import subprocess as sp

    calls = {"n": 0}

    def _fake_run(cmd, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sp.TimeoutExpired(cmd=cmd, timeout=60)
        return SimpleNamespace(returncode=0, stdout="", stderr=satavg_stderr(0.0))

    monkeypatch.setattr(bwdetect.subprocess, "run", _fake_run)
    assert bwdetect.is_grayscale(make_mf(), "ffmpeg") is True
    assert calls["n"] == bwdetect.SAMPLES
