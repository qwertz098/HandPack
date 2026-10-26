"""Tests für mediainfo.category_totals: Aggregation von Einzel-Streams zu
Kategorie-Summen (Video/Audio/Untertitel/Sonstiges) für den Original-vs-
Ergebnis-Vergleich im Media-Info-Dialog."""
from pathlib import Path

from mediainfo import MediaInfoResult, StreamSizeEntry, category_totals


def make_result(entries, total_bytes, other_bytes=0) -> MediaInfoResult:
    return MediaInfoResult(path=Path("x.mkv"), container="Matroska",
                           total_bytes=total_bytes, duration=60.0,
                           entries=entries, other_bytes=other_bytes,
                           other_pct=(other_bytes / total_bytes * 100) if total_bytes else 0.0)


def test_aggregates_multiple_audio_tracks_into_one_row():
    entries = [
        StreamSizeEntry("Video", 800, 80.0, False, category="video"),
        StreamSizeEntry("Audio #1", 100, 10.0, False, category="audio"),
        StreamSizeEntry("Audio #2", 100, 10.0, False, category="audio"),
    ]
    result = make_result(entries, total_bytes=1000)
    rows = {label: (size, pct) for label, size, pct, _color in category_totals(result)}

    # Video-Zeile
    assert any(size == 800 for size, _pct in rows.values())
    # Beide Audiospuren zusammen = 200
    assert any(size == 200 for size, _pct in rows.values())


def test_category_without_streams_is_omitted_except_other():
    """Keine Untertitel vorhanden -> keine Untertitel-Zeile (nicht mit 0
    aufgeführt), aber "Sonstiges" bleibt immer sichtbar (Container-Overhead
    kann > 0 sein, selbst ganz ohne Streams in dieser Kategorie)."""
    entries = [StreamSizeEntry("Video", 900, 90.0, False, category="video")]
    result = make_result(entries, total_bytes=1000, other_bytes=100)
    labels = [label for label, _size, _pct, _color in category_totals(result)]
    assert not any("Untertitel" in l or "Subtitle" in l for l in labels)
    assert len(category_totals(result)) == 2  # Video + Sonstiges


def test_percentages_relative_to_total_bytes():
    entries = [StreamSizeEntry("Video", 500, 50.0, False, category="video")]
    result = make_result(entries, total_bytes=1000)
    rows = category_totals(result)
    video = next(r for r in rows if r[0] and r[1] == 500)
    assert video[2] == 50.0


def test_other_bytes_added_to_other_category():
    entries = [
        StreamSizeEntry("Video", 500, 50.0, False, category="video"),
        StreamSizeEntry("Sonstiges: mjpeg", 50, 5.0, False, category="other"),
    ]
    result = make_result(entries, total_bytes=1000, other_bytes=100)
    rows = category_totals(result)
    other = next(r for r in rows if r[0] not in ("", ) and r[1] == 150)
    assert other[1] == 150  # 50 (mjpeg-Anhang) + 100 (Container-Overhead)
