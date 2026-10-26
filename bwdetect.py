"""Erkennt, ob eine Quelle praktisch farblos (Schwarz-Weiß) ist, per
ffmpeg-signalstats-Filter (durchschnittliche Sättigung über mehrere
Sample-Punkte) – analog zu cropdetect.py, nur mit SATAVG statt crop=."""
from __future__ import annotations

import re
import subprocess

from models import MediaFile
from settings import subprocess_flags

_SATAVG_RE = re.compile(r"lavfi\.signalstats\.SATAVG=([\d.]+)")

SAMPLES = 3          # Anzahl Messpunkte
SAMPLE_SECONDS = 4   # Dauer je Messpunkt

# SATAVG liegt auf einer 0..255-Skala (ffmpeg normalisiert intern auch bei
# höherer Bittiefe dorthin, anders als cropdetects "limit" ist hier kein
# Bittiefen-Skalierungsproblem zu erwarten). Echtes Farbmaterial liegt
# üblicherweise deutlich über 10; kompressionsbedingtes Farbrauschen in
# eigentlich farblosem Material bleibt meist unter diesem Schwellwert.
SATURATION_THRESHOLD = 2.0


def is_grayscale(mf: MediaFile, ffmpeg: str) -> bool:
    dur = mf.duration or 600
    # Messpunkte zwischen 20% und 80% der Laufzeit (Intro/Abspann meiden,
    # die z. B. bei Farbfilmen mit S/W-Rückblenden nicht repräsentativ wären)
    points = [dur * (0.2 + 0.6 * i / max(SAMPLES - 1, 1)) for i in range(SAMPLES)]
    values: list[float] = []

    from applog import log, log_cmd
    for t in points:
        cmd = [
            ffmpeg, "-hide_banner", "-nostats",
            "-ss", f"{t:.1f}", "-i", str(mf.path),
            "-t", str(SAMPLE_SECONDS),
            "-vf", "signalstats,metadata=print:key=lavfi.signalstats.SATAVG",
            "-an", "-sn", "-f", "null", "-",
        ]
        log_cmd(cmd)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=60, **subprocess_flags())
        except subprocess.TimeoutExpired:
            continue
        values += [float(v) for v in _SATAVG_RE.findall(res.stderr)]

    if not values:
        log(f"bwdetect {mf.path.name}: keine Messwerte")
        return False
    avg = sum(values) / len(values)
    grayscale = avg < SATURATION_THRESHOLD
    log(f"bwdetect {mf.path.name}: Ø-Sättigung {avg:.2f}"
        f" -> {'Schwarz/Weiß' if grayscale else 'Farbe'}")
    return grayscale
