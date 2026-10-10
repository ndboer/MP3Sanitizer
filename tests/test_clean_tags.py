"""Tags schrijven en opschonen: alleen artiest, titel en jaar blijven over; undo zet alles terug."""

from pathlib import Path

from mutagen.id3 import APIC, COMM, ID3, TALB, TCON, TDRC, TIT2, TPE1

from mp3sanitizer.core.batch import run_save, run_undo
from mp3sanitizer.core.journal import JournalStore
from mp3sanitizer.core.models import TagValues
from mp3sanitizer.core.planner import FolderTemplate, PlanInput, PlanOptions, plan_renames
from mp3sanitizer.core.tags import TagWriteError, write_clean_tags


def _silent_mp3(path: Path, frames: int = 40) -> None:
    header = bytes([0xFF, 0xFB, 0x90, 0x64])
    path.write_bytes((header + b"\x00" * 413) * frames)


def _rich_mp3(path: Path) -> None:
    _silent_mp3(path)
    tag = ID3()
    tag.add(TPE1(encoding=3, text="queen"))
    tag.add(TIT2(encoding=3, text="innuendo"))
    tag.add(TDRC(encoding=3, text="1991"))
    tag.add(TALB(encoding=3, text="Innuendo (album)"))
    tag.add(TCON(encoding=3, text="Rock"))
    tag.add(COMM(encoding=3, lang="eng", desc="", text="ripped by me"))
    tag.add(APIC(encoding=3, mime="image/png", type=3, desc="", data=b"\x89PNG fake"))
    tag.save(path)


def _frames(path: Path) -> set[str]:
    return {key[:4] for key in ID3(path)}


def test_write_clean_tags_keeps_only_three_and_backs_up(tmp_path):
    path = tmp_path / "x.mp3"
    _rich_mp3(path)
    before, backup = write_clean_tags(
        path, TagValues("Queen", "Innuendo", "1991"), tmp_path / "b.id3"
    )
    assert before == TagValues("queen", "innuendo", "1991")
    assert _frames(path) == {"TPE1", "TIT2", "TDRC"}
    assert str(ID3(path)["TPE1"]) == "Queen"
    assert backup is not None and {"TALB", "APIC", "COMM"} <= _frames(backup)


def test_non_mp3_is_only_updated(tmp_path):
    import struct

    path = tmp_path / "x.wav"
    data = b"\x80" * 800
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 8000, 1, 8)
    path.write_bytes(header + fmt + b"data" + struct.pack("<I", len(data)) + data)
    try:
        _, backup = write_clean_tags(path, TagValues("A", "B", "2000"), tmp_path / "b.id3")
    except TagWriteError:  # WAV zonder tag-ondersteuning: gewone fout, net als write_tags
        return
    assert backup is None


def test_save_with_strip_and_undo_restores_everything(tmp_path):
    root = tmp_path / "muziek"
    root.mkdir()
    path = root / "Queen - Innuendo (1991).mp3"
    _rich_mp3(path)
    opts = PlanOptions(
        root,
        FolderTemplate.NONE,
        write_tags=True,
        include_unchanged=True,
        keep_names=True,
        strip_tags=True,
    )
    plans = plan_renames([PlanInput(1, path, "Queen", "Innuendo", 1991, False)], opts)
    assert len(plans) == 1 and plans[0].strip_tags and not plans[0].renames
    store = JournalStore(tmp_path / "journal")
    result, journal = run_save(plans, store, root, "test")
    assert not result.failures
    assert _frames(path) == {"TPE1", "TIT2", "TDRC"}
    assert any(e.tags_backup for e in journal.entries)

    undo_result, _ = run_undo(store.load(store.json_path(journal.batch_id)), store, "test")
    assert not undo_result.failures
    restored = ID3(path)
    assert {"TALB", "TCON", "COMM", "APIC"} <= _frames(path)
    assert str(restored["TPE1"]) == "queen"
    assert restored.getall("APIC")[0].data == b"\x89PNG fake"
