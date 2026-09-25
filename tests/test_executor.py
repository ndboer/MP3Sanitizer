import json
import os
from pathlib import Path

import pytest
from mutagen.easyid3 import EasyID3

from mp3sanitizer.core.batch import run_save, run_undo
from mp3sanitizer.core.journal import JournalStore, Kind, Op
from mp3sanitizer.core.models import Collision, RenamePlan, TagValues
from mp3sanitizer.core.planner import FolderTemplate, PlanInput, PlanOptions, plan_renames

VERSION = "9.9.9-test"


def _touch(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _names(directory: Path) -> set[str]:
    """Echte schrijfwijze op schijf (ook op hoofdletterongevoelige bestandssystemen)."""
    return set(os.listdir(directory))


def _silent_mp3(path: Path) -> Path:
    header = bytes([0xFF, 0xFB, 0x90, 0x64])
    return _touch(path, (header + b"\x00" * 413) * 20)


@pytest.fixture
def store(tmp_path):
    return JournalStore(tmp_path / "journal")


@pytest.fixture
def music(tmp_path):
    root = tmp_path / "muziek"
    root.mkdir()
    return root


def test_rename_and_move(store, music):
    a = _touch(music / "oud" / "a.mp3", b"A")
    b = _touch(music / "oud" / "b.mp3", b"B")
    plans = [
        RenamePlan(0, a, music / "oud" / "Artiest - A.mp3"),
        RenamePlan(1, b, music / "1985" / "Artiest - B (1985).mp3"),
    ]
    result, journal = run_save(plans, store, music, VERSION)
    assert not result.failures
    assert (music / "oud" / "Artiest - A.mp3").read_bytes() == b"A"
    assert (music / "1985" / "Artiest - B (1985).mp3").read_bytes() == b"B"
    assert [e.op for e in journal.entries] == [Op.RENAME, Op.MOVE]


def test_case_only_rename(store, music):
    src = _touch(music / "queen - innuendo.mp3")
    [plan] = plan_renames([PlanInput(0, src, "Queen", "Innuendo", None, True)], PlanOptions(music))
    assert plan.case_only
    result, _ = run_save([plan], store, music, VERSION)
    assert not result.failures
    assert _names(music) == {"Queen - Innuendo.mp3"}


def test_swap_two_names(store, music):
    a = _touch(music / "A.mp3", b"A")
    b = _touch(music / "B.mp3", b"B")
    plans = [RenamePlan(0, a, music / "B.mp3"), RenamePlan(1, b, music / "A.mp3")]
    result, _ = run_save(plans, store, music, VERSION)
    assert not result.failures
    assert (music / "A.mp3").read_bytes() == b"B"
    assert (music / "B.mp3").read_bytes() == b"A"
    assert _names(music) == {"A.mp3", "B.mp3"}  # geen tijdelijke namen achtergebleven


def test_chain(store, music):
    a = _touch(music / "A.mp3", b"A")
    b = _touch(music / "B.mp3", b"B")
    plans = [RenamePlan(0, a, music / "B.mp3"), RenamePlan(1, b, music / "C.mp3")]
    result, _ = run_save(plans, store, music, VERSION)
    assert not result.failures
    assert (music / "B.mp3").read_bytes() == b"A"
    assert (music / "C.mp3").read_bytes() == b"B"


def test_never_overwrites_even_with_bad_plan(store, music):
    a = _touch(music / "a.mp3", b"A")
    _touch(music / "doel.mp3", b"BESTAAT")
    result, journal = run_save([RenamePlan(0, a, music / "doel.mp3")], store, music, VERSION)
    assert (music / "doel.mp3").read_bytes() == b"BESTAAT"
    assert a.exists()
    assert len(result.failures) == 1
    assert not journal.entries[0].ok


def test_error_does_not_stop_batch(store, music):
    missing = music / "weg.mp3"
    ok = _touch(music / "ok.mp3")
    plans = [RenamePlan(0, missing, music / "x.mp3"), RenamePlan(1, ok, music / "y.mp3")]
    result, journal = run_save(plans, store, music, VERSION)
    assert [f.track_id for f in result.failures] == [0]
    assert (music / "y.mp3").exists()
    assert journal.ok_count == 1
    assert journal.error_count == 1


def test_blocked_plans_are_not_executed(store, music):
    a = _touch(music / "a.mp3")
    plan = RenamePlan(0, a, music / "b.mp3", blocked=True, collision=Collision.SKIP)
    result, journal = run_save([plan], store, music, VERSION)
    assert a.exists()
    assert journal.entries == []
    assert result.moved == []


def test_cancel_restores_temp_names(store, music):
    a = _touch(music / "A.mp3", b"A")
    b = _touch(music / "B.mp3", b"B")
    plans = [RenamePlan(0, a, music / "B.mp3"), RenamePlan(1, b, music / "A.mp3")]
    result, _ = run_save(plans, store, music, VERSION, cancelled=lambda: True)
    assert result.cancelled
    assert (music / "A.mp3").read_bytes() == b"A"
    assert (music / "B.mp3").read_bytes() == b"B"
    assert _names(music) == {"A.mp3", "B.mp3"}


def test_cleanup_empty_dirs_but_never_root(store, music):
    a = _touch(music / "x" / "y" / "a.mp3")
    keep = _touch(music / "z" / "keep.mp3")
    plans = [
        RenamePlan(0, a, music / "1990" / "a.mp3"),
        RenamePlan(1, keep, music / "1991" / "keep.mp3"),
    ]
    _touch(music / "z" / "cover.jpg")  # niet-audio: map z blijft
    result, journal = run_save(plans, store, music, VERSION, cleanup_empty_dirs=True)
    assert not (music / "x").exists()
    assert (music / "z").exists()
    assert music.exists()
    assert {p.name for p in result.removed_dirs} == {"x", "y"}
    assert sum(e.op is Op.RMDIR for e in journal.entries) == 2


def test_journal_files_with_version(store, music):
    a = _touch(music / "a.mp3")
    _, journal = run_save([RenamePlan(0, a, music / "b.mp3")], store, music, VERSION)
    data = json.loads(store.json_path(journal.batch_id).read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["app_version"] == VERSION
    assert data["finished"] is True
    assert data["entries"][0]["src"] == str(a)
    log_text = store.log_path(journal.batch_id).read_text(encoding="utf-8")
    assert log_text.startswith(f"# Mp3Sanitizer {VERSION}")
    assert "->" in log_text


def test_undo_roundtrip_with_moves_swaps_and_dirs(store, music):
    a = _touch(music / "oud" / "A.mp3", b"A")
    b = _touch(music / "oud" / "B.mp3", b"B")
    c = _touch(music / "oud" / "c.mp3", b"C")
    plans = [
        RenamePlan(0, a, music / "oud" / "B.mp3"),
        RenamePlan(1, b, music / "oud" / "A.mp3"),
        RenamePlan(2, c, music / "1999" / "C.mp3"),
    ]
    run_save(plans, store, music, VERSION, cleanup_empty_dirs=True)
    target = store.latest_undoable()
    assert target is not None
    result, undo_journal = run_undo(target, store, VERSION)
    assert not result.failures
    assert (music / "oud" / "A.mp3").read_bytes() == b"A"
    assert (music / "oud" / "B.mp3").read_bytes() == b"B"
    assert (music / "oud" / "c.mp3").read_bytes() == b"C"
    assert not (music / "1999").exists()  # door de batch aangemaakte map is weer weg
    assert undo_journal.kind is Kind.UNDO
    assert undo_journal.undoes == target.batch_id
    # de teruggedraaide batch is niet nog eens terug te draaien, en een undo-batch ook niet
    assert store.latest_undoable() is None


def test_write_tags_and_undo(store, music):
    src = _silent_mp3(music / "a.mp3")
    tags = EasyID3()
    tags["artist"] = "Oud"
    tags.save(src)
    plan = RenamePlan(
        0, src, music / "Nieuw - Titel (2001).mp3", tags=TagValues("Nieuw", "Titel", "2001")
    )
    result, journal = run_save([plan], store, music, VERSION)
    assert not result.failures
    new = EasyID3(music / "Nieuw - Titel (2001).mp3")
    assert (new["artist"], new["title"], new["date"]) == (["Nieuw"], ["Titel"], ["2001"])
    tag_entry = journal.entries[-1]
    assert tag_entry.op is Op.TAG
    assert tag_entry.tags_before == {"artist": "Oud", "title": None, "date": None}

    run_undo(store.latest_undoable(), store, VERSION)
    old = EasyID3(music / "a.mp3")
    assert old["artist"] == ["Oud"]
    assert "title" not in old
    assert "date" not in old


def test_tag_error_is_reported_but_rename_stays(store, music):
    src = _touch(music / "a.mp3", b"geen mp3")
    plan = RenamePlan(0, src, music / "b.mp3", tags=TagValues("A", "B", None))
    result, journal = run_save([plan], store, music, VERSION)
    assert (music / "b.mp3").exists()
    assert len(result.failures) == 1
    assert [e.ok for e in journal.entries] == [True, False]


def test_end_to_end_plan_and_execute_year_folders(store, music):
    a = _touch(music / "rommel" / "queen - innuendo (1991).mp3")
    b = _touch(music / "rommel" / "kopie" / "Queen-Innuendo.mp3")
    opts = PlanOptions(music, FolderTemplate.YEAR, collision=Collision.SUFFIX)
    inputs = [
        PlanInput(0, a, "Queen", "Innuendo", 1991, True),
        PlanInput(1, b, "Queen", "Innuendo", 1991, True),
    ]
    plans = plan_renames(inputs, opts)
    result, _ = run_save(plans, store, music, VERSION, cleanup_empty_dirs=True)
    assert not result.failures
    assert _names(music / "1991") == {
        "Queen - Innuendo (1991).mp3",
        "Queen - Innuendo (1991) (2).mp3",
    }
    assert not (music / "rommel").exists()
