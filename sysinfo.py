"""Systemanalyse: CPU/RAM (plattformübergreifend, keine Zusatz-Dependencies)
sowie ein kurzer ffmpeg-Encode-Benchmark je verfügbarem Encoder."""
from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import dataclass, field

from settings import subprocess_flags

_FPS_RE = re.compile(r"fps=\s*([\d.]+)")
_X265_VER_RE = re.compile(r"x265 \[info\]: HEVC encoder version ([^\s,]+)")

BENCH_DURATION_S = 5
BENCH_RESOLUTION = "1920x1080"
BENCH_FRAMERATE = 30


def cpu_name() -> str:
    """Modellname der CPU, plattformabhängig ermittelt."""
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return name.strip()
        if system == "Linux":
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        if system == "Darwin":
            r = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
    except Exception:
        pass
    return platform.processor() or platform.uname().processor or "Unbekannt"


def cpu_cores() -> str:
    import os
    logical = os.cpu_count() or 0
    return f"{logical} Threads"


def ram_total_gb() -> str:
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return f"{stat.ullTotalPhys / (1024**3):.1f} GB"
        if system == "Linux":
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return f"{kb / (1024**2):.1f} GB"
        if system == "Darwin":
            r = subprocess.run(["sysctl", "-n", "hw.memsize"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return f"{int(r.stdout.strip()) / (1024**3):.1f} GB"
    except Exception:
        pass
    return "Unbekannt"


# WMI Win32_PhysicalMemory.MemoryType codes -> human-readable name.
_WIN_MEMORY_TYPES = {
    20: "DDR", 21: "DDR2", 22: "DDR2 FB-DIMM", 24: "DDR3",
    26: "DDR4", 34: "DDR5",
}


def ram_type() -> str:
    """RAM-Typ (z. B. DDR4/DDR5) + Takt, soweit ohne Zusatzrechte ermittelbar.
    Linux: braucht dmidecode + Root/CAP_SYS_RAWIO — in Containern meist
    nicht verfügbar, dann "Unbekannt" statt eines falschen Wertes."""
    system = platform.system()
    try:
        if system == "Windows":
            # MemoryType often reports 0 ("Unknown") on real hardware;
            # SMBIOSMemoryType is the reliable field for the actual DDR
            # generation (same code table).
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "$m = Get-CimInstance Win32_PhysicalMemory | Select-Object -First 1; "
                 "\"$($m.SMBIOSMemoryType),$($m.MemoryType),$($m.Speed)\""],
                capture_output=True, text=True, timeout=15, **subprocess_flags())
            if r.returncode == 0 and r.stdout.strip():
                parts = r.stdout.strip().split(",")
                smbios = int(parts[0]) if parts[0].isdigit() else 0
                legacy = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                mtype = _WIN_MEMORY_TYPES.get(smbios) or _WIN_MEMORY_TYPES.get(legacy)
                speed = parts[2] if len(parts) > 2 and parts[2].strip() else ""
                if mtype:
                    return f"{mtype}" + (f"-{speed}" if speed else "")
        if system == "Linux":
            r = subprocess.run(["dmidecode", "-t", "17"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                m = re.search(r"^\s*Type:\s*(DDR\d?|SDRAM)\s*$", r.stdout, re.M)
                speed_m = re.search(r"^\s*Speed:\s*([\d]+ MT/s|[\d]+ MHz)", r.stdout, re.M)
                if m and m.group(1) not in ("Unknown", ""):
                    speed = f" @ {speed_m.group(1)}" if speed_m else ""
                    return f"{m.group(1)}{speed}"
        if system == "Darwin":
            r = subprocess.run(["system_profiler", "SPMemoryDataType"],
                               capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                m = re.search(r"Type:\s*(DDR\d?)", r.stdout)
                speed_m = re.search(r"Speed:\s*([\d]+ MHz)", r.stdout)
                if m:
                    speed = f" @ {speed_m.group(1)}" if speed_m else ""
                    return f"{m.group(1)}{speed}"
    except Exception:
        pass
    return "Unbekannt"


def os_info() -> str:
    """Menschenlesbarer Name des Betriebssystems inkl. Version/Build."""
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
            name, _ = winreg.QueryValueEx(key, "ProductName")
            try:
                build, _ = winreg.QueryValueEx(key, "CurrentBuildNumber")
            except OSError:
                build = ""
            # Windows 11 still reports ProductName "Windows 10 ..." on some
            # builds; the build number is the reliable way to tell them apart.
            if build and build.isdigit() and int(build) >= 22000 and "Windows 10" in name:
                name = name.replace("Windows 10", "Windows 11")
            return f"{name} (Build {build})" if build else name
        if system == "Linux":
            info: dict[str, str] = {}
            with open("/etc/os-release", encoding="utf-8") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.rstrip("\n").split("=", 1)
                        info[k] = v.strip('"')
            pretty = info.get("PRETTY_NAME")
            if pretty:
                return f"{pretty} (Linux {platform.release()})"
        if system == "Darwin":
            r = subprocess.run(["sw_vers", "-productVersion"],
                               capture_output=True, text=True, timeout=5)
            ver = r.stdout.strip() if r.returncode == 0 else platform.mac_ver()[0]
            return f"macOS {ver}"
    except Exception:
        pass
    return platform.platform()


@dataclass
class BenchResult:
    encoder: str
    label: str
    fps: float | None      # None = Fehler/nicht verfügbar
    error: str = ""


@dataclass
class SystemInfo:
    cpu: str
    cores: str
    ram: str
    ram_type: str
    os: str
    encoders: list[tuple[str, str]] = field(default_factory=list)  # (id, label)
    tools: list[tuple[str, str, str]] = field(default_factory=list)  # (name, path/"missing", version)
    x265_version: str = ""


def x265_version(ffmpeg: str) -> str | None:
    """Tatsächliche x265-Bibliotheksversion (nicht die ffmpeg-Version) per
    Ein-Frame-Testencode – x265 schreibt seine Version nur beim Encodieren
    selbst nach stderr, nicht bei `ffmpeg -version`. Relevant z. B. um nach
    einem ffmpeg-Wechsel (Debian-Paket <-> statischer Build) zu erkennen,
    ob sich abweichende Encode-Geschwindigkeit über die x265-Version statt
    über CPU/Threads erklären lässt."""
    try:
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64",
             "-frames:v", "1", "-c:v", "libx265", "-f", "null", "-"],
            capture_output=True, text=True, timeout=15, **subprocess_flags())
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = _X265_VER_RE.search(r.stderr or "")
    return m.group(1) if m else None


def gather_system_info(tools: dict[str, str | None]) -> SystemInfo:
    from downloader import local_version

    ffmpeg = tools.get("ffmpeg")
    from encoders import ENCODER_LABELS, detect_encoders
    enc_ids = detect_encoders(ffmpeg) if ffmpeg else ["libx265"]
    encoders = [(e, ENCODER_LABELS.get(e, e)) for e in enc_ids]

    tool_rows: list[tuple[str, str, str]] = []
    for name, path in tools.items():
        if not path:
            tool_rows.append((name, "–", ""))
            continue
        ver = local_version(path) or "?"
        tool_rows.append((name, path, ver))

    return SystemInfo(cpu=cpu_name(), cores=cpu_cores(), ram=ram_total_gb(),
                       ram_type=ram_type(), os=os_info(),
                       encoders=encoders, tools=tool_rows,
                       x265_version=(x265_version(ffmpeg) if ffmpeg else None) or "")


def _bench_cmd(ffmpeg: str, encoder: str) -> list[str]:
    src = (f"testsrc2=size={BENCH_RESOLUTION}:rate={BENCH_FRAMERATE}"
           f":duration={BENCH_DURATION_S}")
    cmd = [ffmpeg, "-hide_banner", "-y", "-f", "lavfi", "-i", src]
    if encoder == "hevc_vaapi":
        cmd = [ffmpeg, "-hide_banner", "-y",
               "-vaapi_device", "/dev/dri/renderD128",
               "-f", "lavfi", "-i", src,
               "-vf", "format=nv12,hwupload"]
    cmd += ["-c:v", encoder, "-preset", "medium", "-f", "null", "-"]
    return cmd


def run_benchmark(ffmpeg: str, encoder: str, label: str) -> BenchResult:
    """Kurzer Testpattern-Encode; letzte 'fps=' Zahl aus ffmpeg-stderr
    ist die erzielte Encoding-Geschwindigkeit."""
    try:
        r = subprocess.run(_bench_cmd(ffmpeg, encoder),
                            capture_output=True, text=True,
                            timeout=BENCH_DURATION_S + 30,
                            **subprocess_flags())
    except subprocess.TimeoutExpired:
        return BenchResult(encoder, label, None, "Timeout")
    except Exception as e:  # noqa: BLE001
        return BenchResult(encoder, label, None, str(e))
    if r.returncode != 0:
        return BenchResult(encoder, label, None, r.stderr[-200:] or "ffmpeg-Fehler")
    matches = _FPS_RE.findall(r.stderr)
    if not matches:
        return BenchResult(encoder, label, None, "keine fps-Ausgabe gefunden")
    return BenchResult(encoder, label, float(matches[-1]))
