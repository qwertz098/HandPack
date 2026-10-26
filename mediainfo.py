"""Medien-Info: Größenanteile von Video/Audio/Untertitel/Sonstigem an der
Gesamtdatei, per ffprobe ermittelt. Nutzt exakte MKV-Statistik-Tags
(NUMBER_OF_BYTES, von mkvmerge geschrieben) wenn vorhanden, sonst eine
Schätzung aus Bitrate × Dauer (wie bei der Audio-Bitrate-Anzeige)."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QSizePolicy, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from i18n import t
from settings import subprocess_flags

# Zyklische Farbpalette für die Segmente (Video/Audio.../Untertitel/Sonstiges)
_PALETTE = [
    "#3b82f6",  # Video – blau
    "#22c55e",  # Audio 1 – grün
    "#f59e0b",  # Audio 2 – orange
    "#a855f7",  # Audio 3 – violett
    "#ec4899",  # Audio 4 – pink
    "#14b8a6",  # weitere Audios – teal
]
_SUBTITLE_COLOR = "#94a3b8"   # grau-blau
_OTHER_COLOR = "#cbd5e1"      # hellgrau (Container-Overhead/nicht zugeordnet)


@dataclass
class StreamSizeEntry:
    label: str
    size_bytes: int
    pct: float            # 0..100 von Gesamtgröße
    estimated: bool        # True = aus Bitrate×Dauer geschätzt, nicht exakt
    color: str = "#888888"
    category: str = "other"   # "video" | "audio" | "subtitle" | "other"


@dataclass
class MediaInfoResult:
    path: Path
    container: str
    total_bytes: int
    duration: float
    entries: list[StreamSizeEntry] = field(default_factory=list)
    other_bytes: int = 0
    other_pct: float = 0.0


def analyze_media(path: Path, ffprobe: str) -> MediaInfoResult:
    cmd = [ffprobe, "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                       **subprocess_flags())
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe fehlgeschlagen: {r.stderr[:200]}")
    data = json.loads(r.stdout or "{}")

    fmt = data.get("format", {})
    total = int(fmt.get("size", 0) or 0) or (path.stat().st_size if path.exists() else 0)
    duration = float(fmt.get("duration", 0) or 0)
    container = fmt.get("format_long_name") or fmt.get("format_name") or "?"

    entries: list[StreamSizeEntry] = []
    accounted = 0
    audio_idx = 0
    color_idx = 0
    for s in data.get("streams", []):
        ctype = s.get("codec_type")
        tags = s.get("tags", {}) or {}
        if ctype == "video" and s.get("disposition", {}).get("attached_pic"):
            continue  # Cover-Art nicht als "Video" werten

        # 1) exakte Größe aus MKV-Statistik-Tag (mkvmerge), 2) Schätzung
        nbytes = tags.get("NUMBER_OF_BYTES") or tags.get("NUMBER_OF_BYTES-eng")
        size = 0
        estimated = False
        if nbytes:
            try:
                size = int(nbytes)
            except (TypeError, ValueError):
                size = 0
        if not size:
            br = s.get("bit_rate")
            bps_tag = tags.get("BPS") or tags.get("BPS-eng")
            rate = int(br) if br else (int(bps_tag) if bps_tag else 0)
            dur = float(s.get("duration", 0) or 0) or duration
            if rate and dur:
                size = int(rate * dur / 8)
                estimated = True

        if ctype == "video":
            label = t("mi_video_label", codec=s.get("codec_name", "?"),
                      w=s.get("width", "?"), h=s.get("height", "?"))
            color = _PALETTE[0]
        elif ctype == "audio":
            audio_idx += 1
            lang = f" {tags.get('language')}" if tags.get("language") else ""
            ch = s.get("channels", "")
            label = t("mi_audio_label", n=audio_idx, codec=s.get("codec_name", "?"),
                      lang=lang, ch=ch)
            color = _PALETTE[min(1 + (audio_idx - 1), len(_PALETTE) - 1)]
        elif ctype == "subtitle":
            label = t("mi_subtitle_label", codec=s.get("codec_name", "?"))
            color = _SUBTITLE_COLOR
        else:
            label = t("mi_other_stream_label", codec=s.get("codec_name", "?"))
            color = _OTHER_COLOR

        if size:
            accounted += size
        pct = (size / total * 100) if total else 0.0
        entries.append(StreamSizeEntry(label, size, pct, estimated, color,
                                       category=ctype if ctype in
                                       ("video", "audio", "subtitle") else "other"))

    other = max(total - accounted, 0)
    other_pct = (other / total * 100) if total else 0.0
    return MediaInfoResult(path, container, total, duration, entries, other, other_pct)


def category_totals(result: MediaInfoResult) -> list[tuple[str, int, float, str]]:
    """Aggregiert die Einzel-Streams zu Kategorie-Summen (Video/Audio/
    Untertitel/Sonstiges) — robuster als Track-für-Track-Vergleich, da
    Original und Ergebnis unterschiedlich viele Spuren haben können (z. B.
    abgewählte Audiospuren), aber die Kategorien immer vergleichbar sind.
    Rückgabe: (Label, Bytes, Prozent-von-Gesamt, Farbe)."""
    sums: dict[str, int] = {"video": 0, "audio": 0, "subtitle": 0, "other": 0}
    colors = {"video": _PALETTE[0], "audio": _PALETTE[1],
             "subtitle": _SUBTITLE_COLOR, "other": _OTHER_COLOR}
    counts: dict[str, int] = {"video": 0, "audio": 0, "subtitle": 0}
    for e in result.entries:
        sums[e.category] = sums.get(e.category, 0) + e.size_bytes
        if e.category in counts:
            counts[e.category] += 1
    sums["other"] += result.other_bytes

    rows: list[tuple[str, int, float, str]] = []
    for cat, key in (("video", "mi_cat_video"), ("audio", "mi_cat_audio"),
                     ("subtitle", "mi_cat_subtitle"), ("other", "mi_cat_other")):
        size = sums[cat]
        if size <= 0 and cat != "other":
            continue
        n = counts.get(cat, 0)
        label = t(key, n=n) if cat in ("audio", "subtitle") else t(key)
        pct = (size / result.total_bytes * 100) if result.total_bytes else 0.0
        rows.append((label, size, pct, colors[cat]))
    return rows


class _ProportionBar(QWidget):
    """Horizontaler Balken mit einem farbigen Segment je Stream + Rest."""

    def __init__(self, result: MediaInfoResult) -> None:
        super().__init__()
        self._result = result
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        x = 0.0
        segments = [(e.pct, e.color) for e in self._result.entries]
        segments.append((self._result.other_pct, _OTHER_COLOR))
        for pct, color in segments:
            seg_w = w * pct / 100.0
            if seg_w > 0:
                painter.fillRect(int(x), 0, int(seg_w) + 1, h, QColor(color))
            x += seg_w
        painter.end()


class MediaInfoDialog(QDialog):
    """Zeigt Größenanteile von Video/Audio/Untertitel/Sonstigem einer Datei.
    Wird zusätzlich `compare_path` übergeben (z. B. die fertige
    Ausgabedatei), zeigt die Tabelle stattdessen Original und Ergebnis
    kategorienweise nebeneinander (je Kategorie: absolute Größe UND
    Prozentanteil, für beide Dateien getrennt) statt der Einzel-Stream-
    Aufschlüsselung einer einzelnen Datei."""

    def __init__(self, path: Path, ffprobe: str, parent: QWidget | None = None,
                 compare_path: Path | None = None) -> None:
        super().__init__(parent)
        self.resize(680 if compare_path else 560, 420)
        layout = QVBoxLayout(self)

        try:
            result = analyze_media(path, ffprobe)
            compare = analyze_media(compare_path, ffprobe) if compare_path else None
        except Exception as e:  # noqa: BLE001
            self.setWindowTitle(t("mi_title", name=path.name))
            layout.addWidget(QLabel(f"{t('qc_error')}: {e}"))
            return

        def fmt_size(n: int) -> str:
            if n >= 1024**3:
                return f"{n / 1024**3:.2f} GB"
            return f"{n / 1024**2:.1f} MB"

        if compare is not None:
            self.setWindowTitle(t("mi_title_compare", name=path.name))
            info = QLabel(
                f"<b>{t('mi_original')}:</b> {fmt_size(result.total_bytes)}"
                f" &nbsp;→&nbsp; <b>{t('mi_result')}:</b> {fmt_size(compare.total_bytes)}"
                f" ({compare.total_bytes / result.total_bytes * 100:.0f} %)"
                if result.total_bytes else ""
            )
            info.setWordWrap(True)
            layout.addWidget(info)

            bars = QHBoxLayout()
            col_a = QVBoxLayout()
            col_a.addWidget(QLabel(f"<b>{t('mi_original')}</b>"))
            col_a.addWidget(_ProportionBar(result))
            col_b = QVBoxLayout()
            col_b.addWidget(QLabel(f"<b>{t('mi_result')}</b>"))
            col_b.addWidget(_ProportionBar(compare))
            bars.addLayout(col_a)
            bars.addLayout(col_b)
            layout.addLayout(bars)

            table = QTableWidget(0, 5)
            table.setHorizontalHeaderLabels([
                t("mi_col_stream"),
                t("mi_col_size") + f" ({t('mi_original')})",
                t("mi_col_pct") + f" ({t('mi_original')})",
                t("mi_col_size") + f" ({t('mi_result')})",
                t("mi_col_pct") + f" ({t('mi_result')})",
            ])
            table.horizontalHeader().setStretchLastSection(True)
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            layout.addWidget(table, 1)

            rows_a = {label: (size, pct, color) for label, size, pct, color
                     in category_totals(result)}
            rows_b = {label: (size, pct, color) for label, size, pct, color
                     in category_totals(compare)}
            for label in dict.fromkeys(list(rows_a) + list(rows_b)):  # Reihenfolge erhalten
                size_a, pct_a, color = rows_a.get(label, (0, 0.0, "#888888"))
                size_b, pct_b, _ = rows_b.get(label, (0, 0.0, color))
                row = table.rowCount()
                table.insertRow(row)
                label_item = QTableWidgetItem(label)
                label_item.setIcon(_color_icon(color))
                table.setItem(row, 0, label_item)
                table.setItem(row, 1, QTableWidgetItem(fmt_size(size_a) if size_a else "–"))
                table.setItem(row, 2, QTableWidgetItem(f"{pct_a:.1f} %" if size_a else "–"))
                table.setItem(row, 3, QTableWidgetItem(fmt_size(size_b) if size_b else "–"))
                table.setItem(row, 4, QTableWidgetItem(f"{pct_b:.1f} %" if size_b else "–"))

            hint = QLabel(t("mi_estimated_hint"))
            hint.setWordWrap(True)
            layout.addWidget(hint)
            return

        self.setWindowTitle(t("mi_title", name=path.name))
        info = QLabel(
            f"<b>{t('mi_container')}:</b> {result.container}<br>"
            f"<b>{t('mi_total_size')}:</b> {fmt_size(result.total_bytes)}"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addWidget(_ProportionBar(result))

        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(
            [t("mi_col_stream"), t("mi_col_size"), t("mi_col_pct")])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(table, 1)

        def add_row(label: str, size: int, pct: float, color: str, note: str = "") -> None:
            row = table.rowCount()
            table.insertRow(row)
            label_item = QTableWidgetItem(f"{label}{note}")
            label_item.setIcon(_color_icon(color))
            table.setItem(row, 0, label_item)
            table.setItem(row, 1, QTableWidgetItem(fmt_size(size)))
            table.setItem(row, 2, QTableWidgetItem(f"{pct:.1f} %"))

        for e in result.entries:
            note = f"  ({t('mi_estimated')})" if e.estimated else ""
            add_row(e.label, e.size_bytes, e.pct, e.color, note)
        if result.other_bytes:
            add_row(t("mi_other"), result.other_bytes, result.other_pct, _OTHER_COLOR)

        hint = QLabel(t("mi_estimated_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)


def _color_icon(color: str):
    from PySide6.QtGui import QIcon, QPixmap
    pm = QPixmap(12, 12)
    pm.fill(QColor(color))
    return QIcon(pm)
