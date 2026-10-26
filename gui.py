"""Hauptfenster: Einstellungsleiste, Drop-Area, Job-Tabelle, Steuerung."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThread, QThreadPool, QTimer, Signal
import time as _time
from PySide6.QtGui import QAction, QActionGroup, QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QTextBrowser,
    QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from encoders import ENCODER_LABELS, detect_encoders
from croppreview import CropPreviewDialog
from i18n import get_lang, set_lang, status_t, t
from jobs import AnalyzeWorker, CropOnlyWorker, EncodeWorker
from models import (AUDIO_BITRATES_KBPS, AUDIO_CHANNEL_OPTIONS, AUDIO_DRC_LEVELS,
                    AudioMode, CropInfo, SettingsCopyOptions, apply_settings,
                    default_audio_bitrate,
                    ENCODE_PRESETS, HDRType, JobStatus, MediaFile,
                    TARGET_RESOLUTIONS, TUNE_PROFILES, VideoMode)
from probe import collect_video_files
from settings import AppSettings


# Reihenfolge bewusst an die Toolbar angeglichen (Ziel/CRF/Encoder/Preset/
# Tune/Audio, s. _build_ui) - "global" und "pro Zeile" sollen dieselbe
# Einstellungsreihenfolge zeigen. Crop steht bei den Quell-Analyse-Spalten
# (Res/HDR), da es inhaltlich zur Analyse gehört statt zu den Encode-
# Einstellungen.
COL_ON, COL_FILE, COL_RES, COL_HDR, COL_CROP_ON, COL_CROP, COL_TARGET, \
    COL_CRF, COL_ENCODER, COL_PRESET, COL_TUNE, COL_MONO, COL_AUDIO, \
    COL_OUT, COL_STATUS = range(15)

HDR_COLORS = {
    HDRType.SDR: None,
    HDRType.HDR10: QColor(70, 110, 170),
    HDRType.HDR10PLUS: QColor(70, 130, 190),
    HDRType.HLG: QColor(90, 140, 90),
    HDRType.DOLBY_VISION: QColor(140, 80, 160),
}


class DropArea(QFrame):
    files_dropped = Signal(list)
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setFrameStyle(QFrame.StyledPanel)
        self.setMinimumHeight(56)
        self.setFixedWidth(230)
        self.setStyleSheet(
            "DropArea { border: 2px dashed #888; border-radius: 8px; }"
            "DropArea:hover { border-color: #4a90d9; }")
        lay = QVBoxLayout(self)
        self._hint_lbl = QLabel()
        self._hint_lbl.setAlignment(Qt.AlignCenter)
        self._hint_lbl.setWordWrap(True)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.addWidget(self._hint_lbl)
        self.setCursor(Qt.PointingHandCursor)

    def set_hint(self, text: str) -> None:
        self._hint_lbl.setText(text)

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls()
                 if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)

    def mousePressEvent(self, e) -> None:
        self.clicked.emit()


_AC3_CODECS = {"ac3", "eac3"}
_AAC_CODECS = {"aac"}


def _audio_target_label(a: "AudioStream", global_mode: "AudioMode") -> str:
    """'codec ch bitrate → targetcodec ch targetbitrate' or just 'copy'.
    Uses the stream's own overrides (a.mode/target_channels/target_bitrate/
    drc) if set, else global_mode / auto defaults."""
    src = a.label()
    mode = a.mode or global_mode
    override_tag = "  [override]" if a.mode is not None else ""
    if mode == AudioMode.COPY:
        return src + override_tag
    target_codec = "ac3" if mode == AudioMode.AC3 else "aac"
    copy_set = _AC3_CODECS if mode == AudioMode.AC3 else _AAC_CODECS
    needs_reencode = (a.target_channels is not None) or (a.drc > 0.0)
    if a.codec in copy_set and not needs_reencode:
        return f"{src}  [copy]{override_tag}"
    ch = a.target_channels or min(a.channels, 6)
    bitrate = a.target_bitrate or default_audio_bitrate(ch)
    ch_str = f"{ch}ch" if ch else ""
    drc_tag = f"  DRC {a.drc:.1f}" if a.drc > 0.0 else ""
    return f"{src}  → {target_codec} {ch_str} {bitrate}k{drc_tag}{override_tag}"


class AudioButton(QToolButton):
    """Dropdown mit Checkboxen für die Audiostream-Auswahl einer Zeile."""

    def __init__(self, mf: "MediaFile", mode: "AudioMode" = None) -> None:
        super().__init__()
        self.mf = mf
        self._mode = mode or AudioMode.COPY
        self.setPopupMode(QToolButton.InstantPopup)
        self._checkboxes: list[tuple["AudioStream", QCheckBox]] = []
        self._menu = QMenu(self)
        for a in mf.audio_streams:
            cb = QCheckBox(_audio_target_label(a, self._mode))
            cb.setChecked(a.selected)
            cb.toggled.connect(lambda on, a=a: self._toggle(a, on))
            wa = QWidgetAction(self._menu)
            w = QWidget()
            l = QHBoxLayout(w)
            l.setContentsMargins(8, 2, 8, 2)
            l.addWidget(cb)
            wa.setDefaultWidget(w)
            self._menu.addAction(wa)
            self._checkboxes.append((a, cb))
        if not mf.audio_streams:
            from i18n import t as _t
            self._menu.addAction(_t("audio_none")).setEnabled(False)
        self.setMenu(self._menu)
        self._resize_menu_to_content()
        self._update_text()

    def _resize_menu_to_content(self) -> None:
        """QWidgetAction checkboxes don't auto-widen the popup, so the menu
        can end up too narrow and clip long labels (e.g. → ac3 6ch 448k)."""
        if not self._checkboxes:
            return
        widest = max(cb.sizeHint().width() for _, cb in self._checkboxes)
        self._menu.setMinimumWidth(widest + 32)  # padding for menu margins

    def set_mode(self, mode: "AudioMode") -> None:
        """Update labels when the global audio mode changes."""
        self._mode = mode
        for a, cb in self._checkboxes:
            cb.setText(_audio_target_label(a, mode))
        self._resize_menu_to_content()
        self._update_text()

    def _toggle(self, stream, on: bool) -> None:
        stream.selected = on
        self._update_text()

    def _update_text(self) -> None:
        n = sum(1 for a in self.mf.audio_streams if a.selected)
        self.setText(f"{n}/{len(self.mf.audio_streams)} Audio")


class BenchmarkWorker(QThread):
    """Führt den ffmpeg-Testpattern-Encode für mehrere Encoder nacheinander
    aus und meldet jedes Ergebnis einzeln, damit die UI live aktualisiert
    werden kann statt am Ende auf alles zu warten."""
    result = Signal(object)   # sysinfo.BenchResult
    finished_all = Signal()

    def __init__(self, ffmpeg: str, encoders: list[tuple[str, str]]) -> None:
        super().__init__()
        self.ffmpeg = ffmpeg
        self.encoders = encoders

    def run(self) -> None:
        from sysinfo import run_benchmark
        for enc_id, label in self.encoders:
            self.result.emit(run_benchmark(self.ffmpeg, enc_id, label))
        self.finished_all.emit()


class _ElideLeftDelegate(QStyledItemDelegate):
    """Kürzt zu langen Zell-Text vorn ("…Ende") statt hinten (Standard) -
    für die Output-Spalte, damit das Ende eines langen Dateinamens
    (Zielauflösung/Audio-Tag/Namens-Kürzel) sichtbar bleibt."""

    def initStyleOption(self, option, index) -> None:  # noqa: N802
        super().initStyleOption(option, index)
        option.textElideMode = Qt.ElideLeft


class _ApplySettingsDialog(QDialog):
    """Überträgt ausgewählte Zeileneinstellungen einer Referenzdatei auf
    andere Zeilen (Batch sehr ähnlicher Dateien, z. B. Serienstaffel) —
    Audio-Auswahl/-Overrides, Crop-Enabled, Ziel, Tune, CRF, Video-Modus,
    jeweils einzeln abwählbar. Zielzeilen per Checkliste, alle vorausgewählt."""

    def __init__(self, ref_name: str, other_rows: list[tuple[int, str]],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("apply_settings_title", name=ref_name))
        self.resize(420, 420)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(t("apply_settings_what")))
        self.chk_audio = QCheckBox(t("apply_settings_audio"))
        self.chk_audio.setChecked(True)
        self.chk_audio.setToolTip(t("apply_settings_audio_tt"))
        self.chk_crop = QCheckBox(t("apply_settings_crop"))
        self.chk_crop.setChecked(True)
        self.chk_target = QCheckBox(t("apply_settings_target"))
        self.chk_target.setChecked(True)
        self.chk_tune = QCheckBox(t("apply_settings_tune"))
        self.chk_tune.setChecked(True)
        self.chk_crf = QCheckBox(t("apply_settings_crf"))
        self.chk_crf.setChecked(True)
        self.chk_video_mode = QCheckBox(t("apply_settings_video_mode"))
        self.chk_video_mode.setChecked(True)
        for cb in (self.chk_audio, self.chk_crop, self.chk_target,
                  self.chk_tune, self.chk_crf, self.chk_video_mode):
            layout.addWidget(cb)

        layout.addWidget(QLabel(t("apply_settings_rows")))
        self.list_rows = QListWidget()
        for row, name in other_rows:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, row)
            self.list_rows.addItem(item)
        layout.addWidget(self.list_rows, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def options(self) -> SettingsCopyOptions:
        return SettingsCopyOptions(
            audio=self.chk_audio.isChecked(),
            crop_enabled=self.chk_crop.isChecked(),
            target=self.chk_target.isChecked(),
            tune=self.chk_tune.isChecked(),
            crf=self.chk_crf.isChecked(),
            video_mode=self.chk_video_mode.isChecked())

    def selected_rows(self) -> list[int]:
        rows = []
        for i in range(self.list_rows.count()):
            item = self.list_rows.item(i)
            if item.checkState() == Qt.Checked:
                rows.append(item.data(Qt.UserRole))
        return rows


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FF-Transcoder (x265/MKV)")
        self.resize(1280, 720)
        self.settings = AppSettings()
        set_lang(self.settings.qs.value("ui/lang", "en"))
        self.pool = QThreadPool.globalInstance()
        self.files: list[MediaFile | None] = []   # Index = Tabellenzeile
        self.row_paths: list[Path] = []           # Quellpfad je Zeile
        self.encode_worker: EncodeWorker | None = None
        # Laufende QRunnables referenzieren: autoDelete würde sie nach run()
        # sofort zerstören und noch nicht zugestellte Signale verwerfen
        self._bg_jobs: set = set()
        self._job_t0: float = 0.0        # Startzeit aktueller Job
        self._batch_t0: float = 0.0      # Startzeit gesamte Batch
        self._jobs_done: int = 0         # abgeschlossene Jobs dieser Batch
        self._jobs_total: int = 0        # eingereihte Jobs dieser Batch
        self._current_pct: float = 0.0   # Fortschritt des laufenden Jobs (0-100)
        self._current_fps: float = 0.0   # aktuelle Encoding-Geschwindigkeit (fps)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_time)
        # Zuletzt gewählter *echter* Encoder (nicht der "Copy"-Sentinel in
        # cmb_encoder), gebraucht z. B. für Qualitäts-Vergleich und
        # per-Zeile Video-Encode, wenn global gerade "Copy" gewählt ist.
        self._last_encoder_id = self.settings.encoder or "libx265"
        self._build_ui()
        self._init_audio_mode()
        self._check_tools()

    # ------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # --- Einstellungsleiste ---
        bar = QHBoxLayout()      # Zeile 1
        bar2 = QHBoxLayout()     # Zeile 2
        self._lbl_target = QLabel()
        bar.addWidget(self._lbl_target)
        self.cmb_target = QComboBox()
        self.cmb_target.addItems(TARGET_RESOLUTIONS.keys())
        self.cmb_target.setCurrentText(self.settings.target_resolution)
        self.cmb_target.currentTextChanged.connect(self._on_target_changed)
        bar.addWidget(self.cmb_target)

        self._lbl_crf = QLabel()
        bar.addWidget(self._lbl_crf)
        self.spn_crf = QSpinBox()
        self.spn_crf.setRange(0, 51)
        self.spn_crf.setValue(self.settings.crf)
        self.spn_crf.valueChanged.connect(
            lambda v: setattr(self.settings, "crf", v))
        bar.addWidget(self.spn_crf)

        self._lbl_encoder = QLabel()
        bar.addWidget(self._lbl_encoder)
        self.cmb_encoder = QComboBox()
        self.cmb_encoder.setMinimumWidth(150)
        self.cmb_encoder.setEnabled(False)
        bar.addWidget(self.cmb_encoder)

        self._lbl_preset = QLabel()
        bar.addWidget(self._lbl_preset)
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItems(ENCODE_PRESETS)
        self.cmb_preset.setCurrentText(self.settings.preset)
        self.cmb_preset.currentTextChanged.connect(self._on_preset_changed)
        bar.addWidget(self.cmb_preset)

        self._lbl_tune = QLabel()
        bar.addWidget(self._lbl_tune)
        self.cmb_tune = QComboBox()
        for key, label in TUNE_PROFILES.items():
            self.cmb_tune.addItem(label, key)
        self.cmb_tune.setCurrentIndex(
            max(self.cmb_tune.findData(self.settings.tune), 0))
        self.cmb_tune.currentIndexChanged.connect(self._on_tune_changed)
        bar.addWidget(self.cmb_tune)

        self._lbl_audio_mode = QLabel()
        bar.addWidget(self._lbl_audio_mode)
        self.cmb_audio_mode = QComboBox()
        self.cmb_audio_mode.setMinimumWidth(100)
        bar.addWidget(self.cmb_audio_mode)

        self.chk_autocrop = QCheckBox()
        self.chk_autocrop.setChecked(self.settings.autocrop)
        self.chk_autocrop.toggled.connect(self._autocrop_toggled)
        bar2.addWidget(self.chk_autocrop)

        self._lbl_crop_min = QLabel()
        bar2.addWidget(self._lbl_crop_min)
        self.spn_crop_min = QSpinBox()
        self.spn_crop_min.setRange(0, 200)
        self.spn_crop_min.setSuffix(" px")
        self.spn_crop_min.setValue(self.settings.crop_min_px)
        self.spn_crop_min.valueChanged.connect(
            lambda v: setattr(self.settings, "crop_min_px", v))
        bar2.addWidget(self.spn_crop_min)

        self._lbl_name_tag = QLabel()
        bar2.addWidget(self._lbl_name_tag)
        self.edt_name_tag = QLineEdit(self.settings.name_tag)
        self.edt_name_tag.setMaximumWidth(90)
        self.edt_name_tag.editingFinished.connect(self._on_name_tag_changed)
        bar2.addWidget(self.edt_name_tag)

        self._lbl_outdir = QLabel()
        bar2.addWidget(self._lbl_outdir)
        _outdir_default = self.settings.output_override or (
            "/output" if Path("/output").is_dir() else "")
        self.edt_outdir = QLineEdit(_outdir_default)
        self.edt_outdir.editingFinished.connect(self._on_outdir_changed)
        bar2.addWidget(self.edt_outdir, 1)
        btn_outdir = QPushButton("…")
        btn_outdir.setFixedWidth(30)
        btn_outdir.clicked.connect(self._pick_outdir)
        bar2.addWidget(btn_outdir)
        bar.addStretch(1)
        settings_col = QVBoxLayout()
        settings_col.setSpacing(2)
        settings_col.addLayout(bar)
        settings_col.addLayout(bar2)
        top = QHBoxLayout()
        top.addLayout(settings_col, 1)

        # --- Drop-Area (kompakt rechts neben den Einstellungen) ---
        self.drop = DropArea()
        self.drop.files_dropped.connect(self.add_paths)
        self.drop.clicked.connect(self._open_dialog)
        top.addWidget(self.drop)
        root.addLayout(top)


        # --- Tabelle ---
        self.table = QTableWidget(0, 15)
        # Nur die Output-Spalte bekommt ElideLeft ("…" + Ende sichtbar statt
        # Anfang) - der Standard (ElideRight) würde bei langem Dateinamen
        # genau den für den Vergleich interessanten Teil (Zielauflösung/
        # Audio-Tag/Namens-Kürzel ganz am Ende) verdecken. Andere Spalten
        # (z. B. Quelldateiname) behalten bewusst ElideRight.
        self.table.setItemDelegateForColumn(COL_OUT, _ElideLeftDelegate(self.table))
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
        hdr.setSectionResizeMode(COL_OUT, QHeaderView.Stretch)
        for c in (COL_ON, COL_RES, COL_CROP_ON, COL_CROP, COL_TARGET, COL_HDR,
                  COL_AUDIO, COL_CRF, COL_TUNE, COL_MONO, COL_ENCODER, COL_PRESET):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(COL_STATUS, QHeaderView.Interactive)
        self.table.setColumnWidth(COL_STATUS, 220)
        hdr.setSectionsMovable(True)
        state = self.settings.qs.value("ui/header_state_v5")
        if state is not None:
            hdr.restoreState(state)
        hdr.sectionMoved.connect(
            lambda *_: self.settings.qs.setValue("ui/header_state_v5",
                                                 hdr.saveState()))
        self.table.itemChanged.connect(self._item_changed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table, 1)

        # --- Log-Feld (optional einblendbar) ---
        from applog import LOG
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(5000)
        self.txt_log.setMaximumHeight(200)
        from PySide6.QtGui import QFontDatabase
        self.txt_log.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.txt_log.setVisible(self.settings.show_log)
        root.addWidget(self.txt_log)
        LOG.line.connect(self.txt_log.appendPlainText)

        # --- Fußleiste ---
        foot = QHBoxLayout()
        self.btn_lang = QPushButton()
        self.btn_lang.setFixedWidth(38)
        self.btn_lang.setToolTip("Switch language / Sprache wechseln")
        self.btn_lang.clicked.connect(self._toggle_lang)
        foot.addWidget(self.btn_lang)
        self.btn_help = QPushButton("?")
        self.btn_help.setFixedWidth(28)
        self.btn_help.clicked.connect(self._show_help)
        foot.addWidget(self.btn_help)
        self.btn_sysinfo = QPushButton()
        self.btn_sysinfo.clicked.connect(self._show_sysinfo)
        foot.addWidget(self.btn_sysinfo)
        self.chk_log = QCheckBox()
        self.chk_log.setChecked(self.settings.show_log)
        self.chk_log.toggled.connect(self._toggle_log)
        foot.addWidget(self.chk_log)
        self.btn_clear_log = QPushButton()
        self.btn_clear_log.setVisible(self.settings.show_log)
        self.btn_clear_log.clicked.connect(self.txt_log.clear)
        foot.addWidget(self.btn_clear_log)
        self.btn_download = QPushButton()
        self.btn_download.setVisible(False)
        self.btn_download.clicked.connect(self._download_tools)
        foot.addWidget(self.btn_download)
        self.pb_download = QProgressBar()
        self.pb_download.setVisible(False)
        self.pb_download.setFixedWidth(220)
        foot.addWidget(self.pb_download)
        self.lbl_tools = QLabel("")
        foot.addWidget(self.lbl_tools, 1)
        self.lbl_time = QLabel("")
        self.lbl_time.setVisible(False)
        foot.addWidget(self.lbl_time)
        self.btn_start = QPushButton()
        self.btn_start.clicked.connect(self._start)
        self.btn_pause = QPushButton()
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_stop = QPushButton()
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        foot.addWidget(self.btn_start)
        foot.addWidget(self.btn_pause)
        foot.addWidget(self.btn_stop)
        root.addLayout(foot)

        self._retranslate()

    def _retranslate(self) -> None:
        """Alle statischen UI-Texte auf die aktuelle Sprache aktualisieren."""
        self.setWindowTitle(t("window_title"))
        self._lbl_target.setText(t("lbl_target"))
        self._lbl_crf.setText(t("lbl_crf"))
        self._lbl_encoder.setText(t("lbl_encoder"))
        copy_idx = self.cmb_encoder.findData(VideoMode.COPY.value)
        if copy_idx >= 0:
            self.cmb_encoder.setItemText(copy_idx, t("video_mode_copy"))
        self._lbl_preset.setText(t("lbl_preset"))
        self.cmb_preset.setToolTip(t("tt_preset"))
        self._lbl_tune.setText(t("lbl_tune"))
        self.cmb_tune.setToolTip(t("tt_tune"))
        self._lbl_audio_mode.setText(t("lbl_audio_mode"))
        for i in range(self.cmb_audio_mode.count()):
            mode = self.cmb_audio_mode.itemData(i)
            self.cmb_audio_mode.setItemText(i, t(f"audio_mode_{mode.value}"))
        self.chk_autocrop.setText(t("chk_autocrop"))
        self.chk_autocrop.setToolTip(t("tt_autocrop"))
        self._lbl_crop_min.setText(t("lbl_crop_min"))
        self._lbl_crop_min.setToolTip(t("tt_crop_min"))
        self.spn_crop_min.setToolTip(t("tt_crop_min"))
        self._lbl_name_tag.setText(t("lbl_name_tag"))
        self.edt_name_tag.setPlaceholderText(t("ph_name_tag"))
        self.edt_name_tag.setToolTip(t("tt_name_tag"))
        self._lbl_outdir.setText(t("lbl_outdir"))
        self.edt_outdir.setPlaceholderText(t("ph_outdir"))
        self.btn_sysinfo.setText(t("btn_sysinfo"))
        lang = get_lang()
        self.btn_lang.setText("EN" if lang == "de" else "DE")
        self.drop.set_hint(t("drop_hint"))
        self.table.setHorizontalHeaderLabels([
            "", t("col_file"), t("col_res"), t("col_hdr"), t("col_crop_on"),
            t("col_crop"), t("col_target"), t("col_crf"), t("col_encoder"),
            t("col_preset"), t("col_tune"), t("col_mono"), t("col_audio"),
            t("col_out"), t("col_status")])
        self.chk_log.setText(t("chk_log"))
        self.chk_log.setToolTip(t("tt_log"))
        self.btn_clear_log.setText(t("btn_clear_log"))
        self.btn_start.setText(t("btn_start"))
        self.btn_pause.setText(t("btn_resume") if self._is_paused() else t("btn_pause"))
        self.btn_stop.setText(t("btn_stop"))
        # Encoder-Suche-Platzhalter (wenn noch nicht erkannt)
        if not self.cmb_encoder.isEnabled() and self.cmb_encoder.count() == 1:
            self.cmb_encoder.setItemText(0, t("encoder_searching"))
        # Tool-Download-Button (Text hängt vom Zustand ab)
        if hasattr(self, "_dl_targets"):
            self._update_download_btn()
            self._update_tools_label()

    def _toggle_lang(self) -> None:
        new_lang = "en" if get_lang() == "de" else "de"
        set_lang(new_lang)
        self.settings.qs.setValue("ui/lang", new_lang)
        self._retranslate()
        # Tools-Label neu aufbauen (enthält übersetzte Statusmeldungen)
        if hasattr(self, "_dl_targets"):
            self._update_tools_label()

    def _show_help(self) -> None:
        # Path(__file__).parent resolves to the PyInstaller bundle dir
        # (sys._MEIPASS) in a frozen onefile build, same as icon.svg in
        # main.py — not the exe-adjacent app_dir() used for .tools/.
        base = Path(__file__).resolve().parent
        filename = "README_DE.md" if get_lang() == "de" else "README.md"
        readme_path = base / filename
        try:
            text = readme_path.read_text(encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, t("help_title"), t("help_load_error", err=str(e)))
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(t("help_title"))
        dlg.resize(760, 640)
        layout = QVBoxLayout(dlg)
        browser = QTextBrowser(dlg)
        browser.setOpenExternalLinks(True)
        browser.setMarkdown(text)
        layout.addWidget(browser)
        dlg.exec()

    def _show_sysinfo(self) -> None:
        from sysinfo import gather_system_info
        ffmpeg = self.settings.tools.get("ffmpeg")
        info = gather_system_info(self.settings.tools)

        dlg = QDialog(self)
        dlg.setWindowTitle(t("sysinfo_title"))
        dlg.resize(560, 520)
        layout = QVBoxLayout(dlg)

        lbl = QLabel(
            f"<b>{t('sysinfo_os')}:</b> {info.os}<br>"
            f"<b>CPU:</b> {info.cpu}  ({info.cores})<br>"
            f"<b>RAM:</b> {info.ram}  ({info.ram_type})<br>"
            f"<b>{t('sysinfo_encoders')}:</b> "
            + ", ".join(label for _id, label in info.encoders)
            + (f"<br><b>{t('sysinfo_x265')}:</b> {info.x265_version}"
               if info.x265_version else "")
        )
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        tools_lbl = QLabel(f"<b>{t('sysinfo_tools')}</b>")
        layout.addWidget(tools_lbl)
        tools_table = QTableWidget(0, 3)
        tools_table.setHorizontalHeaderLabels(
            [t("sysinfo_col_tool"), t("sysinfo_col_version"), t("sysinfo_col_path")])
        tools_table.horizontalHeader().setStretchLastSection(True)
        tools_table.verticalHeader().setVisible(False)
        tools_table.setEditTriggers(QTableWidget.NoEditTriggers)
        tools_table.setMaximumHeight(150)
        for name, path, ver in info.tools:
            row = tools_table.rowCount()
            tools_table.insertRow(row)
            tools_table.setItem(row, 0, QTableWidgetItem(name))
            tools_table.setItem(row, 1, QTableWidgetItem(ver or "–"))
            item_path = QTableWidgetItem(path)
            item_path.setToolTip(path)
            tools_table.setItem(row, 2, item_path)
        tools_table.resizeColumnsToContents()
        tools_table.setColumnWidth(0, int(tools_table.columnWidth(0) * 1.5))
        layout.addWidget(tools_table)

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels([t("sysinfo_col_encoder"), t("sysinfo_col_fps")])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        for _id, label in info.encoders:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(label))
            table.setItem(row, 1, QTableWidgetItem(t("sysinfo_pending")))
        table.resizeColumnsToContents()
        table.setColumnWidth(0, int(table.columnWidth(0) * 1.5))
        layout.addWidget(table)

        btn_row = QHBoxLayout()
        btn_bench = QPushButton(t("sysinfo_run_bench"))
        btn_close = QPushButton(t("btn_close_cancel"))
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_bench)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        if not ffmpeg:
            btn_bench.setEnabled(False)
            btn_bench.setToolTip(t("sysinfo_no_ffmpeg"))

        def start_bench() -> None:
            btn_bench.setEnabled(False)
            for row in range(table.rowCount()):
                table.setItem(row, 1, QTableWidgetItem(t("sysinfo_running")))
            worker = BenchmarkWorker(ffmpeg, info.encoders)
            dlg._bench_worker = worker  # keep alive (QThread would else be GC'd)

            def on_result(res) -> None:
                for row in range(table.rowCount()):
                    if table.item(row, 0).text() == res.label:
                        text = (f"{res.fps:.1f} fps" if res.fps is not None
                                else f"{t('sysinfo_error')}: {res.error[:60]}")
                        table.setItem(row, 1, QTableWidgetItem(text))
                        break

            def on_done() -> None:
                btn_bench.setEnabled(True)

            worker.result.connect(on_result)
            worker.finished_all.connect(on_done)
            worker.start()

        btn_bench.clicked.connect(start_bench)
        dlg.exec()

    def _autocrop_toggled(self, on: bool) -> None:
        self.settings.autocrop = on

    def _toggle_log(self, on: bool) -> None:
        self.settings.show_log = on
        self.txt_log.setVisible(on)
        self.btn_clear_log.setVisible(on)

    def _check_tools(self) -> None:
        self.settings.refresh_tools()
        tools = self.settings.tools
        missing = [k for k in ("ffmpeg", "ffprobe") if not tools.get(k)]
        self.btn_start.setEnabled(not missing)
        from downloader import mkvmerge_downloadable
        self._tool_missing = missing
        self._tool_no_dovi = not tools.get("dovi_tool")
        self._tool_no_mkv = not tools.get("mkvmerge")
        self._mkv_no_dl = not mkvmerge_downloadable()
        self._update_tools_label()
        self._dl_targets = []
        if missing:
            self._dl_targets.append("ffmpeg")
        if self._tool_no_dovi:
            self._dl_targets.append("dovi_tool")
        if self._tool_no_mkv and not self._mkv_no_dl:
            self._dl_targets.append("mkvmerge")
        from downloader import tools_dir
        tdir = tools_dir().resolve()
        self._upd_candidates = {
            name: path for name in ("ffmpeg", "dovi_tool", "mkvmerge")
            if (path := tools.get(name)) and Path(path).resolve().parent == tdir
            and (name != "mkvmerge" or not self._mkv_no_dl)
        }
        self._update_download_btn()
        if tools.get("ffmpeg"):
            self._detect_encoders_async(tools["ffmpeg"])

    def _update_tools_label(self) -> None:
        msgs = []
        if self._tool_missing:
            msgs.append(t("tools_missing", names=", ".join(self._tool_missing)))
        if self._tool_no_dovi:
            msgs.append(t("tools_no_dovi"))
        if self._tool_no_mkv:
            hint = "" if self._mkv_no_dl else t("tools_mkv_hint")
            msgs.append(t("tools_no_mkv", hint=hint))
        self.lbl_tools.setText("  |  ".join(msgs) or t("tools_ok"))

    def _update_download_btn(self) -> None:
        if self._dl_targets:
            self.btn_download.setText(t("btn_tools_missing"))
            self.btn_download.setVisible(True)
        else:
            self.btn_download.setText(t("btn_tools_update"))
            self.btn_download.setVisible(bool(self._upd_candidates))

    def _download_tools(self) -> None:
        if self._dl_targets:
            self._start_download(self._dl_targets)
        else:
            self._check_updates()

    def _start_download(self, targets: list[str]) -> None:
        from downloader import DownloadWorker
        self.btn_download.setEnabled(False)
        self.pb_download.setVisible(True)
        self.pb_download.setRange(0, 0)  # indeterminate bis erste Prozentangabe
        self.dl_worker = DownloadWorker(targets)
        self.dl_worker.progress.connect(self._dl_progress)
        self.dl_worker.finished_ok.connect(self._dl_done)
        self.dl_worker.failed.connect(self._dl_failed)
        self.dl_worker.start()

    def _check_updates(self) -> None:
        from downloader import UpdateCheckWorker
        self.btn_download.setEnabled(False)
        self.lbl_tools.setText(t("tools_searching"))
        self.upd_worker = UpdateCheckWorker(self._upd_candidates)
        self.upd_worker.done.connect(self._upd_done)
        self.upd_worker.failed.connect(self._dl_failed)
        self.upd_worker.start()

    def _upd_done(self, outdated: dict) -> None:
        self.btn_download.setEnabled(True)
        if not outdated:
            self.lbl_tools.setText(t("tools_current"))
            return
        lines = "\n".join(f"  {name}: {loc} → {rem}"
                          for name, (loc, rem) in outdated.items())
        if QMessageBox.question(
                self, t("dlg_updates_title"),
                t("dlg_updates_text", lines=lines),
        ) == QMessageBox.Yes:
            self._start_download(list(outdated))
        else:
            self._check_tools()

    def _dl_progress(self, txt: str, pct: float) -> None:
        self.lbl_tools.setText(txt)
        if pct < 0:
            self.pb_download.setRange(0, 0)
        else:
            self.pb_download.setRange(0, 100)
            self.pb_download.setValue(int(pct))

    def _dl_done(self) -> None:
        self.pb_download.setVisible(False)
        self.btn_download.setEnabled(True)
        self._check_tools()
        self._retry_failed_rows()

    def _retry_failed_rows(self) -> None:
        """Zeilen, deren Analyse mangels Tools scheiterte, nach
        erfolgreichem Tool-Download automatisch neu analysieren."""
        t = self.settings.tools
        if not (t.get("ffmpeg") and t.get("ffprobe")):
            return
        for r in range(len(self.files)):
            item = self.table.item(r, COL_STATUS)
            if (self.files[r] is None and item
                    and item.text().startswith(t("status_error"))):
                item.setText(status_t(JobStatus.ANALYZING))
                w = AnalyzeWorker(r, self.row_paths[r],
                                  self.settings.tools["ffprobe"],
                                  self.settings.tools["ffmpeg"],
                                  self.chk_autocrop.isChecked(),
                                  self.spn_crf.value(),
                                  self.settings.crop_min_px)
                w.signals.finished.connect(
                    lambda r2, mf: self._analyzed(r2, mf, None))
                w.signals.failed.connect(self._analyze_failed)
                w.signals.crop_progress.connect(self._crop_analysis_progress)
                self._start_job(w)

    def _dl_failed(self, msg: str) -> None:
        self.pb_download.setVisible(False)
        self.btn_download.setEnabled(True)
        QMessageBox.warning(self, t("dlg_dl_fail_title"),
                            t("dlg_dl_fail_text", msg=msg))
        self._check_tools()

    def _detect_encoders_async(self, ffmpeg: str) -> None:
        from PySide6.QtCore import QRunnable, QObject, Signal as Sig

        class _Sig(QObject):
            done = Sig(list)

        class _Job(QRunnable):
            def __init__(self, s):
                super().__init__()
                self.s = s

            def run(self):
                self.s.done.emit(detect_encoders(ffmpeg))

        sig = _Sig()
        sig.done.connect(self._encoders_detected)
        self._enc_sig = sig  # Referenzen halten (autoDelete-Race)
        self._enc_job = _Job(sig)
        self._enc_job.setAutoDelete(False)
        self.pool.start(self._enc_job)

    def _encoders_detected(self, encoders: list[str]) -> None:
        self.cmb_encoder.clear()
        for e in encoders:
            self.cmb_encoder.addItem(ENCODER_LABELS.get(e, e), e)
        # "Copy" als letzter Eintrag statt eines separaten Video-Dropdowns —
        # Default bleibt der erste echte Encoder (Software libx265).
        self.cmb_encoder.addItem(t("video_mode_copy"), VideoMode.COPY.value)
        if self.settings.video_mode == VideoMode.COPY:
            idx = self.cmb_encoder.findData(VideoMode.COPY.value)
        else:
            idx = self.cmb_encoder.findData(self.settings.encoder)
        self.cmb_encoder.setCurrentIndex(max(idx, 0))
        self.cmb_encoder.setEnabled(True)
        self.cmb_encoder.currentIndexChanged.connect(self._on_encoder_changed)
        self._on_encoder_changed()

    # ------------------------------------------------------- Dateiaufnahme

    @staticmethod
    def _default_browse_dir() -> str:
        # In Docker the /input volume is the natural starting point
        p = Path("/input")
        return str(p) if p.is_dir() else ""

    def _open_dialog(self) -> None:
        start = self._default_browse_dir()
        files, _ = QFileDialog.getOpenFileNames(
            self, t("fdlg_files_title"), start, t("fdlg_files_filter"))
        if files:
            self.add_paths([Path(f) for f in files])
            return
        d = QFileDialog.getExistingDirectory(self, t("fdlg_folder_title"), start)
        if d:
            self.add_paths([Path(d)])

    def add_paths(self, paths: list[Path]) -> None:
        """Ordner rekursiv nach Videodateien durchsuchen (collect_video_files)
        läuft im Hintergrund-Thread – bei großen/tiefen Ordnern (v. a. über
        ein Netzlaufwerk) kann rglob() mehrere Sekunden dauern und würde
        das Fenster sonst komplett einfrieren."""
        from PySide6.QtCore import QRunnable, QObject, Signal as Sig

        class _ScanSig(QObject):
            done = Sig(list)

        class _ScanJob(QRunnable):
            def __init__(self, s: _ScanSig, paths: list[Path]) -> None:
                super().__init__()
                self.s = s
                self.paths = paths

            def run(self) -> None:
                self.s.done.emit(collect_video_files(self.paths))

        self.drop.set_hint(t("drop_scanning"))
        self.drop.setEnabled(False)
        sig = _ScanSig()
        job = _ScanJob(sig, paths)
        job.setAutoDelete(False)
        # In self._bg_jobs halten (nicht in einem einzelnen Attribut) -
        # ein zweiter Scan (z. B. nochmal per Dateidialog während der
        # erste noch läuft) darf die Referenz auf den ersten, noch
        # laufenden Job/QObject nicht überschreiben (sonst GC-Race mit
        # noch laufendem QRunnable -> Crash, wie beim Frame-Compare-Bug).
        self._bg_jobs.add(job)
        self._bg_jobs.add(sig)

        def _on_done(videos: list[Path]) -> None:
            self._bg_jobs.discard(job)
            self._bg_jobs.discard(sig)
            self._scan_done(videos)

        sig.done.connect(_on_done)
        self.pool.start(job)

    def _scan_done(self, videos: list[Path]) -> None:
        self.drop.setEnabled(True)
        self.drop.set_hint(t("drop_hint"))
        existing = {mf.path.resolve() for mf in self.files if mf}
        videos = [v for v in videos if v.resolve() not in existing]
        if not videos:
            return
        autocrop = self.chk_autocrop.isChecked()
        # "Check only first file for crop" option removed (UI clutter).
        # To restore: add QCheckBox chk_first_crop bound to settings.crop_first_only,
        # set chk_first_crop.setEnabled() in _autocrop_toggled, and read it here.
        first_only = False
        batch_anchor_row: int | None = None
        for i, v in enumerate(videos):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.files.append(None)
            self.row_paths.append(v)
            self.table.setItem(row, COL_FILE, QTableWidgetItem(v.name))
            self.table.item(row, COL_FILE).setToolTip(str(v))
            self.table.setItem(row, COL_STATUS,
                               QTableWidgetItem(status_t(JobStatus.ANALYZING)))
            do_crop = autocrop and ((not first_only) or i == 0)
            if autocrop and first_only and i == 0:
                batch_anchor_row = row
            w = AnalyzeWorker(row, v, self.settings.tools["ffprobe"],
                              self.settings.tools["ffmpeg"], do_crop,
                              self.spn_crf.value(), self.settings.crop_min_px)
            w.signals.finished.connect(
                lambda r, mf, anchor=batch_anchor_row:
                self._analyzed(r, mf, anchor))
            w.signals.failed.connect(self._analyze_failed)
            w.signals.crop_progress.connect(self._crop_analysis_progress)
            self._start_job(w)

    def _start_job(self, w) -> None:
        """QRunnable starten und referenzieren, bis seine Signale
        zugestellt wurden (sonst Race mit autoDelete).
        Signals-QObject wird explizit mitgehalten, da QRunnable kein
        QObject-Parent sein kann und der GC es sonst vorzeitig löscht."""
        w.setAutoDelete(False)
        self._bg_jobs.add(w)
        self._bg_jobs.add(w.signals)   # prevent GC of the signals QObject
        def _done(*_a, job=w):
            self._bg_jobs.discard(job)
            self._bg_jobs.discard(job.signals)
        w.signals.finished.connect(_done)
        w.signals.failed.connect(_done)
        self.pool.start(w)

    def _analyzed(self, row: int, mf: MediaFile, anchor_row: int | None) -> None:
        self.files[row] = mf
        # Crop vom Batch-Anker übernehmen (Schnellmodus)
        if (anchor_row is not None and row != anchor_row
                and self.files[anchor_row] is not None
                and not mf.crop.valid):
            mf.crop = CropInfo(**vars(self.files[anchor_row].crop))
        self._fill_row(row, mf)
        # Falls Anker später fertig wird: Crop an wartende Batch-Zeilen verteilen
        if anchor_row == row and mf.crop.valid:
            for r, other in enumerate(self.files):
                if other and r != row and not other.crop.valid \
                        and other.status == JobStatus.READY:
                    pass  # bereits gefüllte Zeilen nicht ungefragt ändern
        self._update_target_cell(row)

    def _crop_analysis_progress(self, row: int, done: int, total: int) -> None:
        w = self.table.cellWidget(row, COL_STATUS)
        if not isinstance(w, QProgressBar):
            pb = QProgressBar()
            pb.setRange(0, total)
            self.table.setCellWidget(row, COL_STATUS, pb)
            w = pb
        w.setMaximum(total)
        w.setValue(done)
        w.setFormat(t("crop_sample", done=done, total=total))

    def _analyze_failed(self, row: int, msg: str) -> None:
        self.table.removeCellWidget(row, COL_STATUS)
        self.table.setItem(row, COL_STATUS,
                           QTableWidgetItem(f"Fehler: {msg[:80]}"))

    @staticmethod
    def _center_widget(inner: QWidget) -> QWidget:
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setAlignment(Qt.AlignCenter)
        l.addWidget(inner)
        return w

    def _set_out_item(self, row: int, out: Path) -> None:
        item = self.table.item(row, COL_OUT)
        if item:
            item.setText(out.name)
            item.setToolTip(str(out))
            item.setData(Qt.UserRole, str(out))

    def _effective_target(self, mf: "MediaFile") -> str:
        """Effektive Zielauflösungs-Bezeichnung für eine Zeile."""
        return mf.target or self.cmb_target.currentText()

    def _global_video_mode(self) -> VideoMode:
        """Globaler Video-Modus, abgeleitet aus der Encoder-Auswahl
        ("Copy" ist ein Eintrag im Encoder-Dropdown, kein eigenes Feld)."""
        return (VideoMode.COPY if self.cmb_encoder.currentData() == VideoMode.COPY.value
                else VideoMode.ENCODE)

    def _effective_video_mode(self, mf: "MediaFile") -> VideoMode:
        """Effektiver Video-Modus für eine Zeile (Zeilen-Override oder global)."""
        return mf.video_mode or self._global_video_mode()

    def _global_audio_mode(self) -> AudioMode:
        return self.cmb_audio_mode.currentData() or AudioMode.COPY

    def _output_kwargs(self, mf: "MediaFile") -> dict:
        """Gemeinsame Zusatz-Argumente für MediaFile.default_output() –
        Audio-Wandlungs-Tag (AC3/AAC) und freies Namens-Kürzel, die an jedem
        Aufrufort identisch mitgegeben werden müssen."""
        return dict(audio_mode=self._global_audio_mode(),
                   name_tag=self.settings.name_tag)

    def _fill_row(self, row: int, mf: MediaFile) -> None:
        out = mf.default_output(self._override_dir(), self._effective_target(mf),
                               video_mode=self._effective_video_mode(mf),
                               **self._output_kwargs(mf))
        mf.output_path = out
        mf.status = JobStatus.EXISTS if out.exists() else JobStatus.READY
        self._render_row(row)

    def _render_row(self, row: int) -> None:
        """Zeichnet eine Zeile komplett aus dem MediaFile-Zustand neu
        (auch nach Zeilentausch verwendbar)."""
        mf = self.files[row]
        # NICHT "t" nennen - würde die globale i18n-Funktion t() für den
        # Rest der Funktion verdecken (siehe der Atmos-Warnhinweis unten,
        # der genau deswegen vorher nie den übersetzten Text zeigte).
        tbl = self.table

        cb_on = QCheckBox()
        cb_on.setChecked(mf.enabled)
        cb_on.setToolTip("Vom Transcode ausschließen/einschließen")
        cb_on.toggled.connect(lambda on, r=row: self._enabled_toggled(r, on))
        tbl.setCellWidget(row, COL_ON, self._center_widget(cb_on))

        tbl.setItem(row, COL_FILE, QTableWidgetItem(mf.path.name))
        tbl.item(row, COL_FILE).setToolTip(str(mf.path))
        tbl.setItem(row, COL_RES, QTableWidgetItem(
            f"{mf.resolution_label()}  {mf.video_codec} {mf.bit_depth}bit"))

        cb = QCheckBox()
        cb.setChecked(mf.crop_enabled and mf.crop.valid)
        cb.setEnabled(mf.crop.valid)
        cb.toggled.connect(lambda on, r=row: self._crop_toggled(r, on))
        tbl.setCellWidget(row, COL_CROP_ON, self._center_widget(cb))

        crop_item = QTableWidgetItem(str(mf.crop))
        tbl.setItem(row, COL_CROP, crop_item)
        self._style_crop_cell(row)

        hdr_item = QTableWidgetItem(mf.hdr_label())
        col = HDR_COLORS.get(mf.hdr)
        if col:
            hdr_item.setBackground(col)
            hdr_item.setForeground(QColor("white"))
        tbl.setItem(row, COL_HDR, hdr_item)

        tbl.setCellWidget(row, COL_AUDIO, AudioButton(
            mf, self.cmb_audio_mode.currentData() or AudioMode.COPY))

        spn = QSpinBox()
        spn.setRange(0, 51)
        spn.setValue(mf.crf)
        spn.valueChanged.connect(lambda v, m=mf: setattr(m, "crf", v))
        tbl.setCellWidget(row, COL_CRF, spn)

        cb_mono = QCheckBox()
        cb_mono.setChecked(mf.monochrome)
        cb_mono.setToolTip(t("tt_mono"))
        cb_mono.toggled.connect(lambda on, r=row: self._mono_toggled(r, on))
        tbl.setCellWidget(row, COL_MONO, self._center_widget(cb_mono))

        out_path = mf.output_path
        # COL_TUNE wird per _update_tune_cell ganz unten gesetzt
        out_item = QTableWidgetItem(out_path.name if out_path else "")
        out_item.setData(Qt.UserRole, str(out_path or ""))
        out_item.setFlags(out_item.flags() | Qt.ItemIsEditable)
        out_item.setToolTip(str(out_path or ""))
        # Rechtsbündig: bei langen Namen (Zielauflösung/Audio-Tag/Kürzel
        # angehängt) bleibt so das Ende des Namens sichtbar, ohne dass man
        # scrollen oder die Spalte breiter ziehen muss.
        out_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tbl.setItem(row, COL_OUT, out_item)

        tbl.removeCellWidget(row, COL_STATUS)
        status_text = status_t(mf.status)
        # Warn if Atmos tracks present and audio mode will transcode them
        audio_mode = self.cmb_audio_mode.currentData() or AudioMode.COPY
        if audio_mode != AudioMode.COPY and any(
                a.atmos for a in mf.audio_streams if a.selected):
            status_text = t("status_atmos_warn")
        tbl.setItem(row, COL_STATUS, QTableWidgetItem(status_text))
        self._update_target_cell(row)
        self._update_tune_cell(row)
        self._update_encoder_cell(row)
        self._update_preset_cell(row)
        self._style_row_enabled(row)

    def _enabled_toggled(self, row: int, on: bool) -> None:
        mf = self.files[row]
        if not mf:
            return
        mf.enabled = on
        # Bereits eingereihte Jobs wieder herausnehmen
        if not on and mf.status == JobStatus.QUEUED and self.encode_worker:
            if self.encode_worker.dequeue(row):
                mf.status = JobStatus.READY
                self.table.item(row, COL_STATUS).setText(status_t(JobStatus.READY))
        self._style_row_enabled(row)

    def _style_row_enabled(self, row: int) -> None:
        mf = self.files[row]
        gray = QColor("gray")
        normal = self.palette().text().color()
        for c in (COL_FILE, COL_RES, COL_OUT, COL_STATUS):
            item = self.table.item(row, c)
            if item:
                item.setForeground(normal if mf.enabled else gray)
        for col in (COL_TARGET, COL_TUNE):
            cmb = self.table.cellWidget(row, col)
            if isinstance(cmb, QComboBox):
                cmb.setEnabled(mf.enabled)
        self._style_crop_cell(row)

    def _item_changed(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if item.column() == COL_OUT and row < len(self.files) and self.files[row]:
            mf = self.files[row]
            txt = item.text()
            # Wenn der User nur einen Dateinamen (ohne Verzeichnis) tippt,
            # Verzeichnis aus dem gespeicherten vollen Pfad übernehmen
            p = Path(txt)
            if not p.parent or p.parent == Path("."):
                prev = item.data(Qt.UserRole) or ""
                p = Path(prev).parent / p if prev else p
            mf.output_path = p
            item.setData(Qt.UserRole, str(p))
            item.setToolTip(str(p))
            item.setText(p.name)
            # Existiert-Status neu bewerten (Zeile wird sonst nie encodet)
            if mf.status in (JobStatus.READY, JobStatus.EXISTS):
                mf.status = (JobStatus.EXISTS if mf.output_path.exists()
                             else JobStatus.READY)
                st = self.table.item(row, COL_STATUS)
                if st:
                    st.setText(status_t(mf.status))
        elif item.column() == COL_CROP and row < len(self.files) and self.files[row]:
            self._parse_manual_crop(row, item.text())

    def _parse_manual_crop(self, row: int, text: str) -> None:
        mf = self.files[row]
        try:
            w, h, x, y = (int(p) for p in text.replace("×", ":").split(":"))
            mf.crop = CropInfo(w=w, h=h, x=x, y=y)
        except ValueError:
            return
        # Autocrop hat evtl. nichts erkannt (crop.valid war False) und damit
        # die Checkbox deaktiviert gelassen (siehe _render_row) — nach einem
        # gültigen manuellen Wert muss sie wieder anwählbar sein.
        wrapper = self.table.cellWidget(row, COL_CROP_ON)
        cb = wrapper.findChild(QCheckBox) if wrapper else None
        if cb is not None:
            cb.setEnabled(mf.crop.valid)
        self._style_crop_cell(row)
        self._update_target_cell(row)

    def _crop_toggled(self, row: int, on: bool) -> None:
        mf = self.files[row]
        if mf:
            mf.crop_enabled = on
            self._style_crop_cell(row)
            self._update_target_cell(row)

    def _mono_toggled(self, row: int, on: bool) -> None:
        mf = self.files[row]
        if mf:
            mf.monochrome = on

    def _style_crop_cell(self, row: int) -> None:
        mf = self.files[row]
        item = self.table.item(row, COL_CROP)
        if mf and item:
            item.setForeground(
                QColor("gray") if not (mf.crop_enabled and mf.crop.valid)
                else self.palette().text().color())

    def _update_target_cell(self, row: int) -> None:
        """Pro-Zeile-Dropdown für die Zielauflösung; erster Eintrag folgt
        der globalen Einstellung. Items zeigen die errechnete Größe."""
        mf = self.files[row]
        if not mf:
            return
        cmb = self.table.cellWidget(row, COL_TARGET)
        if not isinstance(cmb, QComboBox):
            cmb = QComboBox()
            cmb.currentIndexChanged.connect(
                lambda _i, r=row: self._row_target_changed(r))
            self.table.setCellWidget(row, COL_TARGET, cmb)
        g = self.cmb_target.currentText()
        cmb.blockSignals(True)
        cmb.clear()
        for name in ("", *TARGET_RESOLUTIONS):
            tw, th = mf.compute_target_size(name or g)
            label = f"{name or f'Global ({g})'}: {tw}×{th}"
            cmb.addItem(label, name)
        cmb.setCurrentIndex(max(cmb.findData(mf.target), 0))
        cmb.blockSignals(False)

    def _update_tune_cell(self, row: int) -> None:
        """Pro-Zeile-Dropdown für das Inhalts-Tuning; erster Eintrag folgt
        der globalen Einstellung."""
        mf = self.files[row]
        if not mf:
            return
        cmb = self.table.cellWidget(row, COL_TUNE)
        if not isinstance(cmb, QComboBox):
            cmb = QComboBox()
            cmb.currentIndexChanged.connect(
                lambda _i, r=row: self._row_tune_changed(r))
            self.table.setCellWidget(row, COL_TUNE, cmb)
        g_label = TUNE_PROFILES.get(self.cmb_tune.currentData(), "Standard")
        cmb.blockSignals(True)
        cmb.clear()
        cmb.addItem(f"Global ({g_label})", "")
        for key, label in TUNE_PROFILES.items():
            cmb.addItem(label, key)
        cmb.setCurrentIndex(max(cmb.findData(mf.tune), 0))
        cmb.blockSignals(False)

    def _row_tune_changed(self, row: int) -> None:
        mf = self.files[row]
        cmb = self.table.cellWidget(row, COL_TUNE)
        if mf and isinstance(cmb, QComboBox):
            mf.tune = cmb.currentData() or ""

    def _update_encoder_cell(self, row: int) -> None:
        """Pro-Zeile-Dropdown für den Encoder; erster Eintrag folgt der
        globalen Auswahl, letzter ist "Copy" (wie beim globalen Encoder-
        Dropdown in ein Feld gemergt statt eines separaten Video-Modus-
        Kontextmenüs — ein Widget, ein eindeutiger Zustand, keine zwei
        Stellen, die auseinanderlaufen können)."""
        mf = self.files[row]
        if not mf:
            return
        cmb = self.table.cellWidget(row, COL_ENCODER)
        if not isinstance(cmb, QComboBox):
            cmb = QComboBox()
            cmb.currentIndexChanged.connect(
                lambda _i, r=row: self._row_encoder_changed(r))
            self.table.setCellWidget(row, COL_ENCODER, cmb)
        g_label = (t("video_mode_copy") if self._global_video_mode() == VideoMode.COPY
                  else ENCODER_LABELS.get(self._last_encoder_id, self._last_encoder_id))
        cmb.blockSignals(True)
        cmb.clear()
        cmb.addItem(f"Global ({g_label})", "")
        for i in range(self.cmb_encoder.count()):
            enc_id = self.cmb_encoder.itemData(i)
            if enc_id and enc_id != VideoMode.COPY.value:
                cmb.addItem(self.cmb_encoder.itemText(i), enc_id)
        cmb.addItem(t("video_mode_copy"), VideoMode.COPY.value)
        if mf.video_mode == VideoMode.COPY:
            idx = cmb.findData(VideoMode.COPY.value)
        else:
            idx = cmb.findData(mf.encoder)
        cmb.setCurrentIndex(max(idx, 0))
        cmb.blockSignals(False)

    def _row_encoder_changed(self, row: int) -> None:
        mf = self.files[row]
        cmb = self.table.cellWidget(row, COL_ENCODER)
        if not (mf and isinstance(cmb, QComboBox)):
            return
        data = cmb.currentData()
        if data == VideoMode.COPY.value:
            mf.encoder = ""
            self._set_video_mode(row, VideoMode.COPY)
        elif data:
            mf.encoder = data
            self._set_video_mode(row, VideoMode.ENCODE)
        else:
            mf.encoder = ""
            self._set_video_mode(row, None)

    def _update_preset_cell(self, row: int) -> None:
        """Pro-Zeile-Dropdown für das Encoder-Preset; erster Eintrag folgt
        der globalen Auswahl."""
        mf = self.files[row]
        if not mf:
            return
        cmb = self.table.cellWidget(row, COL_PRESET)
        if not isinstance(cmb, QComboBox):
            cmb = QComboBox()
            cmb.currentIndexChanged.connect(
                lambda _i, r=row: self._row_preset_changed(r))
            self.table.setCellWidget(row, COL_PRESET, cmb)
        g_preset = self.cmb_preset.currentText()
        cmb.blockSignals(True)
        cmb.clear()
        cmb.addItem(f"Global ({g_preset})", "")
        for p in ENCODE_PRESETS:
            cmb.addItem(p, p)
        cmb.setCurrentIndex(max(cmb.findData(mf.preset), 0))
        cmb.blockSignals(False)

    def _row_preset_changed(self, row: int) -> None:
        mf = self.files[row]
        cmb = self.table.cellWidget(row, COL_PRESET)
        if mf and isinstance(cmb, QComboBox):
            mf.preset = cmb.currentData() or ""

    def _init_audio_mode(self) -> None:
        for mode in AudioMode:
            self.cmb_audio_mode.addItem(t(f"audio_mode_{mode.value}"), mode)
        saved = self.settings.audio_mode
        self.cmb_audio_mode.setCurrentIndex(
            max(self.cmb_audio_mode.findData(saved), 0))
        self.cmb_audio_mode.currentIndexChanged.connect(self._on_audio_mode_changed)

    def _on_audio_mode_changed(self) -> None:
        mode = self.cmb_audio_mode.currentData() or AudioMode.COPY
        self.settings.audio_mode = mode
        for row in range(self.table.rowCount()):
            btn = self.table.cellWidget(row, COL_AUDIO)
            if isinstance(btn, AudioButton):
                btn.set_mode(mode)
        if self.encode_worker:
            self.encode_worker.audio_mode = mode
        # Dateiname spiegelt eine tatsächliche Audio-Wandlung (AC3/AAC-Tag)
        # wider -> Ausgabepfad je Zeile neu berechnen.
        for r, mf in enumerate(self.files):
            if mf and mf.status in (JobStatus.READY, JobStatus.EXISTS):
                out = mf.default_output(self._override_dir(), self._effective_target(mf),
                                       video_mode=self._effective_video_mode(mf),
                                       **self._output_kwargs(mf))
                mf.output_path = out
                self._set_out_item(r, out)

    def _on_encoder_changed(self) -> None:
        data = self.cmb_encoder.currentData()
        copy_mode = data == VideoMode.COPY.value
        self.settings.video_mode = VideoMode.COPY if copy_mode else VideoMode.ENCODE
        if not copy_mode:
            encoder = data or "libx265"
            self._last_encoder_id = encoder
            self.settings.encoder = encoder
        # Bei globalem Video-Copy sind Preset/Tune/Ziel wirkungslos
        self.cmb_preset.setEnabled(not copy_mode)
        supports_tune = not copy_mode and self._last_encoder_id == "libx265"
        self._lbl_tune.setEnabled(supports_tune)
        self.cmb_tune.setEnabled(supports_tune)
        self.cmb_target.setEnabled(not copy_mode)
        # "Global (…)"-Beschriftung + Auswahlliste in allen Zeilen aktualisieren
        for r, mf in enumerate(self.files):
            if mf:
                self._update_encoder_cell(r)
        if self.encode_worker:
            self.encode_worker.encoder = self._last_encoder_id
            self.encode_worker.video_mode = self._global_video_mode()

    def _on_tune_changed(self, _idx: int) -> None:
        tune = self.cmb_tune.currentData() or "none"
        self.settings.tune = tune
        # "Global (…)"-Beschriftung in allen Zeilen aktualisieren
        for r, mf in enumerate(self.files):
            if mf:
                self._update_tune_cell(r)
        if self.encode_worker:
            self.encode_worker.tune = tune

    def _row_target_changed(self, row: int) -> None:
        mf = self.files[row]
        cmb = self.table.cellWidget(row, COL_TARGET)
        if mf and isinstance(cmb, QComboBox):
            mf.target = cmb.currentData() or ""
            if mf.status in (JobStatus.READY, JobStatus.EXISTS):
                out = mf.default_output(self._override_dir(), self._effective_target(mf),
                                       video_mode=self._effective_video_mode(mf),
                                       **self._output_kwargs(mf))
                mf.output_path = out
                self._set_out_item(row, out)
                mf.status = JobStatus.EXISTS if out.exists() else JobStatus.READY
                self.table.item(row, COL_STATUS).setText(status_t(mf.status))

    def _on_preset_changed(self, preset: str) -> None:
        self.settings.preset = preset
        # "Global (…)"-Beschriftung in allen Zeilen aktualisieren
        for r, mf in enumerate(self.files):
            if mf:
                self._update_preset_cell(r)
        if self.encode_worker:
            self.encode_worker.preset = preset

    def _on_target_changed(self, name: str) -> None:
        self.settings.target_resolution = name
        if self.encode_worker:
            self.encode_worker.target = name
        for r, mf in enumerate(self.files):
            if not mf:
                continue
            self._update_target_cell(r)
            if not mf.target and mf.status in (JobStatus.READY, JobStatus.EXISTS):
                out = mf.default_output(self._override_dir(), name,
                                       video_mode=self._effective_video_mode(mf),
                                       **self._output_kwargs(mf))
                mf.output_path = out
                self._set_out_item(r, out)
                mf.status = JobStatus.EXISTS if out.exists() else JobStatus.READY
                s_item = self.table.item(r, COL_STATUS)
                if s_item:
                    s_item.setText(status_t(mf.status))

    def _override_dir(self) -> Path | None:
        txt = self.edt_outdir.text().strip()
        return Path(txt) if txt else None

    def _on_outdir_changed(self) -> None:
        self.settings.output_override = self.edt_outdir.text().strip()
        # Defaults neu setzen für Zeilen, die noch nicht laufen/fertig sind
        for r, mf in enumerate(self.files):
            if mf and mf.status in (JobStatus.READY, JobStatus.EXISTS):
                out = mf.default_output(self._override_dir(), self._effective_target(mf),
                                       video_mode=self._effective_video_mode(mf),
                                       **self._output_kwargs(mf))
                mf.output_path = out
                self._set_out_item(r, out)

    def _on_name_tag_changed(self) -> None:
        self.settings.name_tag = self.edt_name_tag.text().strip()
        for r, mf in enumerate(self.files):
            if mf and mf.status in (JobStatus.READY, JobStatus.EXISTS):
                out = mf.default_output(self._override_dir(), self._effective_target(mf),
                                       video_mode=self._effective_video_mode(mf),
                                       **self._output_kwargs(mf))
                mf.output_path = out
                self._set_out_item(r, out)

    def _pick_outdir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, t("fdlg_outdir_title"))
        if d:
            self.edt_outdir.setText(d)
            self._on_outdir_changed()

    # ------------------------------------------------------- Kontextmenü

    def _context_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0 or not self.files[row]:
            return
        menu = QMenu(self)
        a_crop = QAction(t("ctx_reanalyze"), self)
        a_crop.triggered.connect(lambda: self._reanalyze_crop(row))
        menu.addAction(a_crop)
        a_prev = QAction(t("ctx_preview"), self)
        a_prev.triggered.connect(lambda: self._show_crop_preview(row))
        a_prev.setEnabled(bool(self.settings.tools.get("ffmpeg")))
        menu.addAction(a_prev)
        a_qc = QAction(t("ctx_quality"), self)
        a_qc.triggered.connect(lambda: self._show_quality_check(row))
        a_qc.setEnabled(bool(self.settings.tools.get("ffmpeg")))
        menu.addAction(a_qc)
        a_mi = QAction(t("ctx_media_info"), self)
        a_mi.triggered.connect(lambda: self._show_media_info(row))
        a_mi.setEnabled(bool(self.settings.tools.get("ffprobe")))
        menu.addAction(a_mi)
        menu.addSeparator()
        mf = self.files[row]
        a_force = QAction(t("ctx_force"), self)
        a_force.triggered.connect(lambda: self._force_overwrite(row))
        a_force.setEnabled(mf is not None and mf.status == JobStatus.EXISTS)
        menu.addAction(a_force)
        a_requeue = QAction(t("ctx_requeue"), self)
        a_requeue.triggered.connect(lambda: self._requeue_row(row))
        a_requeue.setEnabled(
            mf is not None and mf.status in (JobStatus.DONE, JobStatus.ERROR))
        menu.addAction(a_requeue)
        if mf.audio_streams:
            menu.addSeparator()
            self._build_audio_submenu(menu, row, mf)
        menu.addSeparator()
        a_apply = QAction(t("ctx_apply_settings"), self)
        a_apply.triggered.connect(lambda: self._show_apply_settings(row))
        a_apply.setEnabled(sum(1 for f in self.files if f) > 1)
        menu.addAction(a_apply)
        menu.addSeparator()
        a_up = QAction(t("ctx_up"), self)
        a_up.triggered.connect(lambda: self._move_row(row, -1))
        a_up.setEnabled(self._movable_neighbor(row, -1) is not None)
        menu.addAction(a_up)
        a_dn = QAction(t("ctx_down"), self)
        a_dn.triggered.connect(lambda: self._move_row(row, +1))
        a_dn.setEnabled(self._movable_neighbor(row, +1) is not None)
        menu.addAction(a_dn)
        menu.addSeparator()
        a_rm = QAction(t("ctx_remove"), self)
        a_rm.triggered.connect(lambda: self._remove_row(row))
        a_rm.setEnabled(self.files[row].status != JobStatus.RUNNING)
        menu.addAction(a_rm)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _set_video_mode(self, row: int, mode: VideoMode | None) -> None:
        """Setzt den Video-Modus-Override einer Zeile (None = Global). Wird
        vom Encoder-Dropdown (COL_ENCODER) aufgerufen, das Encoder-Wahl und
        Video-Modus in einem Widget vereint (Copy als letzter Eintrag,
        analog zum globalen Encoder-Dropdown in der Toolbar)."""
        mf = self.files[row]
        if mf:
            mf.video_mode = mode
            # Ausgabedateiname spiegelt Copy vs. Encode wider (".copy.mkv"
            # statt ".x265.mkv"), daher Ausgabepfad neu berechnen.
            if mf.status in (JobStatus.READY, JobStatus.EXISTS):
                effective = mode or self._global_video_mode()
                out = mf.default_output(self._override_dir(), self._effective_target(mf),
                                       video_mode=effective,
                                       **self._output_kwargs(mf))
                mf.output_path = out
                self._set_out_item(row, out)


    def _build_audio_submenu(self, parent_menu: QMenu, row: int, mf: MediaFile) -> None:
        """Per audio stream: submenu to override the global audio mode
        (Global / Copy / AC3 / AAC) and, for transcoded streams, the
        target bitrate — independent of stream selection."""
        audio_menu = parent_menu.addMenu(t("ctx_audio_mode"))
        for a in mf.audio_streams:
            stream_menu = audio_menu.addMenu(a.label())
            group = QActionGroup(stream_menu)
            group.setExclusive(True)
            for choice, label_key in (
                (None, "audio_mode_global"),
                (AudioMode.COPY, "audio_mode_copy"),
                (AudioMode.AC3, "audio_mode_ac3"),
                (AudioMode.AAC, "audio_mode_aac"),
            ):
                act = QAction(t(label_key), stream_menu)
                act.setCheckable(True)
                act.setChecked(a.mode == choice)
                act.triggered.connect(
                    lambda checked, r=row, a=a, m=choice: self._set_audio_override(r, a, m))
                group.addAction(act)
                stream_menu.addAction(act)

            stream_menu.addSeparator()
            bitrate_menu = stream_menu.addMenu(t("ctx_audio_bitrate"))
            default_br = default_audio_bitrate(min(a.channels, 6))
            br_group = QActionGroup(bitrate_menu)
            br_group.setExclusive(True)
            auto_act = QAction(t("audio_bitrate_auto", kbps=default_br), bitrate_menu)
            auto_act.setCheckable(True)
            auto_act.setChecked(a.target_bitrate is None)
            auto_act.triggered.connect(
                lambda checked, r=row, a=a: self._set_audio_bitrate(r, a, None))
            br_group.addAction(auto_act)
            bitrate_menu.addAction(auto_act)
            bitrate_menu.addSeparator()
            for kbps in AUDIO_BITRATES_KBPS:
                act = QAction(f"{kbps} kb/s", bitrate_menu)
                act.setCheckable(True)
                act.setChecked(a.target_bitrate == kbps)
                act.triggered.connect(
                    lambda checked, r=row, a=a, k=kbps: self._set_audio_bitrate(r, a, k))
                br_group.addAction(act)
                bitrate_menu.addAction(act)

            stream_menu.addSeparator()
            channels_menu = stream_menu.addMenu(t("ctx_audio_channels"))
            default_ch = min(a.channels, 6)
            ch_group = QActionGroup(channels_menu)
            ch_group.setExclusive(True)
            auto_ch_act = QAction(t("audio_channels_auto", ch=default_ch), channels_menu)
            auto_ch_act.setCheckable(True)
            auto_ch_act.setChecked(a.target_channels is None)
            auto_ch_act.triggered.connect(
                lambda checked, r=row, a=a: self._set_audio_channels(r, a, None))
            ch_group.addAction(auto_ch_act)
            channels_menu.addAction(auto_ch_act)
            channels_menu.addSeparator()
            for ch in AUDIO_CHANNEL_OPTIONS:
                act = QAction(t(f"audio_channels_{ch}"), channels_menu)
                act.setCheckable(True)
                act.setChecked(a.target_channels == ch)
                act.triggered.connect(
                    lambda checked, r=row, a=a, c=ch: self._set_audio_channels(r, a, c))
                ch_group.addAction(act)
                channels_menu.addAction(act)

            stream_menu.addSeparator()
            drc_menu = stream_menu.addMenu(t("ctx_audio_drc"))
            drc_group = QActionGroup(drc_menu)
            drc_group.setExclusive(True)
            for level in AUDIO_DRC_LEVELS:
                label = t("drc_off") if level == 0.0 else f"{level:.1f}"
                act = QAction(label, drc_menu)
                act.setCheckable(True)
                act.setChecked(abs(a.drc - level) < 1e-6)
                act.triggered.connect(
                    lambda checked, r=row, a=a, lv=level: self._set_audio_drc(r, a, lv))
                drc_group.addAction(act)
                drc_menu.addAction(act)

    def _set_audio_override(self, row: int, stream: "AudioStream", mode: AudioMode | None) -> None:
        stream.mode = mode
        self._refresh_audio_button(row)

    def _set_audio_bitrate(self, row: int, stream: "AudioStream", kbps: int | None) -> None:
        stream.target_bitrate = kbps
        self._refresh_audio_button(row)

    def _set_audio_channels(self, row: int, stream: "AudioStream", channels: int | None) -> None:
        stream.target_channels = channels
        self._refresh_audio_button(row)

    def _set_audio_drc(self, row: int, stream: "AudioStream", level: float) -> None:
        stream.drc = level
        self._refresh_audio_button(row)

    def _refresh_audio_button(self, row: int) -> None:
        btn = self.table.cellWidget(row, COL_AUDIO)
        if isinstance(btn, AudioButton):
            btn.set_mode(btn._mode)  # re-render labels with the new override

    def _movable_neighbor(self, row: int, delta: int) -> int | None:
        """Nächste sichtbare, analysierte Zeile in Richtung delta;
        None, wenn Tausch nicht möglich (Rand oder laufender Job)."""
        if self.files[row] is None \
                or self.files[row].status == JobStatus.RUNNING:
            return None
        r = row + delta
        while 0 <= r < len(self.files):
            if not self.table.isRowHidden(r):
                if self.files[r] is None \
                        or self.files[r].status == JobStatus.RUNNING:
                    return None
                return r
            r += delta
        return None

    def _move_row(self, row: int, delta: int) -> None:
        other = self._movable_neighbor(row, delta)
        if other is None:
            return
        self.files[row], self.files[other] = self.files[other], self.files[row]
        self.row_paths[row], self.row_paths[other] = \
            self.row_paths[other], self.row_paths[row]
        self._render_row(row)
        self._render_row(other)
        # Wartende Jobs in der Encode-Queue mitziehen
        if self.encode_worker:
            self.encode_worker.remap_rows({row: other, other: row})

    def _reanalyze_crop(self, row: int) -> None:
        mf = self.files[row]
        self.table.item(row, COL_CROP).setText(t("crop_analyzing"))
        w = CropOnlyWorker(row, mf, self.settings.tools["ffmpeg"],
                           self.settings.crop_min_px)
        w.signals.finished.connect(self._crop_reanalyzed)
        w.signals.failed.connect(
            lambda r, m: self.table.item(r, COL_CROP).setText(t("crop_error")))
        w.signals.crop_progress.connect(self._crop_analysis_progress)
        self._start_job(w)

    def _crop_reanalyzed(self, row: int, crop: CropInfo) -> None:
        mf = self.files[row]
        mf.crop = crop
        self.table.item(row, COL_CROP).setText(str(crop))
        # Neuer Crop-Wert (Re-Analyse oder Übernahme aus der Crop-Vorschau)
        # soll auch angewendet werden — Checkbox aktivieren (falls Wert
        # gültig, s. _render_row) UND anhaken, statt den User das manuell
        # nachholen zu lassen.
        wrapper = self.table.cellWidget(row, COL_CROP_ON)
        cb = wrapper.findChild(QCheckBox) if wrapper else None
        if cb is not None:
            cb.setEnabled(crop.valid)
            cb.setChecked(crop.valid)   # triggert _crop_toggled -> mf.crop_enabled
        else:
            mf.crop_enabled = crop.valid
        self._style_crop_cell(row)
        self._update_target_cell(row)

    def _force_overwrite(self, row: int) -> None:
        mf = self.files[row]
        if not mf or mf.status != JobStatus.EXISTS:
            return
        mf.force_overwrite = True
        mf.status = JobStatus.READY
        item = self.table.item(row, COL_STATUS)
        if item:
            item.setText(status_t(JobStatus.READY))

    def _requeue_row(self, row: int) -> None:
        """Fertige/fehlgeschlagene Zeile erneut einreihbar machen, nachdem
        z. B. CRF/Ziel/Tune über den Qualitäts-Vergleich oder manuell
        geändert wurden. Erzwingt implizit das Überschreiben der zuvor
        erstellten Ausgabedatei (analog zu _force_overwrite)."""
        mf = self.files[row]
        if not mf or mf.status not in (JobStatus.DONE, JobStatus.ERROR):
            return
        mf.force_overwrite = True
        mf.status = JobStatus.READY
        self.table.removeCellWidget(row, COL_STATUS)
        self.table.setItem(row, COL_STATUS, QTableWidgetItem(status_t(JobStatus.READY)))

    def _show_crop_preview(self, row: int) -> None:
        mf = self.files[row]
        ffmpeg = self.settings.tools.get("ffmpeg")
        if not mf or not ffmpeg:
            return
        dlg = CropPreviewDialog(mf, ffmpeg, self)
        dlg.crop_applied.connect(lambda crop, r=row: self._crop_reanalyzed(r, crop))
        dlg.exec()

    def _show_quality_check(self, row: int) -> None:
        from qualitycheck import QualityCheckDialog
        mf = self.files[row]
        ffmpeg = self.settings.tools.get("ffmpeg")
        if not mf or not ffmpeg:
            return
        dlg = QualityCheckDialog(
            mf, ffmpeg,
            self._last_encoder_id,
            self.cmb_preset.currentText(),
            mf.crf, mf.tune or self.cmb_tune.currentData() or "none",
            self, ffprobe=self.settings.tools.get("ffprobe") or "")
        dlg.settings_applied.connect(
            lambda v, r=row: self._apply_quality_variant(r, v))
        dlg.exec()

    def _show_media_info(self, row: int) -> None:
        from mediainfo import MediaInfoDialog
        mf = self.files[row]
        ffprobe = self.settings.tools.get("ffprobe")
        if not mf or not ffprobe:
            return
        compare_path = mf.output_path if mf.output_path and mf.output_path.exists() else None
        dlg = MediaInfoDialog(mf.path, ffprobe, self, compare_path=compare_path)
        dlg.exec()

    def _show_apply_settings(self, row: int) -> None:
        ref_mf = self.files[row]
        if not ref_mf:
            return
        others = [(r, mf.path.name) for r, mf in enumerate(self.files) if mf and r != row]
        if not others:
            return
        dlg = _ApplySettingsDialog(ref_mf.path.name, others, self)
        if dlg.exec() != QDialog.Accepted:
            return
        opts = dlg.options()
        skipped_audio = 0
        for r in dlg.selected_rows():
            mf = self.files[r]
            if not mf:
                continue
            ok = apply_settings(mf, ref_mf, opts)
            if opts.audio and not ok:
                skipped_audio += 1
            self._render_row(r)
            if mf.status in (JobStatus.READY, JobStatus.EXISTS):
                out = mf.default_output(self._override_dir(), self._effective_target(mf),
                                       video_mode=self._effective_video_mode(mf),
                                       **self._output_kwargs(mf))
                mf.output_path = out
                self._set_out_item(r, out)
                mf.status = JobStatus.EXISTS if out.exists() else JobStatus.READY
                self.table.item(r, COL_STATUS).setText(status_t(mf.status))
        if skipped_audio:
            QMessageBox.information(
                self, t("apply_settings_title", name=ref_mf.path.name),
                t("apply_settings_audio_skipped", n=skipped_audio))

    def _apply_quality_variant(self, row: int, variant) -> None:
        """Gewählte Variante aus dem Qualitäts-Vergleich auf die Zeile übernehmen."""
        mf = self.files[row]
        if not mf:
            return
        mf.target = variant.target
        mf.crf = variant.crf
        mf.tune = variant.tune if variant.tune != "none" else ""
        mf.monochrome = variant.monochrome
        spn = self.table.cellWidget(row, COL_CRF)
        if isinstance(spn, QSpinBox):
            spn.setValue(variant.crf)
        mono_wrapper = self.table.cellWidget(row, COL_MONO)
        mono_cb = mono_wrapper.findChild(QCheckBox) if mono_wrapper else None
        if mono_cb is not None:
            mono_cb.setChecked(variant.monochrome)
        self._update_target_cell(row)
        self._update_tune_cell(row)
        # Ausgabepfad an neue Zielauflösung anpassen (wie _row_target_changed)
        if mf.status in (JobStatus.READY, JobStatus.EXISTS):
            out = mf.default_output(self._override_dir(), self._effective_target(mf),
                                   video_mode=self._effective_video_mode(mf),
                                   **self._output_kwargs(mf))
            mf.output_path = out
            self._set_out_item(row, out)

    def _remove_row(self, row: int) -> None:
        # Zeilenindizes bleiben stabil: Eintrag nur ausblenden statt löschen,
        # damit laufende Worker-Signale (row-basiert) gültig bleiben.
        mf = self.files[row]
        if mf.status == JobStatus.QUEUED and self.encode_worker:
            self.encode_worker.dequeue(row)
        mf.status = JobStatus.SKIPPED
        # Set to None so the path is no longer in the "existing" set —
        # otherwise re-adding the same file after removal would be blocked.
        self.files[row] = None
        self.table.setRowHidden(row, True)

    # ------------------------------------------------------- Encoding

    def _start(self) -> None:
        if self.encode_worker is None:
            self.encode_worker = EncodeWorker(
                self.settings.tools,
                self._last_encoder_id,
                self.cmb_target.currentText(),
                preset=self.cmb_preset.currentText(),
                tune=self.cmb_tune.currentData() or "none",
                audio_mode=self.cmb_audio_mode.currentData() or AudioMode.COPY,
                video_mode=self._global_video_mode())
            self.encode_worker.job_started.connect(self._job_started)
            self.encode_worker.job_progress.connect(self._job_progress)
            self.encode_worker.job_speed.connect(self._job_speed)
            self.encode_worker.job_finished.connect(self._job_finished)
            self.encode_worker.job_failed.connect(self._job_failed)
            self.encode_worker.start()
        enqueued = 0
        for r, mf in enumerate(self.files):
            if mf and mf.enabled and mf.status == JobStatus.READY:
                if mf.output_path and mf.output_path.exists() and not mf.force_overwrite:
                    mf.status = JobStatus.EXISTS
                    self.table.item(r, COL_STATUS).setText(status_t(JobStatus.EXISTS))
                    continue
                mf.force_overwrite = False  # Flag nach Prüfung zurücksetzen
                mf.status = JobStatus.QUEUED
                self.table.item(r, COL_STATUS).setText(status_t(JobStatus.QUEUED))
                self.encode_worker.enqueue(r, mf, mf.output_path)
                enqueued += 1
        if enqueued:
            self.btn_stop.setEnabled(True)
            self.btn_pause.setEnabled(sys.platform != "win32")
            self.btn_pause.setToolTip(
                "" if sys.platform != "win32" else t("tt_pause_unsupported"))
            if not self._timer.isActive():
                self._batch_t0 = _time.monotonic()
                self._jobs_done = 0
                self._jobs_total = 0
            self._jobs_total += enqueued

    def _is_paused(self) -> bool:
        return bool(self.encode_worker and self.encode_worker.is_paused())

    def _toggle_pause(self) -> None:
        if not self.encode_worker:
            return
        if self.encode_worker.is_paused():
            self.encode_worker.resume()
        else:
            self.encode_worker.pause()
        self.btn_pause.setText(t("btn_resume") if self._is_paused() else t("btn_pause"))

    def _stop(self) -> None:
        if self.encode_worker:
            self.encode_worker.resume()  # sonst bliebe der Prozess beim Kill hängen
            self.encode_worker.stop()
            self.encode_worker.wait(3000)
            self.encode_worker = None
        for r, mf in enumerate(self.files):
            if mf and mf.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                mf.status = JobStatus.READY
                self.table.item(r, COL_STATUS).setText(status_t(JobStatus.READY))
                self.table.removeCellWidget(r, COL_STATUS)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText(t("btn_pause"))
        self._timer.stop()
        self._jobs_done = 0
        self._jobs_total = 0
        self.lbl_time.setVisible(False)

    @staticmethod
    def _fmt_dur(secs: float) -> str:
        s = int(secs)
        h, m = divmod(s, 3600)
        m, s = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _tick_time(self) -> None:
        now = _time.monotonic()
        job_el = now - self._job_t0 if self._job_t0 else 0.0
        batch_el = now - self._batch_t0 if self._batch_t0 else 0.0

        # Restzeit: aktuellen Job über Fortschritt schätzen + Ø × verbleibende Jobs
        remaining = ""
        done = self._jobs_done
        total = self._jobs_total
        pending = max(total - done - 1, 0)  # -1 = laufender Job
        pct = self._current_pct
        # Restzeit des laufenden Jobs aus Fortschritt ableiten (min. 2% um Div/0 zu vermeiden)
        if pct >= 2.0 and job_el > 0:
            job_remaining = job_el * (100.0 - pct) / pct
        elif job_el > 0 and done > 0 and batch_el > 0:
            avg = batch_el / done
            job_remaining = max(avg - job_el, 0.0)
        else:
            job_remaining = 0.0
        rem = 0.0
        if (pct >= 2.0 or done > 0) and (job_remaining > 0 or pending > 0):
            if done > 0 and batch_el > 0:
                avg_past = batch_el / done
            elif job_el > 0 and pct >= 2.0:
                avg_past = job_el / pct * 100.0
            else:
                avg_past = 0.0
            rem = job_remaining + avg_past * pending

        current_job_num = min(done + 1, total)
        done_str = f"{current_job_num}/{total}" if total > 1 else ""
        job_rem_str = (f"  {t('time_job_rem', t=self._fmt_dur(job_remaining))}"
                       if job_remaining > 1.0 else "")
        job_str = f"{t('time_job')} {done_str}  {self._fmt_dur(job_el)}{job_rem_str}"
        batch_str = (f"  |  {t('time_total', t=self._fmt_dur(batch_el))}"
                     if total > 1 else "")
        remaining = (f"  {t('time_total_rem', t=self._fmt_dur(rem))}"
                     if rem > 0 and total > 1 else "")

        fps_str = f"  {self._current_fps:.1f} fps" if self._current_fps > 0 else ""

        if self._timer.isActive():
            self.lbl_time.setText(f"{job_str}{batch_str}{remaining}{fps_str}")
        else:
            self.lbl_time.setText(
                t("time_done", done=done_str, total=self._fmt_dur(batch_el)))

    def _job_started(self, row: int) -> None:
        from applog import log
        log(f"=== Start: {self.files[row].path.name} ===")
        self.files[row].status = JobStatus.RUNNING
        self._job_t0 = _time.monotonic()
        self._current_pct = 0.0
        self._current_fps = 0.0
        if not self._timer.isActive():
            self._batch_t0 = self._job_t0
            self._timer.start()
        self.lbl_time.setVisible(True)
        # Item-Text leeren, sonst scheint er unter dem Balken durch
        item = self.table.item(row, COL_STATUS)
        if item:
            item.setText("")
        pb = QProgressBar()
        pb.setRange(0, 100)
        self.table.setCellWidget(row, COL_STATUS, pb)

    def _job_speed(self, row: int, fps: float) -> None:
        self._current_fps = fps

    def _job_progress(self, row: int, pct: float, written: int) -> None:
        self._current_pct = pct
        w = self.table.cellWidget(row, COL_STATUS)
        if not isinstance(w, QProgressBar):
            return
        w.setValue(int(pct))
        if pct > 1 and written > 0:
            mf = self.files[row]
            # DV-Phase: written = hevc_out-Größe; gegen Video-Stream-Größe vergleichen.
            # Normal: written = finale MKV; gegen Gesamtdatei vergleichen.
            src = (mf.video_stream_size if mf and mf.video_stream_size
                   else (mf.path.stat().st_size if mf else 0))
            # DV-Progress läuft nur 5–90 % → written auf Vollspanne hochrechnen
            span = 85.0 if (mf and mf.hdr.name == "DOLBY_VISION") else 100.0
            base = 5.0  if (mf and mf.hdr.name == "DOLBY_VISION") else 0.0
            rel_pct = max((pct - base) / span, 0.001)
            est_bytes = written / rel_pct
            est_mb = est_bytes / 1_048_576
            try:
                ratio = f"  ({est_bytes / src * 100:.0f}%)" if src else ""
            except (OSError, ZeroDivisionError):
                ratio = ""
            w.setFormat(f"{int(pct)}%  ~{est_mb:.0f} MB{ratio}")
        else:
            w.setFormat("%p%")

    def _job_finished(self, row: int) -> None:
        from applog import log
        mf = self.files[row]
        log(f"=== Fertig: {mf.path.name} ===")
        mf.status = JobStatus.DONE
        self._jobs_done += 1
        self.table.removeCellWidget(row, COL_STATUS)
        label = t("status_done")
        try:
            dst = mf.output_path.stat().st_size if mf.output_path else 0
            src = mf.path.stat().st_size
            if dst and src:
                label = t("status_done_size", mb=dst / 1_048_576, pct=dst / src * 100)
        except OSError:
            pass
        self.table.setItem(row, COL_STATUS, QTableWidgetItem(label))
        if self._jobs_done >= self._jobs_total:
            self._timer.stop()
            self._tick_time()  # Endstand einmal aktualisieren

    def _job_failed(self, row: int, msg: str) -> None:
        from applog import log
        log(f"=== FEHLER: {self.files[row].path.name}: {msg} ===")
        self.files[row].status = JobStatus.ERROR
        self.files[row].error_msg = msg
        self.table.removeCellWidget(row, COL_STATUS)
        item = QTableWidgetItem(t("status_error"))
        item.setToolTip(msg)
        item.setForeground(QColor("red"))
        self.table.setItem(row, COL_STATUS, item)
        self._jobs_done += 1
        if self._jobs_done >= self._jobs_total:
            self._timer.stop()
            self._tick_time()

    def closeEvent(self, event) -> None:
        worker = self.encode_worker
        if worker is not None and worker.is_busy():
            mb = QMessageBox(self)
            mb.setWindowTitle(t("dlg_close_title"))
            mb.setText(t("dlg_close_text"))
            mb.setInformativeText(t("dlg_close_info"))
            btn_stop  = mb.addButton(t("btn_close_stop"),   QMessageBox.AcceptRole)
            btn_bg    = mb.addButton(t("btn_close_bg"),     QMessageBox.DestructiveRole)
            btn_abort = mb.addButton(t("btn_close_cancel"), QMessageBox.RejectRole)
            mb.setDefaultButton(btn_abort)
            mb.exec()
            clicked = mb.clickedButton()
            if clicked == btn_abort:
                event.ignore()
                return
            if clicked == btn_stop:
                self._stop()
            # btn_bg: ffmpeg läuft als Kindprozess weiter, App schließt sich
        elif worker is not None:
            # Kein Job aktiv: geparkten Worker-Thread sauber beenden,
            # sonst „QThread destroyed while still running"
            worker.stop()
            worker.wait(3000)
            self.encode_worker = None
        event.accept()
