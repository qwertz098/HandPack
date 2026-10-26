"""Regressionstest für den gefundenen DV-Pipeline-Bug: inject_and_mux
ignorierte audio_mode komplett und kopierte Audiospuren per mkvmerge immer
1:1 aus der Quelle, obwohl der Dateiname (via audio_conversion_tag) eine
Wandlung (z. B. AC3) suggerierte, die nie stattfand. mkvmerge kann nicht
transcodieren - der Fix erkennt das und weicht in dem Fall auf einen
ffmpeg-Mux mit echter Audio-Transcodierung aus."""
from pathlib import Path
from types import SimpleNamespace

import dovi
from models import AudioMode, AudioStream, MediaFile


def make_mf(codec="dts", channels=2) -> MediaFile:
    return MediaFile(path=Path("src.mkv"), audio_streams=[
        AudioStream(index=2, codec=codec, channels=channels, selected=True)])


def run_inject_and_mux(monkeypatch, tmp_path, mf, audio_mode, mkvmerge="mkvmerge"):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(dovi.subprocess, "run", fake_run)
    workdir = tmp_path
    (workdir / "encoded.hevc").write_bytes(b"x")
    output = workdir / "out.mkv"
    dovi.inject_and_mux(mf, workdir / "encoded.hevc", workdir / "rpu.bin", output,
                        "dovi_tool", mkvmerge, "ffmpeg", workdir,
                        audio_mode=audio_mode)
    return calls


def test_transcode_needed_uses_ffmpeg_mux_with_real_audio_conversion(monkeypatch, tmp_path):
    """Der eigentliche Bug: DTS-Quelle + AudioMode.AC3 muss tatsächlich zu
    AC3 gewandelt werden, nicht stillschweigend kopiert."""
    mf = make_mf(codec="dts")
    calls = run_inject_and_mux(monkeypatch, tmp_path, mf, AudioMode.AC3)

    mux_cmd = calls[-1]
    assert mux_cmd[0] == "ffmpeg"
    assert "-c:a:0" in mux_cmd
    assert mux_cmd[mux_cmd.index("-c:a:0") + 1] == "ac3"
    assert not any(c[0] == "mkvmerge" for c in calls)


def test_copy_mode_still_uses_fast_mkvmerge_path(monkeypatch, tmp_path):
    """Reine Kopie soll weiterhin den schnellen mkvmerge-Pfad nutzen, nicht
    unnötig auf ffmpeg umschwenken."""
    mf = make_mf(codec="dts")
    calls = run_inject_and_mux(monkeypatch, tmp_path, mf, AudioMode.COPY)

    mux_cmd = calls[-1]
    assert mux_cmd[0] == "mkvmerge"


def test_already_target_codec_stays_on_mkvmerge_path(monkeypatch, tmp_path):
    """Codec entspricht schon dem Ziel -> kein echtes Transcode nötig,
    mkvmerge-Copy reicht weiterhin aus."""
    mf = make_mf(codec="ac3", channels=6)
    calls = run_inject_and_mux(monkeypatch, tmp_path, mf, AudioMode.AC3)

    mux_cmd = calls[-1]
    assert mux_cmd[0] == "mkvmerge"


def test_channel_override_forces_ffmpeg_mux_even_if_codec_matches(monkeypatch, tmp_path):
    mf = make_mf(codec="ac3", channels=6)
    mf.audio_streams[0].target_channels = 2
    calls = run_inject_and_mux(monkeypatch, tmp_path, mf, AudioMode.AC3)

    mux_cmd = calls[-1]
    assert mux_cmd[0] == "ffmpeg"


def test_no_mkvmerge_available_falls_back_to_ffmpeg_regardless_of_audio_mode(monkeypatch, tmp_path):
    mf = make_mf(codec="dts")
    calls = run_inject_and_mux(monkeypatch, tmp_path, mf, AudioMode.COPY, mkvmerge=None)

    mux_cmd = calls[-1]
    assert mux_cmd[0] == "ffmpeg"
