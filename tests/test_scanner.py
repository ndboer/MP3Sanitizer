from pathlib import Path

from mp3sanitizer.core.models import ParseStatus
from mp3sanitizer.core.scanner import iter_audio_files, normalize_extensions, track_from_path


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_scan_recursive_with_extension_filter(tmp_path):
    _touch(tmp_path / "Queen - Innuendo (1991).mp3")
    _touch(tmp_path / "1985" / "A-ha - Take On Me (1985).MP3")
    _touch(tmp_path / "1985" / "sub" / "X - Y.flac")
    _touch(tmp_path / "cover.jpg")
    _touch(tmp_path / "notes.txt")

    found = {p.relative_to(tmp_path).as_posix() for p in iter_audio_files(tmp_path)}
    assert found == {
        "Queen - Innuendo (1991).mp3",
        "1985/A-ha - Take On Me (1985).MP3",
        "1985/sub/X - Y.flac",
    }

    only_flac = list(iter_audio_files(tmp_path, ["flac"]))
    assert [p.name for p in only_flac] == ["X - Y.flac"]


def test_scan_can_be_cancelled(tmp_path):
    for i in range(3):
        _touch(tmp_path / f"d{i}" / f"A - {i}.mp3")
    assert list(iter_audio_files(tmp_path, cancelled=lambda: True)) == []


def test_scan_missing_root_is_empty(tmp_path):
    assert list(iter_audio_files(tmp_path / "bestaat-niet")) == []


def test_normalize_extensions():
    assert normalize_extensions(["mp3", ".FLAC", " ", "m4a "]) == {".mp3", ".flac", ".m4a"}


def test_track_from_path(tmp_path):
    path = tmp_path / "1991" / "Queen - Innuendo (1991).mp3"
    track = track_from_path(7, path, tmp_path)
    assert track.id == 7
    assert (track.artist, track.title, track.year) == ("Queen", "Innuendo", 1991)
    assert track.parse_status is ParseStatus.OK
    assert track.folder == "1991"
    assert track.filename == "Queen - Innuendo (1991).mp3"
    assert track.ext == ".mp3"

    top = track_from_path(0, tmp_path / "Rubbish.mp3", tmp_path)
    assert top.folder == ""
    assert top.parse_status is ParseStatus.ERROR
