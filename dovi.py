"""Dolby-Vision-Pipeline:
1. HEVC-Stream extrahieren, RPU mit dovi_tool ziehen (Profil 7 -> 8.1 konvertieren)
2. Video als HDR10 neu encoden (eigener Schritt, ruft build_encode_command-Variante)
3. RPU in neuen HEVC-Stream injizieren
4. Mit Audio/Subs zurück in MKV muxen (mkvmerge bevorzugt, sonst ffmpeg)
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from encoders import audio_args, audio_needs_transcode, build_video_filter, quality_args, tuning_args
from models import AudioMode, MediaFile
from settings import subprocess_flags

ProgressCb = Callable[[float, str], None]
LineCb = Callable[[str], None]


class DoviError(RuntimeError):
    pass


def _run(cmd: list[str], desc: str, timeout: int | None = None) -> None:
    from applog import log, log_cmd
    log_cmd(cmd)
    res = subprocess.run(cmd, capture_output=True, text=True,
                         timeout=timeout, **subprocess_flags())
    for line in ((res.stderr or "") + (res.stdout or "")).splitlines()[-15:]:
        log("  " + line)
    if res.returncode != 0:
        raise DoviError(f"{desc} fehlgeschlagen: {res.stderr[-400:]}")


def extract_rpu(mf: MediaFile, ffmpeg: str, dovi_tool: str, workdir: Path) -> Path:
    """RPU aus der Quelle extrahieren. Profil 7 wird nach 8.1 konvertiert."""
    hevc = workdir / "source.hevc"
    rpu = workdir / "rpu.bin"
    _run([ffmpeg, "-hide_banner", "-y", "-i", str(mf.path),
          "-map", "0:v:0", "-c:v", "copy", "-bsf:v", "hevc_mp4toannexb",
          "-f", "hevc", str(hevc)], "HEVC-Demux")
    cmd = [dovi_tool]
    if mf.dv_profile == 7:
        cmd += ["-m", "2"]  # zu Profil 8.1, EL verwerfen
    cmd += ["extract-rpu", str(hevc), "-o", str(rpu)]
    _run(cmd, "RPU-Extraktion")
    hevc.unlink(missing_ok=True)  # Platz sparen
    if not rpu.exists() or rpu.stat().st_size == 0:
        raise DoviError("RPU-Datei leer – keine DV-Metadaten gefunden")
    return rpu


def build_dv_encode_command(
    mf: MediaFile, ffmpeg: str, encoder: str, target: str, hevc_out: Path,
    preset: str = "medium", tune: str = "none",
) -> list[str]:
    """Encode nur des Videostreams als roher HEVC (Annex B) mit HDR10-Signalen."""
    hw_vaapi = encoder == "hevc_vaapi"
    cmd = [ffmpeg, "-hide_banner", "-y", "-nostats", "-progress", "pipe:1"]
    if hw_vaapi:
        cmd += ["-vaapi_device", "/dev/dri/renderD128"]
    cmd += ["-i", str(mf.path), "-map", "0:v:0", "-an", "-sn"]
    vf = build_video_filter(mf, target, hw_vaapi)
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-c:v", encoder] + quality_args(encoder, mf.crf, preset)
    if not hw_vaapi:
        if encoder == "libx265":
            cmd += ["-pix_fmt", "yuv420p10le"]
        elif encoder in ("hevc_nvenc", "hevc_qsv", "hevc_videotoolbox"):
            cmd += ["-pix_fmt", "p010le"]
    cmd += tuning_args(mf, encoder, tune)
    cmd += ["-f", "hevc", str(hevc_out)]
    return cmd


def inject_and_mux(
    mf: MediaFile, encoded_hevc: Path, rpu: Path, output: Path,
    dovi_tool: str, mkvmerge: str | None, ffmpeg: str, workdir: Path,
    audio_mode: AudioMode = AudioMode.COPY,
) -> None:
    injected = workdir / "injected.hevc"
    _run([dovi_tool, "inject-rpu", str(encoded_hevc), "--rpu-in", str(rpu),
          "-o", str(injected)], "RPU-Injektion")
    encoded_hevc.unlink(missing_ok=True)

    audio_tracks = [a.index for a in mf.audio_streams if a.selected]
    # mkvmerge kann Audio nur kopieren, nicht transcodieren – ist also nur
    # nutzbar, solange keine ausgewählte Spur tatsächlich gewandelt werden
    # muss (audio_needs_transcode prüft dieselbe Pro-Spur-Logik wie beim
    # normalen Encode: global_mode/Override, Codec-Match, Kanal-/DRC-
    # Override). Sonst muss ffmpeg den finalen Mux übernehmen, da nur das
    # transcodieren kann.
    if mkvmerge and not audio_needs_transcode(mf, audio_mode):
        cmd = [mkvmerge, "-o", str(output), str(injected)]
        if audio_tracks:
            cmd += ["--audio-tracks", ",".join(map(str, audio_tracks))]
        else:
            cmd += ["--no-audio"]
        cmd += ["--no-video", str(mf.path)]  # Audio/Subs/Attachments aus Quelle
        _run(cmd, "mkvmerge-Mux")
    else:
        cmd = [ffmpeg, "-hide_banner", "-y",
               "-i", str(injected), "-i", str(mf.path),
               "-map", "0:v:0"]
        for idx in audio_tracks:
            cmd += ["-map", f"1:{idx}"]
        cmd += ["-map", "1:s?", "-map", "1:t?", "-c:v", "copy"]
        cmd += audio_args(mf, audio_mode)
        cmd += ["-c:s", "copy", "-c:t", "copy", str(output)]
        _run(cmd, "ffmpeg-Mux")
    injected.unlink(missing_ok=True)


def make_workdir(output: Path, mf: MediaFile | None = None) -> Path:
    """Legt das Arbeitsverzeichnis für die (teils riesigen, v. a. der rohe
    extrahierte HEVC-Stream) DV-Zwischendateien an.

    Bevorzugt den lokalen Temp-Ordner (tempfile.gettempdir(), in Docker der
    schnelle Container-eigene /tmp), sofern dort genug freier Platz ist –
    sonst müssten die Zwischendateien übers Netz geschrieben werden, falls
    Quelle/Ziel auf einem Netzlaufwerk/-Share liegen. Ob output.parent
    tatsächlich ein Netzlaufwerk ist, lässt sich plattformübergreifend (v. a.
    aus einem Docker-Bind-Mount heraus) nicht zuverlässig feststellen –
    deshalb direkt am eigentlichen Ziel ansetzen (genug lokaler Platz?)
    statt am Mount-Typ. Reicht der lokale Platz nicht, Fallback auf den
    bisherigen Ort neben der Ausgabedatei.
    """
    # video_stream_size ist die geschätzte Größe des rohen Video-Streams der
    # QUELLE (aus der Analyse) – das ist die größte transiente Datei
    # (extract_rpu's "source.hevc", wird nach der RPU-Extraktion sofort
    # wieder gelöscht). Sicherheitsmarge, da Schätzung nicht exakt ist.
    needed = 0
    if mf is not None:
        needed = mf.video_stream_size or (
            mf.path.stat().st_size if mf.path.exists() else 0)
        needed = int(needed * 1.2)

    from applog import log

    local_base = Path(tempfile.gettempdir())
    disk_usage_error = ""
    try:
        free_local = shutil.disk_usage(local_base).free
    except OSError as e:
        free_local = 0
        disk_usage_error = str(e)

    use_local = bool(needed and free_local > needed)
    base_dir = local_base if use_local else output.parent

    def _fmt_gb(n: int) -> str:
        return f"{n / 1024**3:.1f} GB"
    if disk_usage_error:
        log(f"DV-Workdir: disk_usage({local_base}) fehlgeschlagen "
            f"({disk_usage_error}) -> Fallback auf {output.parent}")
    elif not needed:
        log(f"DV-Workdir: Größe der Quelle unbekannt -> konservativ "
            f"{output.parent} verwendet (kein lokaler Temp-Versuch)")
    else:
        log(f"DV-Workdir: benötigt ~{_fmt_gb(needed)}, frei in {local_base}: "
            f"{_fmt_gb(free_local)} -> {'lokal' if use_local else f'Fallback auf {output.parent}'}")

    # mkdtemp() hardcodes mode 700 regardless of the process umask (a
    # tempfile security default). Only matters (host-visible, needs
    # widening) when base_dir is the output folder, e.g. a Docker volume –
    # a workdir under the local temp dir is container-internal only anyway.
    workdir = Path(tempfile.mkdtemp(prefix="dv_", dir=str(base_dir)))
    if base_dir == output.parent:
        workdir.chmod(0o777)
    return workdir
