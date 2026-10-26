#!/usr/bin/env bash
# Extrahiert einen kurzen Schnipsel aus einer Quelldatei für Tests
# (z. B. Cropdetect-Debugging an einem HDR10/DV-Master, ohne die ganze
# ~50 GB-Datei zu brauchen). Nutzt Stream-Copy (-c copy) statt Neucodierung:
# schnell (Sekunden statt Minuten) UND verlustfrei inkl. HDR10/DV-Metadaten,
# die bei einer Neucodierung sonst verändert/verloren gehen könnten.
#
# Usage:
#   make_test_clip.sh <input> [start_seconds] [duration_seconds] [output]
#
# Beispiel (20s-Schnipsel ab 5 Minuten):
#   make_test_clip.sh "/input/downloads/.../Der.Elefantenmensch....mkv" 300 20
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <input> [start_seconds=300] [duration_seconds=20] [output]" >&2
    exit 1
fi

INPUT="$1"
START="${2:-300}"
DURATION="${3:-20}"
if [ $# -ge 4 ]; then
    OUTPUT="$4"
else
    BASE="$(basename "$INPUT")"
    OUTPUT="${BASE%.*}.clip_${START}s_${DURATION}s.mkv"
fi

if [ ! -f "$INPUT" ]; then
    echo "Datei nicht gefunden: $INPUT" >&2
    exit 1
fi

echo "Extrahiere ${DURATION}s ab ${START}s aus:"
echo "  $INPUT"
echo "nach:"
echo "  $OUTPUT"

# -ss VOR -i: schneller Keyframe-Seek (kann leicht vom exakten Zeitpunkt
# abweichen - bei Stream-Copy unvermeidbar, da nicht auf Nicht-Keyframes
# geschnitten werden kann; für Testzwecke irrelevant).
# -map 0: alle Streams (Video/Audio/Untertitel/RPU-Attachments) übernehmen,
# damit HDR10/DV-Metadaten im Schnipsel erhalten bleiben.
ffmpeg -hide_banner -y \
    -ss "$START" -i "$INPUT" \
    -t "$DURATION" \
    -map 0 -c copy \
    -avoid_negative_ts make_zero \
    "$OUTPUT"

echo "Fertig: $OUTPUT"
