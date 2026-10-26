"""HEVC-Encoder: Erkennung (mit Probe-Encode) und Kommando-Aufbau."""
from __future__ import annotations

import subprocess
from pathlib import Path

from models import AudioMode, HDRType, MediaFile, VideoMode, default_audio_bitrate, drc_filter_args
from settings import subprocess_flags

HW_CANDIDATES = [
    ("hevc_nvenc", "NVIDIA NVENC"),
    ("hevc_qsv", "Intel QuickSync"),
    ("hevc_vaapi", "VAAPI"),
    ("hevc_amf", "AMD AMF"),
    ("hevc_videotoolbox", "Apple VideoToolbox"),
]

ENCODER_LABELS = {"libx265": "Software (libx265)"} | dict(HW_CANDIDATES)


def detect_encoders(ffmpeg: str) -> list[str]:
    """Liefert nutzbare Encoder: libx265 plus per Probe-Encode verifizierte HW."""
    available = ["libx265"]
    try:
        res = subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
                             capture_output=True, text=True, timeout=20,
                             **subprocess_flags())
        compiled = res.stdout
    except Exception:
        return available

    for enc, _label in HW_CANDIDATES:
        if enc not in compiled:
            continue
        cmd = [ffmpeg, "-hide_banner", "-v", "error",
               "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.1"]
        if enc == "hevc_vaapi":
            cmd = [ffmpeg, "-hide_banner", "-v", "error",
                   "-vaapi_device", "/dev/dri/renderD128",
                   "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.1",
                   "-vf", "format=nv12,hwupload"]
        cmd += ["-frames:v", "1", "-c:v", enc, "-f", "null", "-"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30,
                               **subprocess_flags())
            if r.returncode == 0:
                available.append(enc)
        except Exception:
            pass
    return available


# Geschwindigkeits-Preset je HW-Encoder (libx265-Namen werden abgebildet)
_NVENC_PRESET = {
    "ultrafast": "p1", "superfast": "p1", "veryfast": "p2", "faster": "p3",
    "fast": "p4", "medium": "p5", "slow": "p6", "slower": "p7", "veryslow": "p7",
}
# QSV kennt kein ultrafast/superfast -> auf veryfast anheben
_QSV_PRESET = {
    "ultrafast": "veryfast", "superfast": "veryfast", "veryfast": "veryfast",
    "faster": "faster", "fast": "fast", "medium": "medium",
    "slow": "slow", "slower": "slower", "veryslow": "veryslow",
}

# Inhalts-Tuning. "grain" ist ein nativer x265-Tune; die übrigen Profile
# bilden wir über x265-Parameter ab (x265 kennt kein "animation").
_NATIVE_X265_TUNES = {"grain"}
_TUNE_X265_PARAMS = {
    "animation": ["bframes=8", "psy-rd=1.0", "aq-mode=3",
                  "aq-strength=0.8", "ref=6"],
    "liveaction": ["psy-rd=2.0", "aq-mode=3"],
}


def quality_args(encoder: str, crf: int, preset: str = "medium") -> list[str]:
    """CRF auf den passenden Qualitätsparameter des Encoders mappen."""
    if encoder == "libx265":
        return ["-crf", str(crf), "-preset", preset]
    if encoder == "hevc_nvenc":
        return ["-rc", "vbr", "-cq", str(crf), "-b:v", "0",
                "-preset", _NVENC_PRESET.get(preset, "p5")]
    if encoder == "hevc_qsv":
        return ["-global_quality", str(crf),
                "-preset", _QSV_PRESET.get(preset, "medium")]
    if encoder == "hevc_vaapi":
        return ["-rc_mode", "CQP", "-qp", str(crf)]
    if encoder == "hevc_amf":
        return ["-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf)]
    if encoder == "hevc_videotoolbox":
        # VT hat keinen CRF; q:v 1-100 (höher = besser), grobe Abbildung
        q = max(1, min(100, 100 - crf * 2))
        return ["-q:v", str(q)]
    return ["-crf", str(crf)]


def build_video_filter(mf: MediaFile, target: str, hw_vaapi: bool) -> str:
    parts: list[str] = []
    if mf.crop_enabled and mf.crop.valid:
        c = mf.crop
        parts.append(f"crop={c.w}:{c.h}:{c.x}:{c.y}")
    tw, th = mf.compute_target_size(target)
    src_w, src_h = mf.effective_source_rect()
    if (tw, th) != (src_w, src_h):
        parts.append(f"scale={tw}:{th}:flags=lanczos")
    if hw_vaapi:
        parts.append("format=nv12|p010le,hwupload")
    return ",".join(parts)


def _color_flags(mf: MediaFile) -> list[str]:
    """HDR10/HLG-Farbsignalisierung (für alle Encoder gleich)."""
    if mf.hdr in (HDRType.SDR,):
        return []
    return [
        "-color_primaries", mf.color_primaries or "bt2020",
        "-color_trc", mf.color_transfer or "smpte2084",
        "-colorspace", mf.color_space or "bt2020nc",
    ]


def _x265_param_list(mf: MediaFile, tune: str) -> list[str]:
    """Sammelt alle x265-Parameter (HDR + nicht-natives Tune-Psy) zu einer
    Liste, damit nur EIN -x265-params-Flag entsteht (mehrere überschreiben sich)."""
    params: list[str] = []
    if mf.hdr not in (HDRType.SDR,):
        if mf.hdr == HDRType.HLG:
            params.append("repeat-headers=1")  # HLG braucht kein hdr10/MDM
        else:
            params += ["hdr10=1", "repeat-headers=1"]
            if mf.master_display:
                params.append(f"master-display={mf.master_display}")
            if mf.max_cll:
                params.append(f"max-cll={mf.max_cll}")
    params += _TUNE_X265_PARAMS.get(tune, [])
    return params


def tuning_args(mf: MediaFile, encoder: str, tune: str = "none") -> list[str]:
    """Farb-Signalisierung + Inhalts-Tuning je Encoder.
    libx265: nativer -tune (grain) bzw. x265-params; HW: nur Farb-Flags,
    NVENC zusätzlich spatial-aq, wenn ein Tune aktiv ist."""
    args = _color_flags(mf)
    if encoder == "libx265":
        if tune in _NATIVE_X265_TUNES:
            args += ["-tune", tune]
        params = _x265_param_list(mf, tune)
        if params:
            args += ["-x265-params", ":".join(params)]
    elif encoder == "hevc_nvenc" and tune not in ("none", ""):
        args += ["-spatial-aq", "1"]
    # statische HDR-Metadaten reicht ffmpeg ab Version 6 für nvenc/qsv durch.
    return args


_AC3_CODECS = {"ac3", "eac3"}
_AAC_CODECS = {"aac"}


def audio_args(mf: MediaFile, global_mode: AudioMode) -> list[str]:
    """Per-stream audio codec args. Each stream uses its own override
    (AudioStream.mode) if set, otherwise falls back to global_mode.
    A stream is only passed through as "copy" if its codec already matches
    the target AND no channel/DRC override forces a re-encode.
    Also used by dovi.py's DV mux step (inject_and_mux) — mkvmerge can only
    copy audio, not transcode, so the DV pipeline needs this same per-stream
    decision to know when it must fall back to an ffmpeg-based mux instead."""
    args: list[str] = []
    audio_idx = 0  # output audio stream counter
    for a in mf.audio_streams:
        if not a.selected:
            continue
        mode = a.mode or global_mode
        if mode == AudioMode.COPY:
            args += [f"-c:a:{audio_idx}", "copy"]
        else:
            target_codec = "ac3" if mode == AudioMode.AC3 else "aac"
            copy_set = _AC3_CODECS if mode == AudioMode.AC3 else _AAC_CODECS
            needs_reencode = (a.target_channels is not None) or (a.drc > 0.0)
            if a.codec in copy_set and not needs_reencode:
                args += [f"-c:a:{audio_idx}", "copy"]
            else:
                ch = a.target_channels or min(a.channels, 6)  # cap at 5.1
                bitrate = a.target_bitrate or default_audio_bitrate(ch)
                args += [
                    f"-c:a:{audio_idx}", target_codec,
                    f"-ac:a:{audio_idx}", str(ch),
                    f"-b:a:{audio_idx}", f"{bitrate}k",
                ]
                if a.drc > 0.0:
                    args += [f"-filter:a:{audio_idx}", drc_filter_args(a.drc)]
        audio_idx += 1
    return args or ["-c:a", "copy"]


def audio_needs_transcode(mf: MediaFile, global_mode: AudioMode) -> bool:
    """True, wenn mind. eine ausgewählte Spur tatsächlich transcodiert
    werden muss statt nur kopiert (per-stream, wie in audio_args())."""
    args = audio_args(mf, global_mode)
    for i, val in enumerate(args):
        if val.startswith("-c:a") and args[i + 1] != "copy":
            return True
    return False


def build_encode_command(
    mf: MediaFile, ffmpeg: str, encoder: str, target: str,
    output: Path, ten_bit: bool = True,
    preset: str = "medium", tune: str = "none",
    audio_mode: AudioMode = AudioMode.COPY,
    video_mode: VideoMode = VideoMode.ENCODE,
    monochrome: bool = False,
) -> list[str]:
    """Vollständiges ffmpeg-Kommando (ohne DV-Pipeline) für Encode nach MKV.
    video_mode=COPY überspringt Encoder/Filter/Crop/Ziel/Tune komplett und
    übernimmt den Video-Stream unverändert (z. B. für reines Audio-Remux)."""
    hw_vaapi = encoder == "hevc_vaapi" and video_mode == VideoMode.ENCODE
    cmd = [ffmpeg, "-hide_banner", "-y", "-nostats",
           "-progress", "pipe:1"]
    if hw_vaapi:
        cmd += ["-vaapi_device", "/dev/dri/renderD128"]
    cmd += ["-i", str(mf.path)]

    # Mapping: Video, gewählte Audios, alle Untertitel, Attachments
    cmd += ["-map", "0:v:0"]
    for a in mf.audio_streams:
        if a.selected:
            cmd += ["-map", f"0:{a.index}"]
    cmd += ["-map", "0:s?", "-map", "0:t?"]

    if video_mode == VideoMode.COPY:
        # -vf/-c:v <encoder> lässt sich nicht mit Streamcopy kombinieren
        # ("Filtering and streamcopy cannot be used together") – Crop/Ziel/
        # Tune sind bei reinem Copy ohnehin nicht anwendbar.
        cmd += ["-c:v", "copy"]
    else:
        vf = build_video_filter(mf, target, hw_vaapi)
        if vf:
            cmd += ["-vf", vf]

        cmd += ["-c:v", encoder]
        cmd += quality_args(encoder, mf.crf, preset)

        # Pixelformat / Bittiefe
        want_10 = ten_bit and (mf.hdr != HDRType.SDR or mf.bit_depth >= 10)
        if not hw_vaapi:
            if encoder == "libx265" and monochrome:
                # Kein Chroma-Sampling nötig -> HEVC-Monochrome-Profil statt
                # 4:2:0; x265 wählt das automatisch anhand des Pixelformats
                # (kein extra -x265-params nötig). Spart bei echtem
                # Schwarz-Weiß-Material spürbar mehr Bitrate als jedes
                # Tune-Preset, weil strukturell weniger zu codieren ist.
                cmd += ["-pix_fmt", "gray10le" if want_10 else "gray"]
            elif encoder == "libx265":
                cmd += ["-pix_fmt", "yuv420p10le" if want_10 else "yuv420p"]
            elif encoder in ("hevc_nvenc", "hevc_qsv"):
                cmd += ["-pix_fmt", "p010le" if want_10 else "yuv420p"]
            elif encoder == "hevc_videotoolbox" and want_10:
                cmd += ["-pix_fmt", "p010le"]

        cmd += tuning_args(mf, encoder, tune)

    cmd += audio_args(mf, audio_mode)
    cmd += ["-c:s", "copy", "-c:t", "copy",
            "-max_interleave_delta", "0",
            str(output)]
    return cmd
