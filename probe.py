"""ffprobe-Analyse: Auflösung, Streams, HDR/DV-Erkennung."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from models import ATMOS_CODECS, AudioStream, HDRType, MediaFile, SubtitleStream
from settings import subprocess_flags


def probe_file(path: Path, ffprobe: str) -> MediaFile:
    mf = MediaFile(path=path)
    cmd = [
        ffprobe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams",
        "-show_frames", "-read_intervals", "%+#1",  # 1. Frame für side_data (DV/HDR10+)
        str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                         **subprocess_flags())
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe fehlgeschlagen: {res.stderr[:200]}")
    data = json.loads(res.stdout or "{}")

    fmt = data.get("format", {})
    mf.duration = float(fmt.get("duration", 0) or 0)

    video_seen = False
    for s in data.get("streams", []):
        ctype = s.get("codec_type")
        if ctype == "video" and not video_seen:
            # Cover-Art (mjpeg attached_pic) überspringen
            if s.get("disposition", {}).get("attached_pic"):
                continue
            video_seen = True
            mf.width = int(s.get("width", 0) or 0)
            mf.height = int(s.get("height", 0) or 0)
            mf.video_codec = s.get("codec_name", "")
            mf.pix_fmt = s.get("pix_fmt", "") or ""
            mf.bit_depth = 10 if "10" in mf.pix_fmt else (12 if "12" in mf.pix_fmt else 8)
            mf.frame_rate = s.get("r_frame_rate", "")
            try:
                vbr = int(s.get("bit_rate") or 0)
                if vbr and mf.duration:
                    mf.video_stream_size = int(vbr / 8 * mf.duration)
            except (ValueError, TypeError):
                pass
            mf.color_primaries = s.get("color_primaries", "") or ""
            mf.color_transfer = s.get("color_transfer", "") or ""
            mf.color_space = s.get("color_space", "") or ""
            if not mf.duration:
                mf.duration = float(s.get("duration", 0) or 0)
            _detect_hdr(mf, s)
        elif ctype == "audio":
            codec = s.get("codec_name", "")
            # Atmos: TrueHD or E-AC3 with "Atmos" in the title tag
            title = s.get("tags", {}).get("title", "") or ""
            atmos = codec in ATMOS_CODECS and "atmos" in title.lower()
            mf.audio_streams.append(AudioStream(
                index=int(s.get("index", 0)),
                codec=codec,
                language=s.get("tags", {}).get("language", ""),
                channels=int(s.get("channels", 0) or 0),
                bitrate=int(int(s.get("bit_rate") or
                            s.get("tags", {}).get("BPS") or 0) / 1000),
                title=title,
                atmos=atmos,
            ))
        elif ctype == "subtitle":
            mf.subtitle_streams.append(SubtitleStream(
                index=int(s.get("index", 0)),
                codec=s.get("codec_name", ""),
                language=s.get("tags", {}).get("language", ""),
                title=s.get("tags", {}).get("title", ""),
            ))

    # Frame-side_data prüfen (DV RPU, HDR10+ dynamische Metadaten, Mastering-Display)
    for frame in data.get("frames", []):
        for sd in frame.get("side_data_list", []):
            t = (sd.get("side_data_type") or "").lower()
            if "dolby vision" in t or "dovi" in t:
                _mark_dv(mf, sd)
            elif "hdr dynamic metadata" in t or "hdr10+" in t:
                if mf.hdr == HDRType.HDR10:
                    mf.hdr = HDRType.HDR10PLUS
            elif "mastering display" in t:
                mf.master_display = _mastering_string(sd)
            elif "content light level" in t:
                mx = sd.get("max_content", 0)
                mavg = sd.get("max_average", 0)
                if mx:
                    mf.max_cll = f"{mx},{mavg}"
    return mf


def _detect_hdr(mf: MediaFile, stream: dict) -> None:
    trc = (stream.get("color_transfer") or "").lower()
    if trc in ("smpte2084", "smpte st 2084"):
        mf.hdr = HDRType.HDR10
    elif trc in ("arib-std-b67",):
        mf.hdr = HDRType.HLG
    # DV configuration record im Stream-side_data
    for sd in stream.get("side_data_list", []) or []:
        t = (sd.get("side_data_type") or "").lower()
        if "dovi" in t or "dolby vision" in t:
            _mark_dv(mf, sd)
        elif "mastering display" in t:
            mf.master_display = _mastering_string(sd)
        elif "content light level" in t:
            mx = sd.get("max_content", 0)
            mavg = sd.get("max_average", 0)
            if mx:
                mf.max_cll = f"{mx},{mavg}"


def _mark_dv(mf: MediaFile, sd: dict) -> None:
    mf.hdr = HDRType.DOLBY_VISION
    prof = sd.get("dv_profile")
    if prof is not None:
        try:
            mf.dv_profile = int(prof)
        except (TypeError, ValueError):
            pass


def _frac(v) -> float:
    """ffprobe liefert '34000/50000' oder Zahlen."""
    if isinstance(v, str) and "/" in v:
        n, d = v.split("/")
        return float(n) / float(d) if float(d) else 0.0
    return float(v or 0)


def _mastering_string(sd: dict) -> str:
    """Baut den x265 master-display-String aus ffprobe-Daten."""
    try:
        def gxy(p):  # in x265-Einheiten (0.00002)
            return (round(_frac(sd[f"{p}_x"]) * 50000),
                    round(_frac(sd[f"{p}_y"]) * 50000))
        gx, gy = gxy("green")
        bx, by = gxy("blue")
        rx, ry = gxy("red")
        wx, wy = gxy("white_point")
        lmax = round(_frac(sd["max_luminance"]) * 10000)
        lmin = round(_frac(sd["min_luminance"]) * 10000)
        return (f"G({gx},{gy})B({bx},{by})R({rx},{ry})"
                f"WP({wx},{wy})L({lmax},{lmin})")
    except (KeyError, ValueError, ZeroDivisionError):
        return ""


def collect_video_files(paths: list[Path]) -> list[Path]:
    """Dateien direkt, Ordner rekursiv nach Videodateien durchsuchen."""
    from models import VIDEO_EXTENSIONS
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out.extend(sorted(
                f for f in p.rglob("*")
                if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
            ))
        elif p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            out.append(p)
    # Duplikate entfernen, Reihenfolge erhalten
    seen: set[Path] = set()
    uniq = []
    for p in out:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    return uniq
