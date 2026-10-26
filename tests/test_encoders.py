"""Tests für encoders.build_encode_command: reine Kommandozeilen-Konstruktion,
kein echter ffmpeg-Aufruf nötig. Deckt die Video-Copy-Weiche (kein -vf mit
Streamcopy kombinierbar) und die Audio-Passthrough/Transcode-Logik ab."""
from pathlib import Path

from encoders import build_encode_command
from models import AudioMode, AudioStream, HDRType, MediaFile, VideoMode


def make_mf(**overrides) -> MediaFile:
    defaults = dict(path=Path("in.mkv"), width=1920, height=1080,
                    hdr=HDRType.SDR, duration=60.0,
                    audio_streams=[AudioStream(index=1, codec="aac", channels=2,
                                               selected=True)])
    defaults.update(overrides)
    return MediaFile(**defaults)


def test_copy_mode_skips_filters_and_encoder_args():
    mf = make_mf()
    cmd = build_encode_command(mf, "ffmpeg", "libx265", "Original",
                               Path("out.mkv"), video_mode=VideoMode.COPY)
    assert "-c:v" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    # Video-Copy + Filter gleichzeitig ist ein ffmpeg-Fehler ("Filtering and
    # streamcopy cannot be used together") - darf also nie zusammen auftreten.
    assert "-vf" not in cmd
    assert "libx265" not in cmd
    assert "-preset" not in cmd


def test_encode_mode_uses_encoder_and_preset():
    mf = make_mf()
    cmd = build_encode_command(mf, "ffmpeg", "libx265", "Original",
                               Path("out.mkv"), preset="slow",
                               video_mode=VideoMode.ENCODE)
    assert "libx265" in cmd
    assert "-preset" in cmd
    assert cmd[cmd.index("-preset") + 1] == "slow"


def test_encode_mode_adds_crop_filter_when_crop_enabled():
    from models import CropInfo
    mf = make_mf(crop=CropInfo(w=1920, h=800, x=0, y=140), crop_enabled=True)
    cmd = build_encode_command(mf, "ffmpeg", "libx265", "Original",
                               Path("out.mkv"), video_mode=VideoMode.ENCODE)
    assert "-vf" in cmd
    vf = cmd[cmd.index("-vf") + 1]
    assert "crop=1920:800:0:140" in vf


def test_subtitles_and_attachments_always_copied_regardless_of_video_mode():
    """Sicherstellt, dass -c:s copy / -c:t copy unabhängig vom video_mode
    gesetzt werden - das ist die vom Nutzer erfragte Garantie."""
    mf = make_mf()
    for mode in (VideoMode.ENCODE, VideoMode.COPY):
        cmd = build_encode_command(mf, "ffmpeg", "libx265", "Original",
                                   Path("out.mkv"), video_mode=mode)
        assert "-c:s" in cmd and cmd[cmd.index("-c:s") + 1] == "copy"
        assert "-c:t" in cmd and cmd[cmd.index("-c:t") + 1] == "copy"


def test_audio_copy_passthrough_when_codec_already_matches():
    mf = make_mf(audio_streams=[
        AudioStream(index=1, codec="ac3", channels=6, selected=True)])
    cmd = build_encode_command(mf, "ffmpeg", "libx265", "Original",
                               Path("out.mkv"), audio_mode=AudioMode.AC3)
    assert "-c:a:0" in cmd
    assert cmd[cmd.index("-c:a:0") + 1] == "copy"


def test_audio_transcodes_when_codec_does_not_match_target():
    mf = make_mf(audio_streams=[
        AudioStream(index=1, codec="dts", channels=6, selected=True)])
    cmd = build_encode_command(mf, "ffmpeg", "libx265", "Original",
                               Path("out.mkv"), audio_mode=AudioMode.AC3)
    assert cmd[cmd.index("-c:a:0") + 1] == "ac3"
    assert "-b:a:0" in cmd


def test_audio_channel_override_forces_reencode_even_if_codec_matches():
    """Ein gesetzter Kanal-Override erzwingt Re-Encode, auch wenn der Codec
    schon passt - sonst würde der Override stillschweigend ignoriert."""
    mf = make_mf(audio_streams=[
        AudioStream(index=1, codec="ac3", channels=6, selected=True,
                   target_channels=2)])
    cmd = build_encode_command(mf, "ffmpeg", "libx265", "Original",
                               Path("out.mkv"), audio_mode=AudioMode.AC3)
    assert cmd[cmd.index("-c:a:0") + 1] == "ac3"
    assert cmd[cmd.index("-ac:a:0") + 1] == "2"


def test_monochrome_flag_uses_gray_pix_fmt_on_libx265():
    mf = make_mf(bit_depth=8)
    cmd = build_encode_command(mf, "ffmpeg", "libx265", "Original",
                               Path("out.mkv"), monochrome=True,
                               video_mode=VideoMode.ENCODE)
    assert "-pix_fmt" in cmd
    assert cmd[cmd.index("-pix_fmt") + 1] == "gray"


def test_monochrome_flag_uses_gray10_for_10bit_source():
    mf = make_mf(bit_depth=10)
    cmd = build_encode_command(mf, "ffmpeg", "libx265", "Original",
                               Path("out.mkv"), monochrome=True,
                               video_mode=VideoMode.ENCODE)
    assert cmd[cmd.index("-pix_fmt") + 1] == "gray10le"


def test_monochrome_flag_has_no_effect_on_hw_encoder():
    """Monochrome ist nur für libx265 (Software) sinnvoll umgesetzt - bei
    HW-Encodern soll einfach das normale Pixelformat verwendet werden,
    kein Fehler/Crash."""
    mf = make_mf(bit_depth=8)
    cmd = build_encode_command(mf, "ffmpeg", "hevc_nvenc", "Original",
                               Path("out.mkv"), monochrome=True,
                               video_mode=VideoMode.ENCODE)
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"


def test_monochrome_combinable_with_content_tune():
    """Monochrome ist jetzt unabhängig vom Content-Tune (Grain etc.) -
    beides gleichzeitig muss möglich sein, z. B. für alte S/W-Filme mit
    sichtbarem Filmkorn."""
    mf = make_mf(bit_depth=8)
    cmd = build_encode_command(mf, "ffmpeg", "libx265", "Original",
                               Path("out.mkv"), monochrome=True, tune="grain",
                               video_mode=VideoMode.ENCODE)
    assert cmd[cmd.index("-pix_fmt") + 1] == "gray"
    assert "-tune" in cmd and cmd[cmd.index("-tune") + 1] == "grain"


def test_monochrome_false_by_default_uses_normal_pix_fmt():
    mf = make_mf(bit_depth=8)
    cmd = build_encode_command(mf, "ffmpeg", "libx265", "Original",
                               Path("out.mkv"), video_mode=VideoMode.ENCODE)
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"


def test_deselected_audio_streams_are_not_mapped():
    mf = make_mf(audio_streams=[
        AudioStream(index=1, codec="aac", channels=2, selected=False)])
    cmd = build_encode_command(mf, "ffmpeg", "libx265", "Original",
                               Path("out.mkv"), audio_mode=AudioMode.COPY)
    assert "-c:a:0" not in cmd
