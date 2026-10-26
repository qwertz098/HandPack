"""Qualitäts-Vergleich vor dem Encode.

Probeencodet kurze Samples (Anzahl/Dauer einstellbar, Default 3 × 10 s bei
20/50/80 % der Laufzeit, wie cropdetect) mit verschiedenen Kombinationen aus
Zielauflösung, CRF und Tune und bewertet sie gegen das Original mit einer
oder mehreren wählbaren Metriken (VMAF/SSIM/PSNR). Ergebnis ist eine Tabelle
mit Score(s) vs. hochgerechneter Dateigröße; nicht von einer anderen
Variante dominierte ("Pareto-optimale") Zeilen werden markiert, da ein
einfaches Score-pro-MB-Verhältnis wegen der nichtlinearen Rate-Distortion-
Kurve irreführend wäre. Die gewählte Variante kann auf die Tabellenzeile im
Hauptfenster übernommen werden.

Doppelklick auf eine Zeile spielt das encodierte Sample (bzw. bei der
Referenzzeile das Original) ab. Mehrere Zeilen auswählen + "Frames
vergleichen" zeigt Einzelbilder aller gewählten Zeilen bei einem
wählbaren Zeitpunkt nebeneinander.

Hinweis: Für den Auflösungsvergleich wird das encodierte Sample auf die
(ggf. gecroppte) Quellgröße zurückskaliert — Standard-Vorgehen, damit alle
Varianten gegen dieselbe Referenz gemessen werden.

Wichtiger Qt-Hinweis: QTableWidget verschiebt beim Sortieren nur
QTableWidgetItems, KEINE Cell-Widgets (z. B. Buttons). Deshalb werden hier
bewusst keine Cell-Widgets für Zeilen-Aktionen verwendet (das hatte zuvor
zu vertauschten/verlorenen Werten geführt, sobald während des Tabellenaufbaus
sortiert wurde) — Zeilen-Metadaten (Vorschaupfad etc.) stecken stattdessen
als Qt.UserRole-Daten in Item 0, die Sortierung korrekt mitnimmt.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QMessageBox, QProgressBar, QPushButton, QSlider,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from encoders import build_video_filter, quality_args, tuning_args
from i18n import t
from models import HDRType, MediaFile, TARGET_ORIGINAL, TARGET_RESOLUTIONS, TUNE_PROFILES
from settings import subprocess_flags

DEFAULT_SAMPLES = 3          # Vorauswahl: Anzahl Messpunkte
DEFAULT_SAMPLE_SECONDS = 10  # Vorauswahl: Dauer je Sample
MIN_SAMPLES, MAX_SAMPLES = 1, 10
MIN_SAMPLE_SECONDS, MAX_SAMPLE_SECONDS = 1, 100

ROLE_PREVIEW_PATH = Qt.UserRole + 1     # str | None – Pfad des Vorschau-Samples
ROLE_PREVIEW_ABS = Qt.UserRole + 2      # float | None – absolute Quellzeit von lokal t=0
ROLE_IS_SOURCE = Qt.UserRole + 3        # bool – True für die Referenzzeile (ganze Quelldatei)
ROLE_SAMPLES = Qt.UserRole + 4          # list[tuple[str, float]] | None – alle Sample-Zeitpunkte

# (Schlüssel, Anzeigename, Nachkommastellen). Reihenfolge = Spaltenreihenfolge
# und Priorität für die Übernehmen-Sortierung/Pareto-Markierung (erste
# gewählte Metrik ist "primär").
AVAILABLE_METRICS = [
    ("vmaf", "VMAF", 1),
    ("ssim", "SSIM", 4),
    ("psnr", "PSNR", 2),
]

_SSIM_RE = re.compile(r"SSIM.*All:\s*([\d.]+)")
_PSNR_RE = re.compile(r"PSNR.*average:\s*([\d.]+)")


class NumericTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem, das nach einem numerischen Wert statt nach dem
    angezeigten Text sortiert (sonst z. B. '9.5' vor '72.5' alphabetisch)."""

    def __init__(self, text: str, value: float) -> None:
        super().__init__(text)
        self._value = value

    def __lt__(self, other: object) -> bool:
        if isinstance(other, NumericTableWidgetItem):
            return self._value < other._value
        return super().__lt__(other)


def has_vmaf(ffmpeg: str) -> bool:
    """True, wenn das ffmpeg-Binary den libvmaf-Filter enthält."""
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-filters"],
                           capture_output=True, text=True, timeout=20,
                           **subprocess_flags())
        return "libvmaf" in r.stdout
    except Exception:
        return False


@dataclass
class QualityVariant:
    target: str    # Auflösungs-Label aus TARGET_RESOLUTIONS ("Original", "1080p", …)
    crf: int
    tune: str      # Key aus TUNE_PROFILES ("none", "grain", …)
    monochrome: bool = False   # unabhängig vom Tune kombinierbar (wie im Hauptfenster)

    def label(self) -> str:
        tune_part = f" / {TUNE_PROFILES.get(self.tune, self.tune)}" if self.tune != "none" else ""
        mono_part = f" / {t('qc_variant_mono')}" if self.monochrome else ""
        return f"{self.target} / CRF {self.crf}{tune_part}{mono_part}"


@dataclass
class VariantResult:
    variant: QualityVariant
    scores: dict[str, float]   # z. B. {"vmaf": 96.4, "ssim": 0.987}; leer = Fehler
    est_bytes: int             # hochgerechnete Videogröße für die Gesamtdatei
    error: str = ""
    preview_path: Path | None = None       # encodiertes Sample (mittlerer Messpunkt)
    preview_start_abs: float | None = None  # absolute Quellzeit von lokal t=0 im Sample
    samples: list[tuple[Path, float]] = field(default_factory=list)  # ALLE Sample-Clips (Pfad, Start)


def _sample_points(duration: float, n_samples: int) -> list[float]:
    """n_samples gleichmäßig verteilte Messpunkte zwischen 10 %/90 % der
    Laufzeit (Intro/Abspann meiden), wie cropdetect. Bei nur einem Sample
    wird die Mitte der Laufzeit genommen."""
    dur = duration or 600
    if n_samples <= 1:
        return [dur * 0.5]
    return [dur * (0.1 + 0.8 * i / (n_samples - 1)) for i in range(n_samples)]


def _mid_index(n_samples: int) -> int:
    return n_samples // 2


def _encode_cmd(mf: MediaFile, ffmpeg: str, encoder: str, preset: str,
                variant: QualityVariant, start: float, duration_s: int,
                out: Path) -> list[str]:
    """Sample-Encode: identische Filter/Parameter wie der echte Encode
    (build_video_filter/quality_args/tuning_args), nur Video."""
    cmd = [ffmpeg, "-hide_banner", "-y",
           "-ss", f"{start:.1f}", "-i", str(mf.path),
           "-t", str(duration_s), "-map", "0:v:0"]
    vf = build_video_filter(mf, variant.target, hw_vaapi=False)
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-c:v", encoder]
    cmd += quality_args(encoder, variant.crf, preset)
    if encoder == "libx265":
        want_10 = mf.hdr != HDRType.SDR or mf.bit_depth >= 10
        if variant.monochrome:
            cmd += ["-pix_fmt", "gray10le" if want_10 else "gray"]
        else:
            cmd += ["-pix_fmt", "yuv420p10le" if want_10 else "yuv420p"]
    cmd += tuning_args(mf, encoder, variant.tune)
    cmd += ["-an", "-sn", str(out)]
    return cmd


def _fps_value(mf: MediaFile) -> float:
    """r_frame_rate ('30/1', '30000/1001', …) als float; Fallback 30."""
    raw = mf.frame_rate or ""
    try:
        if "/" in raw:
            n, d = raw.split("/")
            return float(n) / float(d) if float(d) else 30.0
        return float(raw) if raw else 30.0
    except (ValueError, ZeroDivisionError):
        return 30.0


def _escape_filter_path(p: Path) -> str:
    """ffmpeg-Filter-Optionswerte behandeln ':' als Options-Trenner
    (Windows-Laufwerksbuchstaben wie 'C:' brechen sonst das Parsing des
    Filtergraphen). Braucht BEIDES: den Doppelpunkt mit '\\' escapen UND den
    gesamten Wert in einfache Anführungszeichen setzen — nur eines von
    beiden reicht empirisch nicht (getestet mit ffmpeg 8.1.2/gyan.dev)."""
    s = str(p).replace("\\", "/").replace(":", r"\:")
    return f"'{s}'"


def _metric_cmd(mf: MediaFile, ffmpeg: str, distorted: Path, start: float,
                duration_s: int, metrics: list[str], vmaf_available: bool,
                json_log: Path) -> list[str]:
    """Metrik-Pass: Sample gegen das Original-Segment vergleichen, alle
    gewählten Metriken in EINEM ffmpeg-Aufruf (kein separater Durchlauf pro
    Metrik). Beide Ströme werden auf die (ggf. gecroppte) Quellgröße und
    yuv420p normalisiert, da die Metrik-Filter identische Formate verlangen.

    Wichtig: beide Streams werden per fps-Filter auf ein striktes CFR-Grid
    gezwungen (statt nur PTS-STARTPTS zu nullen). Die Metrik-Filter syncen
    die zwei Eingänge intern über Timestamps (framesync) — da Distorted und
    Referenz unabhängig voneinander per -ss geseekt werden, driften rohe
    PTS-Werte leicht auseinander, was Frames leicht versetzt vergleicht und
    den Score massiv drückt (empirisch: ~78 statt ~99.7 bei einem
    Selbstvergleich). Das feste fps-Raster behebt die Drift zuverlässig.

    Wenn VMAF gewählt ist, werden SSIM/PSNR – falls ebenfalls gewählt – als
    libvmaf-"Features" im selben Durchlauf mitberechnet (spart komplette
    zusätzliche Decode-Pässe). Ohne VMAF werden SSIM/PSNR per `split` auf
    parallele Zweige verteilt, ebenfalls in einem einzigen Aufruf."""
    src_w, src_h = mf.effective_source_rect()
    src_w -= src_w % 2
    src_h -= src_h % 2
    fps = _fps_value(mf)
    ref_chain = f"[1:v]fps={fps}"
    if mf.crop_enabled and mf.crop.valid:
        c = mf.crop
        ref_chain += f",crop={c.w}:{c.h}:{c.x}:{c.y}"
    ref_chain += f",scale={src_w}:{src_h},format=yuv420p[r]"
    dist_chain = (f"[0:v]fps={fps},"
                  f"scale={src_w}:{src_h}:flags=lanczos,format=yuv420p[d]")

    if "vmaf" in metrics and vmaf_available:
        features = []
        if "psnr" in metrics:
            features.append("name=psnr")
        if "ssim" in metrics:
            features.append("name=float_ssim")
        feat_opt = (":feature=" + "|".join(features)) if features else ""
        log_path = _escape_filter_path(json_log)
        vmaf_filter = f"libvmaf=log_path={log_path}:log_fmt=json{feat_opt}"
        graph = f"{dist_chain};{ref_chain};[d][r]{vmaf_filter}"
    else:
        parts = [dist_chain, ref_chain]
        needed = [m for m in metrics if m in ("ssim", "psnr")]
        if len(needed) > 1:
            parts.append("[d]split=2[d1][d2]")
            parts.append("[r]split=2[r1][r2]")
            for i, m in enumerate(needed, start=1):
                parts.append(f"[d{i}][r{i}]{m}")
        elif needed:
            parts.append(f"[d][r]{needed[0]}")
        graph = ";".join(parts)

    return [ffmpeg, "-hide_banner",
            "-i", str(distorted),
            "-ss", f"{start:.1f}", "-t", str(duration_s),
            "-i", str(mf.path),
            "-lavfi", graph, "-f", "null", "-"]


def _parse_metric_output(stderr: str, json_log: Path,
                         metrics: list[str], used_vmaf_pass: bool) -> dict[str, float]:
    """Extrahiert die gewählten Metrik-Scores aus VMAF-JSON-Log und/oder
    Text-Ausgabe (SSIM/PSNR ohne VMAF-Pass)."""
    out: dict[str, float] = {}
    if used_vmaf_pass:
        try:
            data = json.loads(json_log.read_text(encoding="utf-8"))
            pooled = data.get("pooled_metrics", {})
            if "vmaf" in pooled:
                out["vmaf"] = pooled["vmaf"]["mean"]
            # libvmaf's "psnr" feature yields per-channel keys, kein
            # zusammenfassendes "psnr" — psnr_y (Luma) ist der übliche
            # Headline-Wert (wie ihn auch andere Tools als "PSNR" zeigen).
            if "psnr_y" in pooled:
                out["psnr"] = pooled["psnr_y"]["mean"]
            if "float_ssim" in pooled:
                out["ssim"] = pooled["float_ssim"]["mean"]
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    else:
        if "ssim" in metrics:
            m = _SSIM_RE.search(stderr)
            if m:
                out["ssim"] = float(m.group(1))
        if "psnr" in metrics:
            m = _PSNR_RE.search(stderr)
            if m:
                out["psnr"] = float(m.group(1))
    return out


class QualityCheckWorker(QThread):
    """Arbeitet die Varianten sequenziell ab. Cancel killt den laufenden
    ffmpeg-Prozess (Muster: EncodeWorker in jobs.py)."""

    variant_done = Signal(object)   # VariantResult
    progress = Signal(int, int)     # step, total_steps
    finished_all = Signal()

    def __init__(self, mf: MediaFile, ffmpeg: str, encoder: str, preset: str,
                 variants: list[QualityVariant], metrics: list[str],
                 vmaf_available: bool, sample_dir: Path, run_id: int,
                 n_samples: int, sample_seconds: int) -> None:
        super().__init__()
        self.mf = mf
        self.ffmpeg = ffmpeg
        self.encoder = encoder
        self.preset = preset
        self.variants = variants
        self.metrics = metrics
        self.sample_dir = sample_dir  # bleibt nach run() erhalten (Vorschau!)
        self.run_id = run_id          # macht Dateinamen über mehrere Testläufe eindeutig
        self.vmaf_available = vmaf_available
        self.n_samples = n_samples
        self.sample_seconds = sample_seconds
        self._stop = False
        self._proc: subprocess.Popen | None = None

    def cancel(self) -> None:
        self._stop = True
        if self._proc and self._proc.poll() is None:
            self._proc.kill()

    def _run_ffmpeg(self, cmd: list[str]) -> tuple[int, str]:
        from applog import log_cmd
        log_cmd(cmd)
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, **subprocess_flags())
        _, stderr = self._proc.communicate()
        return self._proc.returncode, stderr or ""

    def run(self) -> None:
        points = _sample_points(self.mf.duration, self.n_samples)
        use_vmaf_pass = "vmaf" in self.metrics and self.vmaf_available
        # Encode + Metrik = 2 Schritte je Sample
        total = len(self.variants) * len(points) * 2
        step = 0
        tmp = self.sample_dir
        mid = _mid_index(len(points))
        preview_abs = points[mid]
        for v_idx, variant in enumerate(self.variants):
            if self._stop:
                return
            per_metric_scores: dict[str, list[float]] = {m: [] for m in self.metrics}
            sample_bytes = 0
            error = ""
            preview_path: Path | None = None
            samples: list[tuple[Path, float]] = []
            for i, start in enumerate(points):
                if self._stop:
                    return
                out = tmp / f"r{self.run_id}_v{v_idx}_s{i}.mkv"
                rc, stderr = self._run_ffmpeg(_encode_cmd(
                    self.mf, self.ffmpeg, self.encoder, self.preset,
                    variant, start, self.sample_seconds, out))
                step += 1
                self.progress.emit(step, total)
                if self._stop:
                    return
                if rc != 0:
                    error = stderr[-200:] or "encode failed"
                    step += 1  # Metrik-Schritt entfällt
                    self.progress.emit(step, total)
                    continue
                sample_bytes += out.stat().st_size
                samples.append((out, start))
                if i == mid:
                    preview_path = out
                json_log = tmp / f"r{self.run_id}_v{v_idx}_s{i}_metrics.json"
                rc, stderr = self._run_ffmpeg(_metric_cmd(
                    self.mf, self.ffmpeg, out, start, self.sample_seconds,
                    self.metrics, self.vmaf_available, json_log))
                step += 1
                self.progress.emit(step, total)
                if rc != 0:
                    error = stderr[-200:] or "metric failed"
                    continue
                sample_scores = _parse_metric_output(
                    stderr, json_log, self.metrics, use_vmaf_pass)
                if not sample_scores:
                    error = "score not found in ffmpeg output"
                    continue
                for key, val in sample_scores.items():
                    per_metric_scores[key].append(val)
            avg_scores = {k: sum(v) / len(v) for k, v in per_metric_scores.items() if v}
            if avg_scores:
                total_sample_s = len(points) * self.sample_seconds
                est = int(sample_bytes * (self.mf.duration or total_sample_s)
                          / total_sample_s)
                self.variant_done.emit(VariantResult(
                    variant, avg_scores, est,
                    preview_path=preview_path, preview_start_abs=preview_abs,
                    samples=samples))
            else:
                self.variant_done.emit(VariantResult(variant, {}, 0, error))
        self.finished_all.emit()


class _PreviewPlayerDialog(QDialog):
    """Einfacher Video-Player für ein encodiertes Testsample (Play/Pause,
    Zeitanzeige) — Muster: separates Dialog-Fenster wie CropPreviewDialog,
    hier mit echter Wiedergabe statt Einzelframe."""

    def __init__(self, path: Path, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 480)
        layout = QVBoxLayout(self)

        self._video = QVideoWidget()
        layout.addWidget(self._video, 1)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._player.errorOccurred.connect(self._on_error)

        ctrl = QHBoxLayout()
        self.btn_play = QPushButton(t("qc_play"))
        self.btn_play.clicked.connect(self._toggle_play)
        ctrl.addWidget(self.btn_play)
        self._lbl_status = QLabel("")
        ctrl.addWidget(self._lbl_status, 1)
        btn_close = QPushButton(t("btn_close_cancel"))
        btn_close.clicked.connect(self.close)
        ctrl.addWidget(btn_close)
        layout.addLayout(ctrl)

        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()

    def _toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_state_changed(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setText(t("qc_pause") if playing else t("qc_play"))

    def _on_error(self, _error, error_string: str) -> None:
        self._lbl_status.setText(f"{t('qc_error')}: {error_string}")

    def closeEvent(self, event) -> None:
        # setSource(QUrl()) statt nur stop(): auf Windows haelt der
        # Media-Backend sonst den Datei-Handle noch kurz offen, was das
        # spaetere Aufraeumen des Sample-Ordners (tmp_dir.cleanup()) mit
        # PermissionError scheitern laesst.
        self._player.stop()
        self._player.setSource(QUrl())
        super().closeEvent(event)


class _FrameGrabber(QThread):
    """Extrahiert je einen Frame für mehrere (Label, Pfad, Sekunde)-Einträge
    sequenziell im Hintergrund."""

    frame_ready = Signal(int, object, str)   # index, QPixmap|None, error
    finished_all = Signal()

    def __init__(self, ffmpeg: str, jobs: list[tuple[Path, float]]) -> None:
        super().__init__()
        self.ffmpeg = ffmpeg
        self.jobs = jobs

    def run(self) -> None:
        for idx, (path, t_abs) in enumerate(self.jobs):
            try:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    tmp = Path(f.name)
                cmd = [self.ffmpeg, "-hide_banner", "-nostats",
                       "-ss", f"{max(t_abs, 0):.2f}", "-i", str(path),
                       "-vframes", "1", "-y", str(tmp)]
                r = subprocess.run(cmd, capture_output=True, timeout=30,
                                   **subprocess_flags())
                if r.returncode != 0 or not tmp.exists():
                    self.frame_ready.emit(idx, None, "ffmpeg error")
                    continue
                pm = QPixmap(str(tmp))
                tmp.unlink(missing_ok=True)
                if pm.isNull():
                    self.frame_ready.emit(idx, None, "decode error")
                else:
                    self.frame_ready.emit(idx, pm, "")
            except Exception as e:  # noqa: BLE001
                self.frame_ready.emit(idx, None, str(e))
        self.finished_all.emit()


class _FrameCell(QLabel):
    """Ein Vergleichsbild mit kleiner, halbtransparenter Bildunterschrift,
    die unten auf dem Bild selbst liegt (statt eines separaten Titel-Labels
    darüber). Skaliert das gespeicherte Rohbild bei jedem Resize neu, damit
    ein maximiertes Fenster tatsächlich größere Vorschauen zeigt.
    Beim Hovern zeigt eine Lupe oben rechts einen Ausschnitt des Rohbilds
    um die Mauszeigerposition (relative Koordinaten, damit der Dialog alle
    Zellen bei derselben Bildposition synchron zoomen kann). Rechtsklick
    öffnet das aktuelle Bild in einem frei skalierbaren Fenster."""

    hovered = Signal(float, float)   # relative Position (0..1) im Bildinhalt
    left = Signal()

    def __init__(self, caption: str) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(240, 135)
        self.setStyleSheet("background: #1e1e1e; color: #aaa;")
        self.setMouseTracking(True)
        self._raw: QPixmap | None = None
        self._cap = QLabel(caption, self)
        self._cap.setStyleSheet(
            "background: rgba(0,0,0,170); color: white; padding: 2px 6px;"
            "font-size: 11px;")
        self._cap.adjustSize()
        self._mag = QLabel(self)
        self._mag.setStyleSheet("background: #000; border: 2px solid #4a90d9;")
        self._mag.hide()
        self._position_caption()

    def _position_caption(self) -> None:
        self._cap.setFixedWidth(self.width())
        self._cap.move(0, self.height() - self._cap.sizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._position_caption()
        if self._raw is not None:
            self._apply_scaled()
        super().resizeEvent(event)

    def set_loading(self) -> None:
        self._raw = None
        self.setText(t("qc_compare_loading"))
        self.hide_magnifier()

    def set_error(self, msg: str) -> None:
        self._raw = None
        self.setText(f"{t('qc_error')}: {msg}")
        self.hide_magnifier()

    def set_pixmap_raw(self, pm: QPixmap) -> None:
        self._raw = pm
        self._apply_scaled()

    def _apply_scaled(self) -> None:
        scaled = self._raw.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(scaled)

    def _image_rect(self):
        """Rect innerhalb des Widgets, in dem das (zentrierte) Pixmap
        tatsächlich gezeichnet wird — nötig, um Mausposition auf relative
        Bildkoordinaten abzubilden (AlignCenter lässt bei anderem
        Seitenverhältnis Ränder frei)."""
        pm = self.pixmap()
        if pm is None or pm.isNull():
            return None
        x0 = (self.width() - pm.width()) / 2
        y0 = (self.height() - pm.height()) / 2
        return x0, y0, pm.width(), pm.height()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        rect = self._image_rect()
        if rect is not None:
            x0, y0, w, h = rect
            pos = event.position()
            rx = (pos.x() - x0) / w if w else 0.0
            ry = (pos.y() - y0) / h if h else 0.0
            if 0.0 <= rx <= 1.0 and 0.0 <= ry <= 1.0:
                self.hovered.emit(rx, ry)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.left.emit()
        super().leaveEvent(event)

    def show_magnifier(self, rx: float, ry: float) -> None:
        if self._raw is None:
            return
        rx = min(max(rx, 0.0), 1.0)
        ry = min(max(ry, 0.0), 1.0)
        raw = self._raw
        crop = max(24, raw.width() // 10)
        crop = min(crop, raw.width(), raw.height())
        cx = int(rx * raw.width())
        cy = int(ry * raw.height())
        x0 = min(max(cx - crop // 2, 0), max(raw.width() - crop, 0))
        y0 = min(max(cy - crop // 2, 0), max(raw.height() - crop, 0))
        region = raw.copy(x0, y0, crop, crop)
        zoomed = region.scaled(200, 200, Qt.KeepAspectRatio, Qt.FastTransformation)
        self._mag.setPixmap(zoomed)
        self._mag.resize(zoomed.size())
        self._mag.move(self.width() - zoomed.width() - 4, 4)
        self._mag.show()
        self._mag.raise_()

    def hide_magnifier(self) -> None:
        self._mag.hide()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        if self._raw is None:
            return
        menu = QMenu(self)
        act = QAction(t("qc_compare_open_window"), self)
        act.triggered.connect(self._open_in_window)
        menu.addAction(act)
        menu.exec(event.globalPos())

    def _open_in_window(self) -> None:
        if self._raw is None:
            return
        dlg = _FrameWindow(self._raw, self._cap.text(), self.window())
        dlg.show()


class _FrameWindow(QDialog):
    """Frei skalierbares Fenster für ein einzelnes Vergleichsbild in voller
    Auflösung (Rechtsklick auf eine Vergleichszelle) — für den Fall, dass
    die synchronisierte Lupe nicht reicht und man frei zoomen/das Fenster
    neben ein anderes Programm legen will."""

    def __init__(self, pm: QPixmap, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint
                            | Qt.WindowMinimizeButtonHint)
        self._raw = pm
        self.resize(min(pm.width(), 1000), min(pm.height(), 750))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("background: #1e1e1e;")
        layout.addWidget(self._label)
        self._apply_scaled()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._apply_scaled()
        super().resizeEvent(event)

    def _apply_scaled(self) -> None:
        scaled = self._raw.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._label.setPixmap(scaled)


class _FrameCompareDialog(QDialog):
    """Zeigt Einzelbilder mehrerer ausgewählter Ergebniszeilen bei einem per
    Schieberegler wählbaren Zeitpunkt nebeneinander."""

    def __init__(self, ffmpeg: str, entries: list[tuple[str, Path, bool, float]],
                 history: list[tuple[str, Path, bool, float]],
                 sample_seconds: int,
                 samples_per_entry: list[list[tuple[Path, float]]] | None = None,
                 parent: QWidget | None = None) -> None:
        """entries: initiale Auswahl je Zelle (label, path, is_source,
        preview_start_abs) — bestimmt Zellenanzahl + Vorauswahl.
        history: ALLE in dieser Dialog-Session je getesteten Clips (über
        mehrere Testläufe hinweg, nicht nur der aktuell sichtbaren Tabelle) —
        füllt das Dropdown jeder Zelle, damit auch Clips aus vorherigen
        Einstellungen verglichen werden können.
        samples_per_entry: je Zelle alle getesteten Sample-Zeitpunkte
        (Pfad, Startzeit) derselben Variante — füllt das globale
        "Sample"-Dropdown, mit dem sich (unabhängig vom Clip-Dropdown je
        Zelle) zwischen den z. B. 3 Messpunkten (20/50/80 % der Laufzeit)
        umschalten lässt.

        is_source=True (Referenzzeile, komplette Quelldatei): die gewählte
        "Sekunde im Sample" wird zu preview_start_abs addiert, um denselben
        Zeitpunkt im Original zu treffen.
        is_source=False (encodiertes Sample-Clip, nur wenige Sekunden lang):
        die Sekunde wird DIREKT als lokale Zeit im Clip verwendet (0 =
        Clip-Anfang) — preview_start_abs NICHT addieren, sonst seekt ffmpeg
        weit hinter das Ende der kurzen Datei ("decode error")."""
        super().__init__(parent)
        # Maximieren-Button ergänzen (QDialog hat ihn standardmäßig nicht)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint
                            | Qt.WindowMinimizeButtonHint)
        self.ffmpeg = ffmpeg
        self.entries = list(entries)  # pro Zelle aktuell gewählter Clip
        self.history = history
        self._samples_per_cell: list[list[tuple[Path, float]]] = (
            [list(s) for s in samples_per_entry] if samples_per_entry
            else [[] for _ in entries])
        self._grabber: _FrameGrabber | None = None
        self.setWindowTitle(t("qc_compare_title"))
        self.resize(900, 700)
        layout = QVBoxLayout(self)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel(t("qc_compare_time")))
        self.sld_time = QSlider(Qt.Horizontal)
        self.sld_time.setRange(0, max(sample_seconds, 1) * 10)  # 0.1s Schritte
        self.sld_time.setValue(int(sample_seconds / 2 * 10))
        self.sld_time.valueChanged.connect(self._on_slider_moved)
        self.sld_time.sliderReleased.connect(self._refresh)
        ctrl.addWidget(self.sld_time, 1)
        self.lbl_time = QLabel("")
        self.lbl_time.setFixedWidth(48)
        ctrl.addWidget(self.lbl_time)
        n_max = max((len(s) for s in self._samples_per_cell), default=0)
        ctrl.addWidget(QLabel(t("qc_compare_sample")))
        self.cmb_sample = QComboBox()
        self.cmb_sample.setToolTip(t("qc_compare_sample_select"))
        for i in range(n_max):
            self.cmb_sample.addItem(t("qc_compare_sample_n", n=i + 1), i)
        self.cmb_sample.setCurrentIndex(_mid_index(n_max) if n_max else -1)
        self.cmb_sample.setEnabled(n_max > 0)
        self.cmb_sample.currentIndexChanged.connect(self._on_sample_changed)
        ctrl.addWidget(self.cmb_sample)
        btn_refresh = QPushButton(t("qc_compare_refresh"))
        btn_refresh.clicked.connect(self._refresh)
        ctrl.addWidget(btn_refresh)
        layout.addLayout(ctrl)
        self._on_slider_moved(self.sld_time.value())

        self._grid = QGridLayout()
        self._grid.setAlignment(Qt.AlignTop)
        grid_holder = QWidget()
        grid_holder.setLayout(self._grid)
        layout.addWidget(grid_holder, 1)

        self._cells: list[_FrameCell] = []
        self._combos: list[QComboBox] = []
        cols = 2 if len(entries) > 1 else 1
        for i, (label, path, _is_src, _abs) in enumerate(entries):
            col_layout = QVBoxLayout()
            combo = QComboBox()
            combo.setToolTip(t("qc_compare_clip_select"))
            for h_label, h_path, h_is_src, h_abs in history:
                combo.addItem(h_label, (h_path, h_is_src, h_abs))
            idx = combo.findData((path, _is_src, _abs))
            if idx < 0:
                idx = max(combo.findText(label), 0)
            combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(
                lambda _idx, i=i: self._on_clip_changed(i))
            self._combos.append(combo)
            col_layout.addWidget(combo)
            cell = _FrameCell(label)
            cell.hovered.connect(self._on_cell_hovered)
            cell.left.connect(self._on_cell_left)
            self._cells.append(cell)
            col_layout.addWidget(cell, 1)
            col_widget = QWidget()
            col_widget.setLayout(col_layout)
            self._grid.addWidget(col_widget, i // cols, i % cols)

        self._refresh()

    def _on_slider_moved(self, raw: int) -> None:
        self.lbl_time.setText(f"{raw / 10:.1f} s")

    def _on_clip_changed(self, cell_idx: int) -> None:
        data = self._combos[cell_idx].currentData()
        if data is None:
            return
        path, is_source, start_abs = data
        label = self._combos[cell_idx].currentText()
        self.entries[cell_idx] = (label, path, is_source, start_abs)
        # Andere Historien-Clips kennen wir nur mit ihrem einen gespeicherten
        # Zeitpunkt — das Sample-Dropdown hat für diese Zelle bis zur
        # nächsten Auswahl über das Clip-Dropdown also nur einen Eintrag.
        self._samples_per_cell[cell_idx] = [(path, start_abs)]
        self._refresh_one(cell_idx)

    def _on_cell_hovered(self, rx: float, ry: float) -> None:
        for cell in self._cells:
            cell.show_magnifier(rx, ry)

    def _on_cell_left(self) -> None:
        for cell in self._cells:
            cell.hide_magnifier()

    def _on_sample_changed(self, _idx: int) -> None:
        sample_idx = self.cmb_sample.currentData()
        if sample_idx is None:
            return
        for i, samples in enumerate(self._samples_per_cell):
            if not samples:
                continue
            si = min(sample_idx, len(samples) - 1)
            path, start_abs = samples[si]
            label, _old_path, is_source, _old_abs = self.entries[i]
            self.entries[i] = (label, path, is_source, start_abs)
        self._refresh()

    def _refresh(self) -> None:
        if self._grabber and self._grabber.isRunning():
            return
        t_local = self.sld_time.value() / 10.0
        jobs = []
        for _label, path, is_source, start_abs in self.entries:
            t_abs = (start_abs + t_local) if is_source else t_local
            jobs.append((path, t_abs))
        for cell in self._cells:
            cell.set_loading()
        self._grabber = _FrameGrabber(self.ffmpeg, jobs)
        self._grabber.frame_ready.connect(self._on_frame_ready)
        self._grabber.start()

    def _refresh_one(self, cell_idx: int) -> None:
        """Nur eine Zelle neu laden (nach Dropdown-Wechsel), ohne auf einen
        eventuell noch laufenden Gesamt-Refresh zu warten."""
        t_local = self.sld_time.value() / 10.0
        _label, path, is_source, start_abs = self.entries[cell_idx]
        t_abs = (start_abs + t_local) if is_source else t_local
        self._cells[cell_idx].set_loading()
        grabber = _FrameGrabber(self.ffmpeg, [(path, t_abs)])
        grabber.frame_ready.connect(
            lambda _idx, pm, err, i=cell_idx: self._on_frame_ready(i, pm, err))
        grabber.finished_all.connect(grabber.deleteLater)
        self._single_grabbers = getattr(self, "_single_grabbers", [])
        self._single_grabbers.append(grabber)
        grabber.start()

    def closeEvent(self, event) -> None:
        # Noch laufende Grabber-Threads MÜSSEN vor dem Schließen beendet
        # sein — ein QThread, der beim Zerstören noch läuft, führt zu
        # "QThread: Destroyed while thread is still running" und reißt
        # den kompletten Prozess per SIGABRT ab (auch alle anderen
        # laufenden Encodes). Die ffmpeg-Frame-Grabs sind kurz, ein
        # blockierendes wait() hier ist unkritisch.
        if self._grabber is not None:
            self._grabber.wait()
        for g in getattr(self, "_single_grabbers", []):
            g.wait()
        super().closeEvent(event)

    def _on_frame_ready(self, idx: int, pm: QPixmap | None, error: str) -> None:
        cell = self._cells[idx]
        if pm is None:
            cell.set_error(error)
        else:
            cell.set_pixmap_raw(pm)


class QualityCheckDialog(QDialog):
    """Varianten-Matrix + Metriken wählen, Samples testen, Ergebnis übernehmen."""

    settings_applied = Signal(object)   # QualityVariant

    def __init__(self, mf: MediaFile, ffmpeg: str, encoder: str, preset: str,
                 current_crf: int, current_tune: str,
                 parent: QWidget | None = None, ffprobe: str = "") -> None:
        super().__init__(parent)
        self.mf = mf
        self.ffmpeg = ffmpeg
        # Fallback nur falls der Aufrufer ffprobe nicht mitgibt: Dateiname
        # in ffmpeg-Pfad ersetzen (liegt praktisch immer im selben Ordner).
        self.ffprobe = ffprobe or ffmpeg.replace("ffmpeg", "ffprobe")
        self.encoder = encoder
        self.preset = preset
        self._worker: QualityCheckWorker | None = None
        self._vmaf_available = has_vmaf(ffmpeg)
        self._metric_cols: list[str] = []  # wird bei _start() befüllt (Spaltenreihenfolge)
        # Sample-Dateien bleiben absichtlich bis zum Schließen des Dialogs
        # erhalten (Vorschau-Wiedergabe je Ergebniszeile) statt sofort nach
        # der Metrik-Berechnung gelöscht zu werden.
        self._tmp_dir = tempfile.TemporaryDirectory(prefix="handpack_qc_")
        self._run_id = 0
        self._preview_player: _PreviewPlayerDialog | None = None
        self._compare_dialog: _FrameCompareDialog | None = None
        self._last_sample_seconds = DEFAULT_SAMPLE_SECONDS
        # Sammelt Clips über ALLE Testläufe dieser Dialog-Session hinweg
        # (label, path, is_source, preview_start_abs) – die Tabelle selbst
        # wird bei jedem neuen Testlauf geleert, alte Sample-Dateien bleiben
        # aber bis zum Schließen des Dialogs erhalten und sollen im
        # Frame-Vergleich weiterhin auswählbar sein ("vorherige Einstellung").
        self._clip_history: list[tuple[str, Path, bool, float]] = []

        self.setWindowTitle(t("qc_title", name=mf.path.name))
        self.resize(820, 640)
        layout = QVBoxLayout(self)

        info = f"<b>{t('qc_encoder')}:</b> {encoder} / {preset}"
        info += f"<br><i>{t('qc_video_only')}</i>"
        info += f"<br><i>{t('qc_dblclick_hint')}</i>"
        lbl_info = QLabel(info)
        lbl_info.setWordWrap(True)
        layout.addWidget(lbl_info)

        # --- Metrik-Auswahl ---
        metric_row = QHBoxLayout()
        metric_row.addWidget(QLabel(f"<b>{t('qc_metrics')}:</b>"))
        self._metric_checks: list[tuple[str, QCheckBox]] = []
        for key, label, _dec in AVAILABLE_METRICS:
            cb = QCheckBox(label)
            tip = t(f"qc_metric_tip_{key}")
            if key == "vmaf":
                cb.setChecked(self._vmaf_available)
                cb.setEnabled(self._vmaf_available)
                if not self._vmaf_available:
                    tip += "\n\n" + t("qc_vmaf_missing")
            else:
                cb.setChecked(not self._vmaf_available and key == "ssim")
            cb.setToolTip(tip)
            self._metric_checks.append((key, cb))
            metric_row.addWidget(cb)
        metric_row.addStretch(1)
        layout.addLayout(metric_row)
        self.lbl_metric_warn = QLabel("")
        self.lbl_metric_warn.setWordWrap(True)
        self.lbl_metric_warn.setVisible(False)  # nimmt sonst auch leer Platz ein
        layout.addWidget(self.lbl_metric_warn)

        # --- Varianten-Matrix (inkl. Sample-Einstellungen) ---
        grp = QGroupBox(t("qc_variants"))
        grp_l = QVBoxLayout(grp)

        sample_row = QHBoxLayout()
        sample_row.addWidget(QLabel(t("qc_samples_label")))
        self.spn_samples = QSpinBox()
        self.spn_samples.setRange(MIN_SAMPLES, MAX_SAMPLES)
        self.spn_samples.setValue(DEFAULT_SAMPLES)
        self.spn_samples.valueChanged.connect(self._update_count)
        sample_row.addWidget(self.spn_samples)
        sample_row.addWidget(QLabel(t("qc_sample_secs_label")))
        self.spn_sample_secs = QSpinBox()
        self.spn_sample_secs.setRange(MIN_SAMPLE_SECONDS, MAX_SAMPLE_SECONDS)
        self.spn_sample_secs.setValue(DEFAULT_SAMPLE_SECONDS)
        self.spn_sample_secs.setSuffix(" s")
        self.spn_sample_secs.valueChanged.connect(self._update_count)
        sample_row.addWidget(self.spn_sample_secs)
        sample_row.addStretch(1)
        grp_l.addLayout(sample_row)

        res_row = QHBoxLayout()
        res_row.addWidget(QLabel(t("qc_resolutions")))
        self._res_checks: list[QCheckBox] = []
        src_h = mf.effective_source_rect()[1]
        for name, size in TARGET_RESOLUTIONS.items():
            if size is not None and size[1] > src_h:
                continue  # kein Upscaling anbieten
            cb = QCheckBox(name)
            cb.setChecked(name == TARGET_ORIGINAL)
            cb.toggled.connect(self._update_count)
            self._res_checks.append(cb)
            res_row.addWidget(cb)
        res_row.addStretch(1)
        grp_l.addLayout(res_row)

        crf_row = QHBoxLayout()
        crf_row.addWidget(QLabel(t("qc_crfs")))
        self.edt_crfs = QLineEdit(
            f"{max(current_crf - 2, 0)},{current_crf},{current_crf + 2}")
        self.edt_crfs.textChanged.connect(self._update_count)
        crf_row.addWidget(self.edt_crfs, 1)
        grp_l.addLayout(crf_row)

        tune_row = QHBoxLayout()
        tune_row.addWidget(QLabel(t("qc_tunes")))
        self._tune_checks: list[tuple[str, QCheckBox]] = []
        for key, label in TUNE_PROFILES.items():
            cb = QCheckBox(label)
            cb.setChecked(key == (current_tune or "none"))
            cb.toggled.connect(self._update_count)
            self._tune_checks.append((key, cb))
            tune_row.addWidget(cb)
        tune_row.addStretch(1)
        grp_l.addLayout(tune_row)
        # Tune wirkt nur bei libx265 (analog zur Toolbar)
        if encoder != "libx265":
            for _key, cb in self._tune_checks:
                cb.setEnabled(False)

        self.chk_test_mono = QCheckBox(t("qc_test_monochrome"))
        self.chk_test_mono.setChecked(mf.monochrome)
        self.chk_test_mono.setToolTip(t("qc_test_monochrome_tt"))
        self.chk_test_mono.toggled.connect(self._update_count)
        if encoder != "libx265":
            self.chk_test_mono.setEnabled(False)
        grp_l.addWidget(self.chk_test_mono)

        self.lbl_count = QLabel("")
        grp_l.addWidget(self.lbl_count)
        layout.addWidget(grp)

        # --- Ergebnistabelle (Spalten für Metriken kommen dynamisch bei _start) ---
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [t("qc_col_variant"), t("qc_col_size"), t("qc_col_pct")])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.itemDoubleClicked.connect(self._on_row_double_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)
        layout.addWidget(self.table, 1)

        lbl_pareto = QLabel(t("qc_pareto_hint"))
        lbl_pareto.setWordWrap(True)
        layout.addWidget(lbl_pareto)

        self.pb = QProgressBar()
        self.pb.setVisible(False)
        layout.addWidget(self.pb)

        btn_row = QHBoxLayout()
        self.btn_start = QPushButton(t("qc_start"))
        self.btn_start.clicked.connect(self._start)
        self.btn_compare = QPushButton(t("qc_compare_btn"))
        self.btn_compare.setEnabled(False)
        self.btn_compare.clicked.connect(self._open_compare)
        self.btn_apply = QPushButton(t("qc_apply"))
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply)
        btn_close = QPushButton(t("btn_close_cancel"))
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_compare)
        btn_row.addWidget(self.btn_apply)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self.table.itemSelectionChanged.connect(self._selection_changed)
        # Signale erst jetzt verbinden (UI vollständig aufgebaut): setChecked()
        # oben könnte sonst synchron toggled auslösen, bevor _res_checks/
        # edt_crfs/_tune_checks existieren, auf die _update_count zugreift.
        for _key, cb in self._metric_checks:
            cb.toggled.connect(self._on_metric_toggled)
        self._on_metric_toggled()  # initiale Warnung/Zustand setzen
        self._update_count()

    # ------------------------------------------------------------ Helpers

    def _fmt_size(self, size: int) -> str:
        if size >= 1024**3:
            return f"{size / 1024**3:.2f} GB"
        return f"{size / 1024**2:.0f} MB"

    def _selected_metrics(self) -> list[str]:
        return [key for key, cb in self._metric_checks if cb.isChecked() and cb.isEnabled()]

    def _on_metric_toggled(self, *_args) -> None:
        metrics = self._selected_metrics()
        self.lbl_metric_warn.setText("" if metrics else t("qc_no_metric"))
        self.lbl_metric_warn.setVisible(not metrics)
        self.btn_start.setEnabled(bool(metrics) and len(self._build_variants()) > 0
                                  and self._worker is None)

    def _metric_label(self, key: str) -> str:
        for k, label, _dec in AVAILABLE_METRICS:
            if k == key:
                return label
        return key

    def _metric_decimals(self, key: str) -> int:
        for k, _label, dec in AVAILABLE_METRICS:
            if k == key:
                return dec
        return 2

    def _rebuild_table_columns(self, metrics: list[str]) -> None:
        """Score-Spalten (eine je gewählter Metrik) zwischen Variante und
        Größe einfügen. Wird nur bei _start() aufgerufen (Auswahl danach
        eingefroren, bis der nächste Testlauf startet). Sortierung bleibt
        während des GESAMTEN Tabellenaufbaus (bis Ende von _start()) aus,
        da QTableWidget bei aktivierter Sortierung schon bei einzelnen
        setItem()-Aufrufen mitten im Zeilenaufbau resortiert und so Werte
        in falsche Zeilen schreibt."""
        self._metric_cols = metrics
        headers = [t("qc_col_variant")] + [self._metric_label(m) for m in metrics] \
            + [t("qc_col_size"), t("qc_col_pct")]
        self.table.setSortingEnabled(False)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setStretchLastSection(True)

    def _size_col(self) -> int:
        return 1 + len(self._metric_cols)

    def _pct_col(self) -> int:
        return 2 + len(self._metric_cols)

    def _set_row_preview_data(self, row: int, path: Path | None,
                              start_abs: float | None, is_source: bool,
                              samples: list[tuple[Path, float]] | None = None) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        item.setData(ROLE_PREVIEW_PATH, str(path) if path else None)
        item.setData(ROLE_PREVIEW_ABS, start_abs)
        item.setData(ROLE_IS_SOURCE, is_source)
        item.setData(ROLE_SAMPLES,
                    [(str(p), s) for p, s in samples] if samples else None)

    def _add_reference_row(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        item0 = QTableWidgetItem(t("qc_original"))
        item0.setData(Qt.UserRole, None)   # Referenz: kein Variant
        self.table.setItem(row, 0, item0)
        for i, m in enumerate(self._metric_cols):
            ref_val = 1.0 if m == "ssim" else 100.0
            dec = self._metric_decimals(m)
            self.table.setItem(row, 1 + i,
                               NumericTableWidgetItem(f"{ref_val:.{dec}f}", ref_val))
        size = self.mf.path.stat().st_size if self.mf.path.exists() else 0
        self.table.setItem(row, self._size_col(),
                           NumericTableWidgetItem(self._fmt_size(size), size))
        self.table.setItem(row, self._pct_col(), NumericTableWidgetItem("100 %", 100.0))
        # Referenzzeile: "Sekunde im Sample" bezieht sich auf denselben
        # Zeitfensterstart wie bei den Varianten (mittlerer Messpunkt).
        points = _sample_points(self.mf.duration, self.spn_samples.value())
        preview_abs = points[_mid_index(len(points))]
        self._set_row_preview_data(row, self.mf.path, preview_abs, is_source=True,
                                   samples=[(self.mf.path, p) for p in points])
        # Referenz-Eintrag in der Clip-Historie aktuell halten (überschreiben
        # statt duplizieren – es gibt immer nur EIN Original).
        self._clip_history = [h for h in self._clip_history if not h[2]]
        self._clip_history.insert(
            0, (t("qc_original"), self.mf.path, True, preview_abs))

    def _parse_crfs(self) -> list[int]:
        out: list[int] = []
        for part in self.edt_crfs.text().split(","):
            part = part.strip()
            if part.isdigit() and 0 <= int(part) <= 51:
                out.append(int(part))
        return sorted(set(out))

    def _build_variants(self) -> list[QualityVariant]:
        resolutions = [cb.text() for cb in self._res_checks if cb.isChecked()]
        crfs = self._parse_crfs()
        tunes = [key for key, cb in self._tune_checks
                 if cb.isChecked() and cb.isEnabled()] or ["none"]
        # Monochrome ist wie im Hauptfenster unabhängig vom Content-Tune
        # kombinierbar - bei aktivierter Checkbox wird JEDE Kombination
        # zusätzlich als S/W-Variante mitgetestet (verdoppelt die Matrix).
        mono_options = [False, True] if (self.chk_test_mono.isChecked()
                                         and self.chk_test_mono.isEnabled()) else [False]
        return [QualityVariant(r, c, tu, mono)
                for r in resolutions for c in crfs for tu in tunes for mono in mono_options]

    def _update_count(self) -> None:
        n = len(self._build_variants())
        self.lbl_count.setText(
            t("qc_count", n=n, samples=self.spn_samples.value(),
              secs=self.spn_sample_secs.value()))
        self._on_metric_toggled()

    # ------------------------------------------------------------ Ablauf

    def _start(self) -> None:
        variants = self._build_variants()
        metrics = self._selected_metrics()
        if not variants or not metrics:
            return
        self.btn_start.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.spn_samples.setEnabled(False)
        self.spn_sample_secs.setEnabled(False)
        for _key, cb in self._metric_checks:
            cb.setEnabled(False)  # Auswahl für diesen Lauf einfrieren

        self._rebuild_table_columns(metrics)  # setzt Sortierung aus
        self.table.setRowCount(0)
        self._add_reference_row()
        for v in variants:
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(v.label())
            item.setData(Qt.UserRole, v)
            self.table.setItem(row, 0, item)
            for col in range(1, self.table.columnCount()):
                self.table.setItem(row, col, NumericTableWidgetItem("…", -1.0))
        # Variant-Spalte an die (jetzt bekannten, meist recht langen)
        # Label-Texte anpassen — sonst bleibt sie auf der schmalen Breite
        # aus der Setup-Phase stehen und der Text wird abgeschnitten/
        # überlappend dargestellt.
        self.table.resizeColumnToContents(0)
        # Sortierung erst jetzt wieder erlauben — der GESAMTE Zeilenaufbau
        # (Referenz + alle Platzhalter) ist an dieser Stelle abgeschlossen.
        self.table.setSortingEnabled(True)
        self.pb.setVisible(True)
        self.pb.setValue(0)

        self._last_sample_seconds = self.spn_sample_secs.value()
        self._run_id += 1
        self._worker = QualityCheckWorker(
            self.mf, self.ffmpeg, self.encoder, self.preset,
            variants, metrics, self._vmaf_available,
            Path(self._tmp_dir.name), self._run_id,
            self.spn_samples.value(), self.spn_sample_secs.value())
        self._worker.variant_done.connect(self._on_variant_done)
        self._worker.progress.connect(
            lambda cur, tot: (self.pb.setMaximum(tot), self.pb.setValue(cur)))
        self._worker.finished_all.connect(self._on_finished)
        self._worker.start()

    def _on_variant_done(self, res: VariantResult) -> None:
        self.table.setSortingEnabled(False)
        # Nicht "range(1, ...)": die Referenzzeile steht nur direkt nach dem
        # Aufbau an Index 0 – sobald zwischen zwei Ergebnissen sortiert wird
        # (Sortierung bleibt während des Laufs aktiv, wegen der Pareto-★-
        # Markierung/Nutzersortierung), kann JEDE Zeile an Index 0 landen,
        # inkl. einer noch unfertigen Varianten-Zeile (Platzhalterwert -1.0
        # sortiert oft ganz nach oben). Die wurde dann dauerhaft übersprungen
        # und nie mehr aktualisiert. Der UserRole-Vergleich schließt die
        # Referenzzeile (UserRole=None) ohnehin sicher aus.
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == res.variant:
                if not res.scores:
                    err_text = f"{t('qc_error')}: {res.error[:60]}"
                    self.table.setItem(row, 1, NumericTableWidgetItem(err_text, -1.0))
                    for col in range(2, self.table.columnCount()):
                        self.table.setItem(row, col, NumericTableWidgetItem("–", -1.0))
                else:
                    for i, m in enumerate(self._metric_cols):
                        val = res.scores.get(m)
                        dec = self._metric_decimals(m)
                        text = f"{val:.{dec}f}" if val is not None else "–"
                        self.table.setItem(row, 1 + i,
                                           NumericTableWidgetItem(text, val if val is not None else -1.0))
                    self.table.setItem(
                        row, self._size_col(),
                        NumericTableWidgetItem(self._fmt_size(res.est_bytes), res.est_bytes))
                    src = self.mf.path.stat().st_size if self.mf.path.exists() else 0
                    pct_val = 100 * res.est_bytes / src if src else -1.0
                    pct = f"{pct_val:.0f} %" if src else "–"
                    self.table.setItem(row, self._pct_col(), NumericTableWidgetItem(pct, pct_val))
                    self._set_row_preview_data(
                        row, res.preview_path, res.preview_start_abs, is_source=False,
                        samples=res.samples)
                    self._add_to_clip_history(
                        res.variant.label(), res.preview_path, res.preview_start_abs)
                break
        self.table.setSortingEnabled(True)

    def _add_to_clip_history(self, label: str, path: Path | None, start_abs: float | None) -> None:
        """Fügt ein erfolgreiches Ergebnis der Session-weiten Clip-Historie
        hinzu (für "vorherige Einstellung" im Frame-Vergleich). Bei
        wiederholt gleicher Bezeichnung (z. B. identische Variante erneut
        getestet) wird die Lauf-Nummer angehängt, damit beide auswählbar
        bleiben statt sich im Dropdown zu verdecken."""
        if path is None or start_abs is None:
            return
        base_label = label
        n = sum(1 for l, *_ in self._clip_history if l == base_label or
               l.startswith(base_label + " ("))
        final_label = base_label if n == 0 else f"{base_label} ({t('qc_run_n', n=n + 1)})"
        self._clip_history.append((final_label, path, False, start_abs))

    def _on_finished(self) -> None:
        self._worker = None
        self.spn_samples.setEnabled(True)
        self.spn_sample_secs.setEnabled(True)
        for _key, cb in self._metric_checks:
            if _key != "vmaf" or self._vmaf_available:
                cb.setEnabled(True)
        self.pb.setVisible(False)
        self._mark_pareto_optimal()
        self._update_count()
        self._selection_changed()

    def _mark_pareto_optimal(self) -> None:
        """Markiert Varianten-Zeilen, die von keiner anderen Zeile (inkl. der
        Referenz!) sowohl in Größe als auch in der primären (ersten
        gewählten) Metrik dominiert werden — die einzig sinnvolle Antwort
        auf "Score pro MB", da die Rate-Distortion-Kurve nicht linear ist
        (siehe Modul-Docstring). Die Referenzzeile selbst zählt als
        möglicher Dominator (das Original ist z. B. immer besser UND
        größer als ein Encode, der es nicht wert war), bekommt aber keinen
        eigenen Stern — "Original" ist keine anwendbare Encode-Einstellung."""
        if not self._metric_cols:
            return
        rows = []  # (row, score, size) – Referenzzeile inklusive
        for row in range(self.table.rowCount()):
            score_item = self.table.item(row, 1)
            size_item = self.table.item(row, self._size_col())
            if isinstance(score_item, NumericTableWidgetItem) and \
                    isinstance(size_item, NumericTableWidgetItem) and \
                    score_item._value >= 0 and size_item._value >= 0:
                rows.append((row, score_item._value, size_item._value))
        for row, score, size in rows:
            variant_item = self.table.item(row, 0)
            if variant_item is not None and variant_item.data(Qt.UserRole) is None:
                continue  # Referenzzeile selbst nie markieren (Zeilenindex ist
                          # nach Sortierung nicht mehr zuverlässig row 0)
            dominated = any(
                other_score >= score and other_size <= size and
                (other_score > score or other_size < size)
                for r2, other_score, other_size in rows if r2 != row
            )
            item = self.table.item(row, 0)
            if item:
                if not dominated:
                    item.setText("★ " + item.text().removeprefix("★ "))
                    item.setForeground(QColor("#1a7f37"))
                else:
                    item.setText(item.text().removeprefix("★ "))
                    item.setForeground(self.palette().text().color())

    def _selection_changed(self) -> None:
        variant = self._selected_variant()
        rows = self._selected_rows()
        self.btn_apply.setEnabled(self._worker is None and variant is not None)
        self.btn_compare.setEnabled(self._worker is None and len(rows) >= 1)

    def _selected_rows(self) -> list[int]:
        return sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})

    def _selected_variant(self) -> QualityVariant | None:
        items = self.table.selectedItems()
        if not items:
            return None
        return self.table.item(items[0].row(), 0).data(Qt.UserRole)

    def _apply(self) -> None:
        v = self._selected_variant()
        if v is not None:
            self.settings_applied.emit(v)
            self.accept()

    # ------------------------------------------------------------ Vorschau

    def _on_row_double_clicked(self, item: QTableWidgetItem) -> None:
        col0 = self.table.item(item.row(), 0)
        if col0 is None:
            return
        path_str = col0.data(ROLE_PREVIEW_PATH)
        if not path_str:
            return
        self._open_preview(Path(path_str))

    def _on_table_context_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        col0 = self.table.item(row, 0)
        path_str = col0.data(ROLE_PREVIEW_PATH) if col0 else None
        menu = QMenu(self)
        a_mi = QAction(t("ctx_media_info"), self)
        a_mi.setEnabled(bool(path_str))
        a_mi.triggered.connect(lambda: self._show_media_info(Path(path_str)))
        menu.addAction(a_mi)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _show_media_info(self, path: Path) -> None:
        from mediainfo import MediaInfoDialog
        if not path.exists():
            QMessageBox.warning(self, t("qc_error"), t("qc_preview_missing"))
            return
        MediaInfoDialog(path, self.ffprobe, self).exec()

    def _open_preview(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.warning(self, t("qc_error"), t("qc_preview_missing"))
            return
        # Vorherigen Player schließen, bevor ein neuer geöffnet wird
        if self._preview_player is not None:
            self._preview_player.close()
        self._preview_player = _PreviewPlayerDialog(
            path, t("qc_preview_title", name=path.name), self)
        self._preview_player.show()

    def _open_compare(self) -> None:
        entries: list[tuple[str, Path, bool, float]] = []
        samples_per_entry: list[list[tuple[Path, float]]] = []
        for row in self._selected_rows():
            col0 = self.table.item(row, 0)
            if col0 is None:
                continue
            path_str = col0.data(ROLE_PREVIEW_PATH)
            start_abs = col0.data(ROLE_PREVIEW_ABS)
            is_source = bool(col0.data(ROLE_IS_SOURCE))
            if not path_str or start_abs is None:
                continue
            label = col0.text().removeprefix("★ ")
            entries.append((label, Path(path_str), is_source, float(start_abs)))
            raw_samples = col0.data(ROLE_SAMPLES)
            samples_per_entry.append(
                [(Path(p), s) for p, s in raw_samples] if raw_samples else [])
        if not entries:
            QMessageBox.information(self, t("qc_error"), t("qc_preview_missing"))
            return
        if self._compare_dialog is not None:
            self._compare_dialog.close()
        self._compare_dialog = _FrameCompareDialog(
            self.ffmpeg, entries, self._clip_history, self._last_sample_seconds,
            samples_per_entry, self)
        self._compare_dialog.show()

    def done(self, result: int) -> None:
        # Läuft für Accept (Übernehmen) UND Reject (Abbrechen/X) gleichermaßen:
        # laufenden Test stoppen, Vorschau-Fenster schließen, Sample-Dateien
        # erst jetzt aufräumen (nicht schon während/direkt nach dem Testlauf).
        if self._worker:
            self._worker.cancel()
            self._worker.wait(3000)
            self._worker = None
        if self._preview_player is not None:
            self._preview_player.close()
            self._preview_player = None
        if self._compare_dialog is not None:
            self._compare_dialog.close()
            self._compare_dialog = None
        try:
            self._tmp_dir.cleanup()
        except OSError:
            # Windows kann eine Datei kurzzeitig noch sperren, wenn der
            # Media-Backend-Teardown asynchron etwas nachläuft. Kein
            # kritischer Fehler — landet nur im System-Temp-Ordner, den
            # das OS ohnehin regelmäßig aufräumt.
            pass
        super().done(result)
