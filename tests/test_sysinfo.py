"""Tests für die Parsing-Regexe in sysinfo.py (fps aus dem Benchmark,
x265-Version aus dem Encoder-Log) - reine String-Verarbeitung, kein
echter ffmpeg-Aufruf nötig."""
import sysinfo


def test_fps_regex_picks_last_occurrence():
    stderr = ("frame=  10 fps=0.0 q=-1.0\n"
             "frame=  50 fps=25.0 q=-1.0\n"
             "frame= 100 fps=42.7 q=-1.0\n")
    matches = sysinfo._FPS_RE.findall(stderr)
    assert matches[-1] == "42.7"


def test_x265_version_regex_extracts_version_string():
    line = ("x265 [info]: HEVC encoder version 4.2+37-b81f650\n"
            "x265 [info]: build info [Windows][GCC 16.1.0][64 bit]\n")
    m = sysinfo._X265_VER_RE.search(line)
    assert m is not None
    assert m.group(1) == "4.2+37-b81f650"


def test_x265_version_regex_no_match_returns_none():
    m = sysinfo._X265_VER_RE.search("no x265 output here")
    assert m is None


def test_x265_version_stops_before_trailing_comma():
    line = "x265 [info]: HEVC encoder version 3.5+1-f0c1022b6, some trailing text"
    m = sysinfo._X265_VER_RE.search(line)
    assert m.group(1) == "3.5+1-f0c1022b6"
