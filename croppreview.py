"""Crop-Vorschau: extrahiert einen Frame per ffmpeg, zeigt das Crop-Overlay
und erlaubt das manuelle Festlegen der Ränder (links/rechts/oben/unten)."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from models import CropInfo, MediaFile
from settings import subprocess_flags


class _FrameLoader(QThread):
    loaded = Signal(object, float)   # QImage, timestamp
    failed = Signal(str)

    def __init__(self, path: Path, ffmpeg: str, t: float):
        super().__init__()
        self.path = path
        self.ffmpeg = ffmpeg
        self.t = t

    def run(self) -> None:
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                tmp = Path(f.name)
            cmd = [
                self.ffmpeg, "-hide_banner", "-nostats",
                "-ss", f"{self.t:.2f}", "-i", str(self.path),
                "-vframes", "1", "-y", str(tmp),
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=30,
                               **subprocess_flags())
            if r.returncode != 0 or not tmp.exists():
                self.failed.emit("Frame konnte nicht extrahiert werden")
                return
            img = QImage(str(tmp))
            tmp.unlink(missing_ok=True)
            if img.isNull():
                self.failed.emit("Bild konnte nicht geladen werden")
                return
            self.loaded.emit(img, self.t)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class _FrameView(QLabel):
    """Zeigt ein skaliertes Frame mit Crop-Overlay."""

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(640, 360)
        self._raw: QImage | None = None
        self._crop: CropInfo | None = None

    def set_image(self, img: QImage, crop: CropInfo | None) -> None:
        self._raw = img
        self._crop = crop
        self._refresh()

    def set_crop(self, crop: CropInfo | None) -> None:
        self._crop = crop
        self._refresh()

    def resizeEvent(self, event) -> None:
        self._refresh()
        super().resizeEvent(event)

    def _refresh(self) -> None:
        if self._raw is None:
            return
        img_w, img_h = self._raw.width(), self._raw.height()
        avail_w, avail_h = self.width(), self.height()

        scale = min(avail_w / img_w, avail_h / img_h)
        disp_w = int(img_w * scale)
        disp_h = int(img_h * scale)
        off_x = (avail_w - disp_w) // 2
        off_y = (avail_h - disp_h) // 2

        pm = QPixmap(avail_w, avail_h)
        pm.fill(QColor("#1e1e1e"))
        painter = QPainter(pm)
        scaled = QPixmap.fromImage(self._raw).scaled(
            disp_w, disp_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap(off_x, off_y, scaled)

        if self._crop and self._crop.valid:
            c = self._crop
            cx = off_x + int(c.x * scale)
            cy = off_y + int(c.y * scale)
            cw = int(c.w * scale)
            ch = int(c.h * scale)

            overlay = QPixmap(avail_w, avail_h)
            overlay.fill(Qt.transparent)
            op = QPainter(overlay)
            op.setOpacity(0.45)
            op.setBrush(QColor("black"))
            op.setPen(Qt.NoPen)
            op.drawRect(off_x, off_y, disp_w, cy - off_y)
            op.drawRect(off_x, cy + ch, disp_w, off_y + disp_h - cy - ch)
            op.drawRect(off_x, cy, cx - off_x, ch)
            op.drawRect(cx + cw, cy, off_x + disp_w - cx - cw, ch)
            op.end()
            painter.drawPixmap(0, 0, overlay)

            pen = QPen(QColor("#00e5ff"), 2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(cx, cy, cw, ch)

            painter.setPen(QColor("white"))
            painter.drawText(cx + 4, cy + 16,
                             f"{c.w}×{c.h}  offset {c.x},{c.y}")

        painter.end()
        self.setPixmap(pm)


class CropPreviewDialog(QDialog):
    """Zeigt einen Frame der Quelldatei mit Crop-Overlay.
    Ränder können manuell angepasst und auf die Datei angewendet werden."""

    crop_applied = Signal(object)   # CropInfo

    def __init__(self, mf: MediaFile, ffmpeg: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.mf = mf
        self.ffmpeg = ffmpeg
        self._loader: _FrameLoader | None = None
        self._src_w = mf.width or 0
        self._src_h = mf.height or 0

        self.setWindowTitle(f"Crop-Vorschau – {mf.path.name}")
        self.resize(1000, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._view = _FrameView()
        layout.addWidget(self._view)

        # --- Zeitslider ---
        ctrl = QHBoxLayout()
        self._lbl_time = QLabel("0 s")
        self._lbl_time.setFixedWidth(55)
        self._slider = QSlider(Qt.Horizontal)
        dur = int(mf.duration or 600)
        self._slider.setRange(0, dur)
        self._slider.setValue(dur // 2)
        self._slider.sliderReleased.connect(self._load_frame)
        ctrl.addWidget(QLabel("Zeit:"))
        ctrl.addWidget(self._slider)
        ctrl.addWidget(self._lbl_time)
        layout.addLayout(ctrl)

        # --- Manuelle Crop-Eingabe ---
        box = QGroupBox("Crop manuell festlegen  (Pixel vom Rand)")
        form_row = QHBoxLayout(box)
        form_row.setSpacing(16)

        def make_spin(label: str, max_val: int) -> QSpinBox:
            spn = QSpinBox()
            spn.setRange(0, max_val)
            spn.setSingleStep(2)
            spn.setSuffix(" px")
            spn.valueChanged.connect(self._on_spin_changed)
            fl = QFormLayout()
            fl.setContentsMargins(0, 0, 0, 0)
            fl.addRow(label, spn)
            form_row.addLayout(fl)
            return spn

        self._spn_left   = make_spin("Links:",  self._src_w // 2)
        self._spn_right  = make_spin("Rechts:", self._src_w // 2)
        self._spn_top    = make_spin("Oben:",   self._src_h // 2)
        self._spn_bottom = make_spin("Unten:",  self._src_h // 2)

        form_row.addStretch()
        self._lbl_result = QLabel("")
        form_row.addWidget(self._lbl_result)

        layout.addWidget(box)

        # --- Fußzeile ---
        foot = QHBoxLayout()
        self._lbl_status = QLabel("Lade Frame…")
        foot.addWidget(self._lbl_status, 1)

        btn_reset = QPushButton("Erkannten Crop wiederherstellen")
        btn_reset.clicked.connect(self._reset_to_detected)
        foot.addWidget(btn_reset)

        btn_apply = QPushButton("Übernehmen")
        btn_apply.setDefault(True)
        btn_apply.clicked.connect(self._apply)
        foot.addWidget(btn_apply)

        btn_close = QPushButton("Schließen")
        btn_close.clicked.connect(self.accept)
        foot.addWidget(btn_close)

        layout.addLayout(foot)

        # Spinboxen mit aktuellem Crop befüllen (blockSignals um Refresh zu vermeiden)
        self._populate_spins(mf.crop if mf.crop.valid else CropInfo())
        self._load_frame()

    # ------------------------------------------------------------------ Spins

    def _populate_spins(self, crop: CropInfo) -> None:
        for spn in (self._spn_left, self._spn_right,
                    self._spn_top, self._spn_bottom):
            spn.blockSignals(True)
        if crop.valid and self._src_w and self._src_h:
            self._spn_left.setValue(crop.x)
            self._spn_top.setValue(crop.y)
            self._spn_right.setValue(self._src_w - crop.x - crop.w)
            self._spn_bottom.setValue(self._src_h - crop.y - crop.h)
        else:
            for spn in (self._spn_left, self._spn_right,
                        self._spn_top, self._spn_bottom):
                spn.setValue(0)
        for spn in (self._spn_left, self._spn_right,
                    self._spn_top, self._spn_bottom):
            spn.blockSignals(False)
        self._on_spin_changed()

    def _current_crop(self) -> CropInfo:
        l = self._spn_left.value()
        r = self._spn_right.value()
        t = self._spn_top.value()
        b = self._spn_bottom.value()
        w = max(self._src_w - l - r, 2)
        h = max(self._src_h - t - b, 2)
        w -= w % 2
        h -= h % 2
        if w <= 0 or h <= 0:
            return CropInfo()
        return CropInfo(w=w, h=h, x=l, y=t)

    def _on_spin_changed(self) -> None:
        crop = self._current_crop()
        self._view.set_crop(crop if crop.valid else None)
        if crop.valid and self._src_w and self._src_h:
            self._lbl_result.setText(
                f"Ergebnis: {crop.w}×{crop.h}  (x={crop.x}, y={crop.y})")
        else:
            self._lbl_result.setText("Kein Crop")

    def _reset_to_detected(self) -> None:
        self._populate_spins(self.mf.crop if self.mf.crop.valid else CropInfo())

    def _apply(self) -> None:
        crop = self._current_crop()
        self.mf.crop = crop
        self.mf.crop_enabled = crop.valid
        self.crop_applied.emit(crop)
        self.accept()

    # ------------------------------------------------------------------ Frame

    def _load_frame(self) -> None:
        if self._loader and self._loader.isRunning():
            return
        t = self._slider.value()
        self._lbl_time.setText(f"{t} s")
        self._lbl_status.setText("Lade Frame…")
        self._loader = _FrameLoader(self.mf.path, self.ffmpeg, float(t))
        self._loader.loaded.connect(self._on_loaded)
        self._loader.failed.connect(self._on_failed)
        self._loader.start()

    def _on_loaded(self, img: QImage, t: float) -> None:
        crop = self._current_crop()
        self._view.set_image(img, crop if crop.valid else None)
        self._lbl_status.setText(f"Frame bei {t:.1f} s  –  "
                                 f"Quelle {self._src_w}×{self._src_h}")

    def _on_failed(self, msg: str) -> None:
        self._lbl_status.setText(f"Fehler: {msg}")
