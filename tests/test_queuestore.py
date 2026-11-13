from pathlib import Path

import queuestore
from models import (AudioMode, AudioStream, CropInfo, HDRType, JobStatus,
                    MediaFile, SubtitleStream, VideoMode)


def _sample() -> MediaFile:
    return MediaFile(
        path=Path("/in/a.mkv"), hdr=HDRType.DOLBY_VISION, dv_profile=7,
        crop=CropInfo(1, 2, 3, 4), crf=18, video_mode=VideoMode.COPY,
        output_path=Path("/out/a.mkv"), status=JobStatus.RUNNING,
        audio_streams=[AudioStream(index=1, codec="ac3",
                                   mode=AudioMode.AAC, drc=0.5)],
        subtitle_streams=[SubtitleStream(index=2)])


def test_roundtrip(tmp_path):
    f = tmp_path / "q.json"
    queuestore.save(queuestore.dumps([_sample()], [Path("/in/b.mkv")]), f)
    files, pending = queuestore.load(f)
    assert files == [_sample()]
    assert pending == [Path("/in/b.mkv")]


def test_missing_or_corrupt_file_gives_empty_queue(tmp_path):
    assert queuestore.load(tmp_path / "none.json") == ([], [])
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert queuestore.load(bad) == ([], [])


def test_unknown_fields_and_bad_entries_are_skipped():
    text = ('{"files": [{"path": "/x.mkv", "future_field": 1}, {"nopath": 1}],'
            ' "pending": []}')
    files, _ = queuestore.loads(text)
    assert [f.path for f in files] == [Path("/x.mkv")]
