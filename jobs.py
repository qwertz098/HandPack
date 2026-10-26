"""Hintergrund-Worker.

- AnalyzeWorker: ffprobe + optional cropdetect je Datei (QThreadPool)
- EncodeWorker: arbeitet die Job-Queue sequenziell ab; Queue darf während
  der Laufzeit wachsen (Dateien nachträglich hinzufügbar).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThread, Signal

import dovi
from bwdetect import is_grayscale
from cropdetect import detect_crop
from encoders import build_encode_command
from models import AudioMode, CropInfo, HDRType, JobStatus, MediaFile, VideoMode
from probe import probe_file
from settings import subprocess_flags

_TIME_RE = re.compile(r"out_time_ms=(\d+)")
_TIME_US_RE = re.compile(r"out_time_us=(\d+)")
_FPS_RE = re.compile(r"fps=([\d.]+)")


# ---------------------------------------------------------------- Analyse

class AnalyzeSignals(QObject):
    finished = Signal(int, object)        # row, MediaFile
    failed = Signal(int, str)             # row, error
    crop_progress = Signal(int, int, int) # row, done_samples, total_samples


class AnalyzeWorker(QRunnable):
    """Analysiert eine Datei. do_crop steuert, ob cropdetect läuft."""

    def __init__(self, row: int, path: Path, ffprobe: str, ffmpeg: str,
                 do_crop: bool, default_crf: int, crop_min_px: int = 0):
        super().__init__()
        self.row = row
        self.path = path
        self.ffprobe = ffprobe
        self.ffmpeg = ffmpeg
        self.do_crop = do_crop
        self.default_crf = default_crf
        self.crop_min_px = crop_min_px
        self.signals = AnalyzeSignals()

    def run(self) -> None:
        # Keep a local reference so the GC cannot collect signals mid-run.
        # PySide6 may delete a QObject's C++ backing even while Python holds
        # self.signals if the reference count drops to zero on the C++ side.
        sig = self.signals
        try:
            mf = probe_file(self.path, self.ffprobe)
            mf.crf = self.default_crf
            if self.do_crop:
                def _crop_cb(done: int, total: int) -> None:
                    try:
                        sig.crop_progress.emit(self.row, done, total)
                    except RuntimeError:
                        pass
                mf.crop = detect_crop(mf, self.ffmpeg, progress_cb=_crop_cb,
                                     min_px=self.crop_min_px)
                # An dieselbe "Extra-Analyse an/aus"-Einstellung gekoppelt
                # wie Cropdetect (ähnliche Kosten: ein paar kurze Samples).
                # Nur vorschlagen, nicht erzwingen -> Checkbox in der
                # Tabelle, jederzeit vom Nutzer übersteuerbar.
                mf.monochrome = is_grayscale(mf, self.ffmpeg)
            mf.status = JobStatus.READY
            sig.finished.emit(self.row, mf)
        except Exception as e:  # noqa: BLE001
            try:
                sig.failed.emit(self.row, str(e))
            except RuntimeError:
                pass


class CropOnlyWorker(QRunnable):
    """Crop-Nachanalyse für eine bereits analysierte Datei (Kontextmenü)."""

    def __init__(self, row: int, mf: MediaFile, ffmpeg: str,
                 crop_min_px: int = 0):
        super().__init__()
        self.row = row
        self.mf = mf
        self.ffmpeg = ffmpeg
        self.crop_min_px = crop_min_px
        self.signals = AnalyzeSignals()

    def run(self) -> None:
        sig = self.signals
        try:
            def _crop_cb(done: int, total: int) -> None:
                try:
                    sig.crop_progress.emit(self.row, done, total)
                except RuntimeError:
                    pass
            crop = detect_crop(self.mf, self.ffmpeg, progress_cb=_crop_cb,
                               min_px=self.crop_min_px)
            sig.finished.emit(self.row, crop)
        except Exception as e:  # noqa: BLE001
            try:
                sig.failed.emit(self.row, str(e))
            except RuntimeError:
                pass


# ---------------------------------------------------------------- Encode

class EncodeWorker(QThread):
    """Sequenzielle Abarbeitung. Jobs können jederzeit angehängt werden."""

    job_started = Signal(int)
    job_progress = Signal(int, float, int)  # row, 0..100, bytes written so far
    job_speed = Signal(int, float)          # row, current encode fps
    job_finished = Signal(int)
    job_failed = Signal(int, str)
    queue_empty = Signal()

    def __init__(self, tools: dict[str, str | None], encoder: str, target: str,
                 preset: str = "medium", tune: str = "none",
                 audio_mode: AudioMode = AudioMode.COPY,
                 video_mode: VideoMode = VideoMode.ENCODE):
        super().__init__()
        self.tools = tools
        self.encoder = encoder
        self.target = target
        self.preset = preset
        self.tune = tune
        self.audio_mode = audio_mode
        self.video_mode = video_mode
        self._queue: list[tuple[int, MediaFile, Path]] = []
        self._lock = threading.Lock()
        self._wakeup = threading.Event()
        self._stop = False
        self._active = False   # gerade ein Job in Bearbeitung?
        self._proc: subprocess.Popen | None = None
        self._paused = False

    # --- öffentliche API (GUI-Thread) ---
    def is_busy(self) -> bool:
        """True, wenn ein Job läuft oder noch welche in der Queue warten.
        (Der Thread selbst läuft als Endlosschleife dauerhaft weiter.)"""
        with self._lock:
            return self._active or bool(self._queue)

    def enqueue(self, row: int, mf: MediaFile, output: Path) -> None:
        with self._lock:
            self._queue.append((row, mf, output))
        self._wakeup.set()

    def dequeue(self, row: int) -> bool:
        """Entfernt einen noch nicht gestarteten Job aus der Warteschlange."""
        with self._lock:
            for i, (r, _mf, _out) in enumerate(self._queue):
                if r == row:
                    del self._queue[i]
                    return True
        return False

    def remap_rows(self, mapping: dict[int, int]) -> None:
        """Nach Zeilentausch in der GUI: Row-Indizes der wartenden Jobs
        anpassen und Queue wieder in Tabellenreihenfolge bringen."""
        with self._lock:
            self._queue = [(mapping.get(r, r), mf, out)
                           for r, mf, out in self._queue]
            self._queue.sort(key=lambda job: job[0])

    def stop(self) -> None:
        self._stop = True
        self._wakeup.set()
        if self._proc and self._proc.poll() is None:
            self._proc.kill()

    # Pause/Fortsetzen: hält den laufenden ffmpeg-Prozess per SIGSTOP an,
    # statt ihn abzubrechen – ffmpeg selbst merkt davon nichts, der
    # Fortschritt bleibt exakt an der pausierten Stelle stehen. Nur auf
    # POSIX verfügbar (SIGSTOP/SIGCONT); Windows kennt kein Prozess-Pendant
    # dazu (bräuchte SuspendThread/ResumeThread je Thread über die WinAPI –
    # siehe TODO.md), daher dort bewusst ein No-Op.
    def can_pause(self) -> bool:
        return sys.platform != "win32"

    def pause(self) -> None:
        if not self.can_pause() or self._paused:
            return
        if self._proc and self._proc.poll() is None:
            import signal
            os.kill(self._proc.pid, signal.SIGSTOP)
            self._paused = True

    def resume(self) -> None:
        if not self._paused:
            return
        if self._proc and self._proc.poll() is None:
            import signal
            os.kill(self._proc.pid, signal.SIGCONT)
        self._paused = False

    def is_paused(self) -> bool:
        return self._paused

    # --- Worker-Thread ---
    def run(self) -> None:
        while not self._stop:
            with self._lock:
                job = self._queue.pop(0) if self._queue else None
                self._active = job is not None
            if job is None:
                self.queue_empty.emit()
                self._wakeup.wait()
                self._wakeup.clear()
                continue
            row, mf, output = job
            self._paused = False
            self.job_started.emit(row)
            try:
                output.parent.mkdir(parents=True, exist_ok=True)
                effective_video_mode = mf.video_mode or self.video_mode
                if (effective_video_mode == VideoMode.ENCODE
                        and mf.hdr == HDRType.DOLBY_VISION
                        and self.tools.get("dovi_tool")):
                    self._encode_dv(row, mf, output)
                else:
                    self._encode_plain(row, mf, output)
                if self._stop:
                    return
                self.job_finished.emit(row)
            except Exception as e:  # noqa: BLE001
                if not self._stop:
                    self.job_failed.emit(row, str(e))
            finally:
                with self._lock:
                    self._active = False

    def _run_ffmpeg_with_progress(self, cmd: list[str], row: int,
                                  duration: float, output: Path,
                                  base: float = 0.0, span: float = 100.0) -> None:
        from applog import log, log_cmd
        log_cmd(cmd)
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, **subprocess_flags())
        if self._paused and self.can_pause():
            # Pause wurde zwischen zwei Pipeline-Stufen angefordert (z. B.
            # während der Dolby-Vision-Pipeline zwischen RPU-Extraktion und
            # HDR10-Encode) – den gerade gestarteten Prozess sofort mit
            # anhalten, damit die Pause über Stufenwechsel hinweg gilt.
            import signal
            os.kill(self._proc.pid, signal.SIGSTOP)
        stderr_tail: list[str] = []

        def drain_stderr():
            for line in self._proc.stderr:  # type: ignore[union-attr]
                log("  " + line)
                stderr_tail.append(line)
                if len(stderr_tail) > 40:
                    stderr_tail.pop(0)

        t = threading.Thread(target=drain_stderr, daemon=True)
        t.start()
        for line in self._proc.stdout:  # type: ignore[union-attr]
            if self._stop:
                self._proc.kill()
                return
            fm = _FPS_RE.search(line)
            if fm:
                try:
                    self.job_speed.emit(row, float(fm.group(1)))
                except ValueError:
                    pass
            m = _TIME_RE.search(line) or _TIME_US_RE.search(line)
            if m and duration > 0:
                done = int(m.group(1)) / 1_000_000 / duration
                pct = base + span * min(done, 1.0)
                try:
                    written = output.stat().st_size
                except OSError:
                    written = 0
                self.job_progress.emit(row, pct, written)
        rc = self._proc.wait()
        t.join(timeout=2)
        if rc != 0 and not self._stop:
            raise RuntimeError("ffmpeg-Fehler: " + "".join(stderr_tail)[-400:])

    def _encode_plain(self, row: int, mf: MediaFile, output: Path) -> None:
        cmd = build_encode_command(mf, self.tools["ffmpeg"], mf.encoder or self.encoder,
                                   mf.target or self.target, output,
                                   preset=mf.preset or self.preset,
                                   tune=mf.tune or self.tune,
                                   audio_mode=self.audio_mode,
                                   video_mode=mf.video_mode or self.video_mode,
                                   monochrome=mf.monochrome)
        self._run_ffmpeg_with_progress(cmd, row, mf.duration, output)

    def _encode_dv(self, row: int, mf: MediaFile, output: Path) -> None:
        workdir = dovi.make_workdir(output, mf)
        try:
            self.job_progress.emit(row, 1.0, 0)
            rpu = dovi.extract_rpu(mf, self.tools["ffmpeg"],
                                   self.tools["dovi_tool"], workdir)
            if self._stop:
                return
            hevc_out = workdir / "encoded.hevc"
            cmd = dovi.build_dv_encode_command(
                mf, self.tools["ffmpeg"], mf.encoder or self.encoder,
                mf.target or self.target, hevc_out,
                preset=mf.preset or self.preset, tune=mf.tune or self.tune)
            # Encode 5..90%, Rest für Inject/Mux.
            # Größe via hevc_out tracken (finale MKV existiert erst nach Mux).
            self._run_ffmpeg_with_progress(cmd, row, mf.duration, hevc_out,
                                           base=5.0, span=85.0)
            if self._stop:
                return
            self.job_progress.emit(row, 92.0, 0)
            dovi.inject_and_mux(mf, hevc_out, rpu, output,
                                self.tools["dovi_tool"],
                                self.tools.get("mkvmerge"),
                                self.tools["ffmpeg"], workdir,
                                audio_mode=self.audio_mode)
            self.job_progress.emit(row, 100.0, 0)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
