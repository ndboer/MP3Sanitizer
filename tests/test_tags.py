import struct
from pathlib import Path

from mutagen.easyid3 import EasyID3

from mp3sanitizer.core.models import AudioInfo, Field
from mp3sanitizer.core.tags import read_audio_info, tag_mismatches


def _write_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> None:
    """Minimale mono 8-bit PCM WAV, zodat er geen testaudio in de repo hoeft."""
    frames = int(seconds * rate)
    data = b"\x80" * frames
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate, 1, 8)
    path.write_bytes(header + fmt + b"data" + struct.pack("<I", len(data)) + data)


def test_read_wav_duration(tmp_path):
    path = tmp_path / "A - B.wav"
    _write_wav(path, seconds=2.0)
    info = read_audio_info(path)
    assert info.error is None
    assert info.size_bytes == path.stat().st_size
    assert abs((info.duration_s or 0) - 2.0) < 0.01
    assert info.bitrate_kbps == 64


def _write_silent_mp3(path: Path, frames: int = 40) -> None:
    """MPEG-1 Layer III, 128 kbps, 44.1 kHz: frames van 417 bytes met een lege payload."""
    header = bytes([0xFF, 0xFB, 0x90, 0x64])
    path.write_bytes((header + b"\x00" * 413) * frames)


def test_read_id3_tags(tmp_path):
    path = tmp_path / "Queen - Innuendo (1991).mp3"
    _write_silent_mp3(path)
    tags = EasyID3()
    tags["artist"] = "Queen"
    tags["title"] = "Innuendo"
    tags["date"] = "1991-02-04"
    tags.save(path)
    info = read_audio_info(path)
    assert info.error is None
    assert (info.tag_artist, info.tag_title, info.tag_year) == ("Queen", "Innuendo", 1991)
    assert info.bitrate_kbps == 128
    assert info.duration_s and 0.9 < info.duration_s < 1.2


def test_read_garbage_does_not_raise(tmp_path):
    path = tmp_path / "kapot.mp3"
    path.write_bytes(b"dit is geen mp3" * 10)
    info = read_audio_info(path)
    assert info.size_bytes == 150
    assert info.duration_s is None


def test_read_missing_file(tmp_path):
    info = read_audio_info(tmp_path / "weg.mp3")
    assert info.error


def test_tag_mismatches():
    info = AudioInfo(tag_artist="queen", tag_title="Innuendo (Remaster)", tag_year=1992)
    assert tag_mismatches("Queen", "Innuendo", 1991, info) == [Field.TITLE, Field.YEAR]
    assert tag_mismatches("Queen", "Innuendo", None, AudioInfo(tag_year=1991)) == []
    assert tag_mismatches("Queen", "Innuendo", 1991, AudioInfo()) == []
    assert tag_mismatches("Queen", "Innuendo", 1991, None) == []
