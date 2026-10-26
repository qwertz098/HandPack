"""Datenmodell für die Transcoder-App."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".m4v", ".mov", ".avi", ".ts", ".m2ts", ".mts",
    ".wmv", ".webm", ".flv", ".mpg", ".mpeg", ".vob",
}


class HDRType(Enum):
    SDR = "SDR"
    HDR10 = "HDR10"
    HDR10PLUS = "HDR10+"
    HLG = "HLG"
    DOLBY_VISION = "DV"


class JobStatus(Enum):
    ANALYZING = "Analysiere…"
    READY = "Bereit"
    QUEUED = "In Warteschlange"
    RUNNING = "Läuft"
    DONE = "Fertig"
    ERROR = "Fehler"
    SKIPPED = "Übersprungen"
    EXISTS = "Ziel existiert!"


# Sonderziel: Auflösung der Quelle unverändert übernehmen
TARGET_ORIGINAL = "Original"

# Zielauflösungen: (Breite, Höhe) der 16:9-Referenz
TARGET_RESOLUTIONS = {
    TARGET_ORIGINAL: None,
    "576p": (720, 576),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "2160p": (3840, 2160),
}

# Geschwindigkeits-Presets (libx265-Namen; HW-Encoder werden gemappt)
ENCODE_PRESETS = [
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow",
]
DEFAULT_PRESET = "medium"

# Inhalts-Tuning. Schlüssel "none" = ohne Tuning.
# Wirkt voll nur bei libx265; HW-Encoder ignorieren es weitgehend.
TUNE_PROFILES = {
    "none": "Standard",
    "grain": "Film / Grain",
    "animation": "Animation",
    "liveaction": "Live-Action",
}
DEFAULT_TUNE = "none"


class VideoMode(Enum):
    ENCODE = "encode"   # normale Neucodierung (Encoder/CRF/Ziel/Tune wirken)
    COPY = "copy"       # Video-Stream unverändert übernehmen (nur Remux/Audio-Only)


class AudioMode(Enum):
    COPY = "copy"       # pass through unchanged
    AC3  = "ac3"        # transcode → AC3 (max 5.1), copy if already AC3
    AAC  = "aac"        # transcode → AAC (max 5.1), copy if already AAC


# Codecs that count as "already AC3 / AAC" — no re-encode needed
_AC3_CODECS = {"ac3", "eac3"}   # eac3 = DD+; passthrough as-is when mode=COPY
_AAC_CODECS = {"aac"}

def audio_conversion_tag(mf: "MediaFile", global_mode: "AudioMode") -> str:
    """Kurzes Namens-Tag für tatsächlich gewandelte (nicht kopierte)
    Audiospuren, z. B. "AC3" oder "AAC" – für den Ausgabedateinamen, damit
    auf einen Blick erkennbar ist, ob/wohin die Tonspur umgewandelt wurde.
    Leer, wenn alle ausgewählten Spuren im Zielcodec bleiben (Copy)."""
    tags: set[str] = set()
    for a in mf.audio_streams:
        if not a.selected:
            continue
        mode = a.mode or global_mode
        if mode == AudioMode.AC3:
            copy_set, target = _AC3_CODECS, "AC3"
        elif mode == AudioMode.AAC:
            copy_set, target = _AAC_CODECS, "AAC"
        else:
            continue
        needs_reencode = (a.target_channels is not None) or (a.drc > 0.0)
        if a.codec in copy_set and not needs_reencode:
            continue  # bereits im Zielcodec -> wird kopiert, kein Tag nötig
        tags.add(target)
    return "+".join(sorted(tags))


@dataclass
class SettingsCopyOptions:
    """Welche Aspekte beim Übertragen von Zeileneinstellungen (Kontextmenü
    "Einstellungen auf andere Zeilen übertragen…") mitgenommen werden."""
    audio: bool = True
    crop_enabled: bool = True
    target: bool = True
    tune: bool = True
    crf: bool = True
    video_mode: bool = True


def apply_audio_overrides(dst: "MediaFile", src: "MediaFile") -> bool:
    """Kopiert Audiospur-Auswahl/-Overrides (selected/mode/target_bitrate/
    target_channels/drc) von src nach dst, per Index gematcht (keine Sprach-
    /Codec-Heuristik – bei einer Batch sehr ähnlicher Dateien liegt meist
    dieselbe Spurreihenfolge vor). Bei abweichender Spurzahl wird NICHTS
    geändert (False), um keine Overrides auf die falsche Spur zu übertragen."""
    if len(dst.audio_streams) != len(src.audio_streams):
        return False
    for d, s in zip(dst.audio_streams, src.audio_streams):
        d.selected = s.selected
        d.mode = s.mode
        d.target_bitrate = s.target_bitrate
        d.target_channels = s.target_channels
        d.drc = s.drc
    return True


def apply_settings(dst: "MediaFile", src: "MediaFile",
                   opts: SettingsCopyOptions) -> bool:
    """Wendet die in opts ausgewählten Einstellungen von src auf dst an.
    Gibt False zurück, wenn Audio angefordert war, aber die Spurzahl nicht
    übereinstimmt (andere angeforderte Felder werden trotzdem übernommen –
    das Audio-Mismatch soll den Rest nicht blockieren)."""
    ok = True
    if opts.audio:
        ok = apply_audio_overrides(dst, src)
    if opts.crop_enabled:
        dst.crop_enabled = src.crop_enabled
    if opts.target:
        dst.target = src.target
    if opts.tune:
        dst.tune = src.tune
    if opts.crf:
        dst.crf = src.crf
    if opts.video_mode:
        dst.video_mode = src.video_mode
    return ok


# Selectable target bitrates (kbps) for AC3/AAC transcoding, offered in the
# per-track bitrate dropdown. Default picked automatically from channel
# count (<=2ch -> 192, >=3ch -> 384) unless a stream has an explicit override.
AUDIO_BITRATES_KBPS = [96, 128, 160, 192, 224, 256, 320, 384, 448, 640]


def default_audio_bitrate(channels: int) -> int:
    """Default target bitrate (kbps) for AC3/AAC transcoding by channel count."""
    return 192 if channels <= 2 else 384


# Selectable target channel counts for AC3/AAC transcoding. "Auto" keeps the
# source channel count (capped at 6 / 5.1, AC3/AAC's practical ceiling).
AUDIO_CHANNEL_OPTIONS = [1, 2, 6]  # mono, stereo, 5.1

# Dynamic Range Compression levels for AC3/AAC transcoding, modeled after
# HandBrake's DRC slider (0.0 = off, 1.0..4.0 = increasing compression).
# Implemented via ffmpeg's "acompressor" filter — not the same algorithm as
# HandBrake's, but serves the same purpose (quieter dialogue louder, loud
# peaks tamed, useful for night-time / low-volume listening).
AUDIO_DRC_LEVELS = [0.0, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]


def drc_filter_args(drc: float) -> str:
    """Maps a HandBrake-style DRC level (0..4) to an ffmpeg acompressor filter
    string. 0.0 -> no filter (caller should skip). Ratio scales roughly
    linearly with the level; threshold/attack/release are fixed, sensible
    defaults for dialogue-preserving compression."""
    ratio = max(1.0, drc * 5.0)
    return f"acompressor=ratio={ratio:.1f}:threshold=-24dB:attack=5:release=250:makeup=2"


# Codecs that carry Atmos / DTS:X object audio (base layer survives, objects lost)
ATMOS_CODECS = {"truehd", "eac3"}   # TrueHD+Atmos, DD+Atmos
DTSX_CODECS  = {"dts"}              # DTS:X (profile 2 — not detectable from codec alone)


@dataclass
class AudioStream:
    index: int            # Stream-Index in der Datei (ffmpeg 0:N)
    codec: str = ""
    language: str = ""
    channels: int = 0
    bitrate: int = 0   # kb/s, 0 = unbekannt
    title: str = ""
    atmos: bool = False  # TrueHD+Atmos or DD+Atmos detected
    selected: bool = True
    mode: Optional["AudioMode"] = None  # per-stream override; None = follow global mode
    target_bitrate: Optional[int] = None  # kbps override for AC3/AAC transcode; None = auto default
    target_channels: Optional[int] = None  # channel-count override; None = auto (source, capped at 6)
    drc: float = 0.0  # HandBrake-style Dynamic Range Compression level, 0 = off

    def label(self) -> str:
        parts = [f"#{self.index}", self.codec]
        if self.atmos:
            parts.append("Atmos")
        if self.language:
            parts.append(self.language)
        if self.channels:
            parts.append(f"{self.channels}ch")
        if self.bitrate:
            parts.append(f"{self.bitrate}k")
        if self.title:
            parts.append(self.title)
        return " ".join(p for p in parts if p)


@dataclass
class SubtitleStream:
    index: int
    codec: str = ""
    language: str = ""
    title: str = ""


@dataclass
class CropInfo:
    w: int = 0
    h: int = 0
    x: int = 0
    y: int = 0

    @property
    def valid(self) -> bool:
        return self.w > 0 and self.h > 0

    def __str__(self) -> str:
        if not self.valid:
            return "—"
        return f"{self.w}:{self.h}:{self.x}:{self.y}"


@dataclass
class MediaFile:
    path: Path
    width: int = 0
    height: int = 0
    duration: float = 0.0
    video_codec: str = ""
    pix_fmt: str = ""
    bit_depth: int = 8
    frame_rate: str = ""
    hdr: HDRType = HDRType.SDR
    dv_profile: Optional[int] = None
    color_primaries: str = ""
    color_transfer: str = ""
    color_space: str = ""
    master_display: str = ""
    max_cll: str = ""
    audio_streams: list[AudioStream] = field(default_factory=list)
    subtitle_streams: list[SubtitleStream] = field(default_factory=list)
    crop: CropInfo = field(default_factory=CropInfo)
    crop_enabled: bool = True
    enabled: bool = True          # nimmt am Transcode teil (Checkbox-Spalte)
    target: str = ""              # Zielauflösung; leer = globale Einstellung
    tune: str = ""                # Inhalts-Tune; leer = globale Einstellung
    encoder: str = ""             # Encoder-ID (z. B. "libx265"); leer = globale Einstellung
    preset: str = ""              # Encoder-Preset; leer = globale Einstellung
    # Schwarz/Weiß-Encoding (HEVC-Monochrome-Profil, spart Chroma-Bits) -
    # unabhängig vom Content-Tune (Grain etc.) kombinierbar, daher eigenes
    # Feld statt eines Tune-Werts. Nur pro Zeile, kein globaler Schalter -
    # per Checkbox in der Tabelle gesetzt (manuell oder durch Autoerkennung
    # via bwdetect.is_grayscale beim Analysieren).
    monochrome: bool = False
    video_mode: Optional["VideoMode"] = None  # None = globale Einstellung
    video_stream_size: int = 0    # geschätzte Video-Stream-Größe in Bytes
    force_overwrite: bool = False # Zieldatei überschreiben auch wenn vorhanden
    crf: int = 20
    output_path: Optional[Path] = None
    status: JobStatus = JobStatus.ANALYZING
    progress: float = 0.0
    error_msg: str = ""

    def effective_source_rect(self) -> tuple[int, int]:
        """Bildfläche nach (optionalem) Crop."""
        if self.crop_enabled and self.crop.valid:
            return self.crop.w, self.crop.h
        return self.width, self.height

    def compute_target_size(self, target_name: str) -> tuple[int, int]:
        """16:9-Regel: breiter als 16:9 -> Breite fixieren, sonst Höhe fixieren.
        Niemals hochskalieren. Ergebnis auf gerade Werte gerundet."""
        src_w, src_h = self.effective_source_rect()
        if target_name == TARGET_ORIGINAL:
            out_w = src_w - src_w % 2
            out_h = src_h - src_h % 2
            return max(out_w, 2), max(out_h, 2)
        ref_w, ref_h = TARGET_RESOLUTIONS[target_name]
        if src_w <= 0 or src_h <= 0:
            return ref_w, ref_h
        aspect = src_w / src_h
        if aspect >= ref_w / ref_h:
            out_w = min(ref_w, src_w)
            out_h = round(out_w / aspect)
        else:
            out_h = min(ref_h, src_h)
            out_w = round(out_h * aspect)
        out_w -= out_w % 2
        out_h -= out_h % 2
        return max(out_w, 2), max(out_h, 2)

    def default_output(self, override_dir: Optional[Path],
                       target_label: str = "",
                       video_mode: Optional["VideoMode"] = None,
                       audio_mode: Optional["AudioMode"] = None,
                       name_tag: str = "") -> Path:
        suffix = f".{target_label}" if target_label and target_label != "Original" else ""
        # "x265" waere irrefuehrend, wenn das Video nur kopiert statt neu
        # codiert wird (z. B. bei reinem Audio-Umbau).
        codec_tag = "copy" if video_mode == VideoMode.COPY else "x265"
        a_tag = audio_conversion_tag(self, audio_mode) if audio_mode is not None else ""
        audio_suffix = f".{a_tag}" if a_tag else ""
        # Freies Nutzer-Kürzel ganz ans Ende, vor die Extension.
        tag_suffix = f".{name_tag.strip()}" if name_tag and name_tag.strip() else ""
        base = (self.path.stem + suffix + audio_suffix + f".{codec_tag}"
               + tag_suffix + ".mkv")
        if override_dir:
            return override_dir / base
        return self.path.parent / base

    def resolution_label(self) -> str:
        if self.width and self.height:
            return f"{self.width}×{self.height}"
        return "?"

    def hdr_label(self) -> str:
        if self.hdr == HDRType.DOLBY_VISION:
            p = f" P{self.dv_profile}" if self.dv_profile is not None else ""
            return f"DV{p}"
        return self.hdr.value
