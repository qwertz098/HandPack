"""Tests für models.apply_settings/apply_audio_overrides: Übertragen von
Zeileneinstellungen (Audio-Overrides, Crop-Enabled, Ziel, Tune, CRF,
Video-Modus) von einer Referenzdatei auf andere - für Batches sehr
ähnlicher Dateien (z. B. Serienstaffel)."""
from pathlib import Path

from models import (AudioMode, AudioStream, CropInfo, MediaFile,
                    SettingsCopyOptions, VideoMode, apply_audio_overrides,
                    apply_settings)


def make_mf(n_audio=2, **overrides) -> MediaFile:
    defaults = dict(
        path=Path("x.mkv"),
        audio_streams=[AudioStream(index=i + 1, codec="aac", channels=2,
                                   selected=True) for i in range(n_audio)],
    )
    defaults.update(overrides)
    return MediaFile(**defaults)


def test_apply_audio_overrides_copies_selection_and_mode_by_index():
    src = make_mf(n_audio=2)
    src.audio_streams[0].selected = False
    src.audio_streams[1].mode = AudioMode.AC3
    src.audio_streams[1].drc = 2.0
    dst = make_mf(n_audio=2)

    ok = apply_audio_overrides(dst, src)

    assert ok
    assert dst.audio_streams[0].selected is False
    assert dst.audio_streams[1].mode == AudioMode.AC3
    assert dst.audio_streams[1].drc == 2.0


def test_apply_audio_overrides_refuses_on_track_count_mismatch():
    """Unterschiedliche Spurzahl -> nichts übernehmen, um Overrides nicht
    auf eine falsche Spur zu übertragen."""
    src = make_mf(n_audio=3)
    dst = make_mf(n_audio=2)
    original = [s.selected for s in dst.audio_streams]

    ok = apply_audio_overrides(dst, src)

    assert not ok
    assert [s.selected for s in dst.audio_streams] == original


def test_apply_settings_copies_all_requested_aspects():
    src = make_mf(n_audio=1, target="1080p", tune="grain", crf=18,
                  video_mode=VideoMode.COPY,
                  crop=CropInfo(w=1920, h=800, x=0, y=140), crop_enabled=False)
    dst = make_mf(n_audio=1, target="", tune="", crf=23,
                  video_mode=VideoMode.ENCODE, crop_enabled=True)

    ok = apply_settings(dst, src, SettingsCopyOptions())

    assert ok
    assert dst.target == "1080p"
    assert dst.tune == "grain"
    assert dst.crf == 18
    assert dst.video_mode == VideoMode.COPY
    assert dst.crop_enabled is False


def test_apply_settings_respects_opt_flags_partial_selection():
    """Nur CRF soll übernommen werden - alles andere bleibt unangetastet."""
    src = make_mf(n_audio=1, target="2160p", tune="animation", crf=16)
    dst = make_mf(n_audio=1, target="720p", tune="none", crf=23)

    opts = SettingsCopyOptions(audio=False, crop_enabled=False, target=False,
                               tune=False, crf=True, video_mode=False)
    apply_settings(dst, src, opts)

    assert dst.crf == 16
    assert dst.target == "720p"   # unverändert
    assert dst.tune == "none"     # unverändert


def test_apply_settings_audio_mismatch_does_not_block_other_fields():
    """Abweichende Audiospurzahl blockiert nur die Audio-Übernahme, nicht
    die anderen angeforderten Felder (CRF etc.)."""
    src = make_mf(n_audio=3, crf=16)
    dst = make_mf(n_audio=1, crf=23)

    ok = apply_settings(dst, src, SettingsCopyOptions())

    assert not ok
    assert dst.crf == 16  # trotzdem übernommen
