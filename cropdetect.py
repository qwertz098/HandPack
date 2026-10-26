"""Autocrop: cropdetect über mehrere Samples, häufigster Wert gewinnt."""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

from models import CropInfo, MediaFile
from settings import subprocess_flags

_CROP_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")

SAMPLES = 5          # Anzahl Messpunkte
SAMPLE_SECONDS = 8   # Dauer je Messpunkt

# cropdetects "limit" als Bruchwert (0.0-1.0) statt fixem Integer (z. B. 24)
# angeben: ein absoluter Integer wird bei >8-Bit-Quellen (HDR10/DV-Master
# sind praktisch immer 10-Bit) je nach ffmpeg-Version unterschiedlich auf
# den größeren Wertebereich skaliert – manche Builds skalieren "24"
# proportional korrekt hoch, andere interpretieren ihn im falschen
# Wertebereich, wodurch der Schwellwert effektiv gegen 0 geht und praktisch
# nie mehr etwas als "schwarz genug" gilt (-> immer Vollbild erkannt, kein
# Crop, egal wie deutlich die Balken sind). Ein Bruchwert ist laut
# ffmpeg-Doku explizit bittiefen-unabhängig und über Versionen hinweg stabil.
_CROP_LIMIT = 24 / 255


def _apply_min_side(mf: MediaFile, w: int, h: int, x: int, y: int,
                    min_px: int) -> tuple[int, int, int, int]:
    """Seiten, an denen weniger als min_px abgeschnitten würden, bleiben
    unbeschnitten (kleine Ränder nicht croppen -> pixelgenaues FullHD/4K)."""
    if min_px <= 0:
        return w, h, x, y
    left, top = x, y
    right, bottom = mf.width - w - x, mf.height - h - y
    left, right = (0 if v < min_px else v for v in (left, right))
    top, bottom = (0 if v < min_px else v for v in (top, bottom))
    return mf.width - left - right, mf.height - top - bottom, left, top


def detect_crop(mf: MediaFile, ffmpeg: str, progress_cb=None,
                min_px: int = 0) -> CropInfo:
    dur = mf.duration or 600
    # Messpunkte zwischen 10% und 90% der Laufzeit verteilen (Intro/Abspann meiden)
    points = [dur * (0.1 + 0.8 * i / max(SAMPLES - 1, 1)) for i in range(SAMPLES)]
    counter: Counter[tuple[int, int, int, int]] = Counter()

    from applog import log, log_cmd
    matches_seen = 0
    for idx, t in enumerate(points):
        if progress_cb:
            progress_cb(idx, SAMPLES)
        cmd = [
            ffmpeg, "-hide_banner", "-nostats",
            "-ss", f"{t:.1f}", "-i", str(mf.path),
            "-t", str(SAMPLE_SECONDS),
            "-vf", f"cropdetect=limit={_CROP_LIMIT:.6f}:round=2:reset=0",
            "-an", "-sn", "-f", "null", "-",
        ]
        log_cmd(cmd)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=120, **subprocess_flags())
        except subprocess.TimeoutExpired:
            log(f"cropdetect {mf.path.name}: Sample bei {t:.1f}s Timeout")
            continue
        sample_matches = list(_CROP_RE.finditer(res.stderr))
        matches_seen += len(sample_matches)
        for m in sample_matches:
            w, h, x, y = map(int, m.groups())
            if w > 0 and h > 0:
                w, h, x, y = _apply_min_side(mf, w, h, x, y, min_px)
                counter[(w, h, x, y)] += 1
    if progress_cb:
        progress_cb(SAMPLES, SAMPLES)

    if not counter:
        # matches_seen == 0 heißt: der cropdetect-Filter hat GAR KEINE
        # "crop=..."-Zeile ins stderr geschrieben (Filter-/Build-Problem,
        # z. B. anderes Log-Level oder geänderte Filter-Ausgabe in einem
        # neueren ffmpeg-Build) — anders als "hat gemessen, aber Vollbild
        # erkannt" (matches_seen > 0, w/h dort aber <= 0).
        reason = "keine crop=-Zeilen im ffmpeg-Output (Filter/Build-Problem?)" \
            if matches_seen == 0 else "nur ungültige/leere Messwerte"
        log(f"cropdetect {mf.path.name}: keine Messwerte ({reason})")
        return CropInfo()

    # Häufigster Wert; bei Gleichstand der mit der größeren Fläche (konservativer)
    best = max(counter.items(), key=lambda kv: (kv[1], kv[0][0] * kv[0][1]))[0]
    w, h, x, y = best

    # Crop ignorieren, wenn er praktisch der Vollfläche entspricht (<8 px Differenz)
    if mf.width - w < 8 and mf.height - h < 8:
        log(f"cropdetect {mf.path.name}: Vollbild ({w}:{h}) – kein Crop")
        return CropInfo()
    log(f"cropdetect {mf.path.name}: {w}:{h}:{x}:{y}")
    return CropInfo(w=w, h=h, x=x, y=y)
