"""Tests für reine Modell-Logik: CropInfo, Output-Pfad-Namensschema,
Zielauflösungs-Berechnung, DRC-Filter-Mapping."""
from pathlib import Path

from models import (AudioMode, AudioStream, CropInfo, HDRType, MediaFile,
                    VideoMode, audio_conversion_tag, drc_filter_args)


def test_cropinfo_default_is_invalid():
    assert not CropInfo().valid


def test_cropinfo_valid_needs_positive_w_and_h():
    assert CropInfo(w=1920, h=800, x=0, y=140).valid
    assert not CropInfo(w=0, h=800).valid
    assert not CropInfo(w=1920, h=0).valid


def test_cropinfo_str_roundtrip_format():
    c = CropInfo(w=1920, h=800, x=0, y=140)
    assert str(c) == "1920:800:0:140"
    assert str(CropInfo()) == "—"


def test_default_output_encode_mode_uses_x265_tag():
    mf = MediaFile(path=Path("/videos/Movie.mkv"))
    out = mf.default_output(None, "", VideoMode.ENCODE)
    assert out == Path("/videos/Movie.x265.mkv")


def test_default_output_copy_mode_uses_copy_tag_not_x265():
    """Ein reiner Video-Copy (z. B. nur Audio-Umbau) darf nicht ".x265.mkv"
    heißen - das wäre irreführend, da gar nicht neu codiert wird."""
    mf = MediaFile(path=Path("/videos/Movie.mkv"))
    out = mf.default_output(None, "", VideoMode.COPY)
    assert out == Path("/videos/Movie.copy.mkv")


def test_default_output_appends_target_label():
    mf = MediaFile(path=Path("/videos/Movie.mkv"))
    out = mf.default_output(None, "1080p", VideoMode.ENCODE)
    assert out.name == "Movie.1080p.x265.mkv"


def test_default_output_original_label_is_not_appended():
    mf = MediaFile(path=Path("/videos/Movie.mkv"))
    out = mf.default_output(None, "Original", VideoMode.ENCODE)
    assert out.name == "Movie.x265.mkv"


def test_default_output_override_dir_used_when_given():
    mf = MediaFile(path=Path("/videos/Movie.mkv"))
    out = mf.default_output(Path("/out"), "", VideoMode.ENCODE)
    assert out == Path("/out/Movie.x265.mkv")


def test_effective_source_rect_uses_crop_only_when_enabled_and_valid():
    mf = MediaFile(path=Path("x.mkv"), width=1920, height=1080,
                   crop=CropInfo(w=1920, h=800, x=0, y=140), crop_enabled=True)
    assert mf.effective_source_rect() == (1920, 800)

    mf.crop_enabled = False
    assert mf.effective_source_rect() == (1920, 1080)

    mf.crop_enabled = True
    mf.crop = CropInfo()  # invalid
    assert mf.effective_source_rect() == (1920, 1080)


def test_compute_target_size_never_upscales():
    """Quelle ist kleiner als das Ziel -> Zielauflösung darf NICHT
    hochskaliert werden, Ausgabe bleibt bei der Quellgröße (gerundet)."""
    mf = MediaFile(path=Path("x.mkv"), width=1280, height=720)
    w, h = mf.compute_target_size("2160p")
    assert w <= 1280 and h <= 720


def test_compute_target_size_downscales_widescreen_by_width():
    mf = MediaFile(path=Path("x.mkv"), width=3840, height=2160)
    w, h = mf.compute_target_size("1080p")
    assert w == 1920
    assert h % 2 == 0


def test_audio_conversion_tag_empty_when_copy_mode():
    mf = MediaFile(path=Path("x.mkv"), audio_streams=[
        AudioStream(index=1, codec="aac", channels=2, selected=True)])
    assert audio_conversion_tag(mf, AudioMode.COPY) == ""


def test_audio_conversion_tag_empty_when_already_target_codec():
    """Codec entspricht schon dem Ziel -> wird kopiert, kein Tag nötig."""
    mf = MediaFile(path=Path("x.mkv"), audio_streams=[
        AudioStream(index=1, codec="ac3", channels=6, selected=True)])
    assert audio_conversion_tag(mf, AudioMode.AC3) == ""


def test_audio_conversion_tag_set_when_actually_transcoded():
    mf = MediaFile(path=Path("x.mkv"), audio_streams=[
        AudioStream(index=1, codec="dts", channels=6, selected=True)])
    assert audio_conversion_tag(mf, AudioMode.AC3) == "AC3"


def test_audio_conversion_tag_channel_override_forces_tag_even_if_codec_matches():
    mf = MediaFile(path=Path("x.mkv"), audio_streams=[
        AudioStream(index=1, codec="ac3", channels=6, selected=True,
                   target_channels=2)])
    assert audio_conversion_tag(mf, AudioMode.AC3) == "AC3"


def test_audio_conversion_tag_ignores_deselected_streams():
    mf = MediaFile(path=Path("x.mkv"), audio_streams=[
        AudioStream(index=1, codec="dts", channels=6, selected=False)])
    assert audio_conversion_tag(mf, AudioMode.AC3) == ""


def test_default_output_includes_audio_tag_only_when_transcoded():
    mf = MediaFile(path=Path("/v/Movie.mkv"), audio_streams=[
        AudioStream(index=1, codec="dts", channels=6, selected=True)])
    out = mf.default_output(None, "", VideoMode.ENCODE, audio_mode=AudioMode.AC3)
    assert out.name == "Movie.AC3.x265.mkv"


def test_default_output_name_tag_appended_at_the_very_end():
    mf = MediaFile(path=Path("/v/Movie.mkv"))
    out = mf.default_output(None, "1080p", VideoMode.ENCODE, name_tag="MyGroup")
    assert out.name == "Movie.1080p.x265.MyGroup.mkv"


def test_default_output_blank_name_tag_is_not_appended():
    mf = MediaFile(path=Path("/v/Movie.mkv"))
    out = mf.default_output(None, "", VideoMode.ENCODE, name_tag="   ")
    assert out.name == "Movie.x265.mkv"


def test_drc_zero_maps_to_minimum_ratio():
    assert "ratio=1.0" in drc_filter_args(0.0)


def test_drc_scales_with_level():
    assert "ratio=10.0" in drc_filter_args(2.0)
    assert "ratio=20.0" in drc_filter_args(4.0)
