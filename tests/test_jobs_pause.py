"""Tests für EncodeWorker.pause()/resume(): reine Zustandslogik + korrekte
SIGSTOP/SIGCONT-Aufrufe, ohne echten ffmpeg-Prozess. can_pause() ist absichtlich
plattformabhängig (kein SIGSTOP-Äquivalent unter Windows) - das wird hier über
monkeypatch von sys.platform geprüft statt uns auf die tatsächliche Plattform
zu verlassen, auf der die Tests laufen."""
import signal
from types import SimpleNamespace

import pytest

import jobs


@pytest.fixture(autouse=True)
def _fake_posix_signals(monkeypatch):
    """SIGSTOP/SIGCONT existieren im signal-Modul nur auf POSIX - auf einem
    Windows-Testrechner (wo die stdlib diese Konstanten schlicht nicht
    definiert) sonst AttributeError. Für die reine Zustandslogik-Prüfung
    reichen beliebige Platzhalterwerte."""
    monkeypatch.setattr(signal, "SIGSTOP", 19, raising=False)
    monkeypatch.setattr(signal, "SIGCONT", 18, raising=False)


def make_worker() -> jobs.EncodeWorker:
    return jobs.EncodeWorker(tools={}, encoder="libx265", target="Original")


def fake_running_proc(pid=4242):
    return SimpleNamespace(pid=pid, poll=lambda: None)


def test_can_pause_true_on_linux(monkeypatch):
    monkeypatch.setattr(jobs.sys, "platform", "linux")
    assert make_worker().can_pause()


def test_can_pause_false_on_windows(monkeypatch):
    monkeypatch.setattr(jobs.sys, "platform", "win32")
    assert not make_worker().can_pause()


def test_pause_sends_sigstop_to_running_process(monkeypatch):
    monkeypatch.setattr(jobs.sys, "platform", "linux")
    calls = []
    monkeypatch.setattr(jobs.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    w = make_worker()
    w._proc = fake_running_proc(pid=1234)

    w.pause()

    assert w.is_paused()
    assert calls == [(1234, signal.SIGSTOP)]


def test_resume_sends_sigcont_only_if_was_paused(monkeypatch):
    monkeypatch.setattr(jobs.sys, "platform", "linux")
    calls = []
    monkeypatch.setattr(jobs.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    w = make_worker()
    w._proc = fake_running_proc(pid=1234)

    w.resume()  # war nie pausiert -> kein Aufruf
    assert calls == []

    w.pause()
    calls.clear()
    w.resume()
    assert calls == [(1234, signal.SIGCONT)]
    assert not w.is_paused()


def test_pause_is_noop_on_windows_even_if_process_running(monkeypatch):
    monkeypatch.setattr(jobs.sys, "platform", "win32")
    calls = []
    monkeypatch.setattr(jobs.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    w = make_worker()
    w._proc = fake_running_proc()

    w.pause()

    assert not w.is_paused()
    assert calls == []


def test_pause_is_noop_when_no_process_running():
    w = make_worker()
    w._proc = None
    w.pause()
    assert not w.is_paused()


def test_pause_twice_only_sends_sigstop_once(monkeypatch):
    """Doppelter Pause-Klick darf nicht zweimal SIGSTOP schicken (harmlos,
    aber unnötig) - is_paused()-Guard soll das verhindern."""
    monkeypatch.setattr(jobs.sys, "platform", "linux")
    calls = []
    monkeypatch.setattr(jobs.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    w = make_worker()
    w._proc = fake_running_proc()

    w.pause()
    w.pause()

    assert len(calls) == 1
