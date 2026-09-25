import json
from datetime import datetime
from pathlib import Path

from mp3sanitizer.core.journal import (
    Journal,
    JournalEntry,
    JournalStore,
    Kind,
    Op,
    new_batch_id,
    undo_plans,
)


def _journal(batch_id: str, entries=(), kind=Kind.SAVE, undone_by=None) -> Journal:
    return Journal(
        batch_id, "2026-01-01T00:00:00", "0.3.0", "/m", kind, list(entries), True, None, undone_by
    )


def _ok(op=Op.RENAME, src="/m/a", dst="/m/b", **kw) -> JournalEntry:
    return JournalEntry(op, src, dst, True, **kw)


def test_batch_ids_sort_chronologically():
    early = new_batch_id(datetime(2026, 1, 2, 3, 4, 5))
    late = new_batch_id(datetime(2026, 1, 2, 3, 4, 6))
    assert early.startswith("20260102-030405-")
    assert early < late


def test_roundtrip(tmp_path):
    store = JournalStore(tmp_path)
    j = _journal("20260101-000000-aaaaaa", [_ok(track_id=3, tags_before={"artist": None})])
    store.save(j)
    loaded = store.load(store.json_path(j.batch_id))
    assert loaded == j


def test_latest_undoable_skips_undone_undo_and_empty(tmp_path):
    store = JournalStore(tmp_path)
    store.save(_journal("20260101-000001-a", [_ok()]))
    store.save(_journal("20260101-000002-b", [_ok()], undone_by="x"))
    store.save(_journal("20260101-000003-c", [_ok()], kind=Kind.UNDO))
    store.save(_journal("20260101-000004-d", [JournalEntry(Op.RENAME, "a", "b", False, "fout")]))
    assert store.latest_undoable().batch_id == "20260101-000001-a"


def test_corrupt_and_newer_journals_are_ignored(tmp_path):
    store = JournalStore(tmp_path)
    store.save(_journal("20260101-000001-a", [_ok()]))
    (tmp_path / "20260101-000009-z.json").write_text("{kapot", encoding="utf-8")
    newer = _journal("20260101-000008-y", [_ok()]).to_dict() | {"schema_version": 99}
    (tmp_path / "20260101-000008-y.json").write_text(json.dumps(newer), encoding="utf-8")
    assert store.latest_undoable().batch_id == "20260101-000001-a"
    assert (tmp_path / "20260101-000009-z.json.corrupt").exists()
    assert (tmp_path / "20260101-000008-y.json").exists()  # nieuwer: niet aangeraakt


def test_undo_plans_reverse_order_and_tags():
    j = _journal(
        "b",
        [
            _ok(Op.MOVE, "/m/x/a.mp3", "/m/1990/A.mp3", track_id=0),
            _ok(
                Op.TAG,
                "/m/1990/A.mp3",
                "/m/1990/A.mp3",
                track_id=0,
                tags_before={"artist": "oud", "title": None, "date": None},
            ),
            _ok(
                Op.TAG,
                "/m/b.mp3",
                "/m/b.mp3",
                track_id=1,
                tags_before={"artist": None, "title": "t", "date": "1999"},
            ),
            JournalEntry(Op.RENAME, "/m/c.mp3", "/m/C.mp3", False, "fout", 2),
            _ok(Op.RMDIR, "/m/x", "/m/x"),
        ],
    )
    plans = undo_plans(j)
    assert [(p.src, p.dst) for p in plans] == [
        (Path("/m/b.mp3"), Path("/m/b.mp3")),
        (Path("/m/1990/A.mp3"), Path("/m/x/a.mp3")),
    ]
    assert plans[0].tags.date == "1999"
    assert plans[1].tags.artist == "oud"
