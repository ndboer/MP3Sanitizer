from pathlib import Path

import pytest

from mp3sanitizer.core.deleter import DeleteItem, delete_files
from mp3sanitizer.core.journal import JournalStore, Kind, Op


@pytest.fixture
def setup(tmp_path):
    music = tmp_path / "m"
    music.mkdir()
    files = [music / f"{i}.mp3" for i in range(3)]
    for f in files:
        f.write_bytes(b"x")
    return music, files, JournalStore(tmp_path / "journal")


def test_trash_by_default(setup):
    music, files, store = setup
    trashed: list[str] = []

    def fake_trash(path: str) -> None:  # nooit de echte Prullenbak in tests
        trashed.append(path)
        Path(path).unlink()

    items = [DeleteItem(i, f) for i, f in enumerate(files[:2])]
    result, journal = delete_files(items, store, music, "t", trash=fake_trash)
    assert result.deleted == [0, 1]
    assert trashed == [str(files[0]), str(files[1])]
    assert files[2].exists()
    assert journal.kind is Kind.DELETE
    assert [e.op for e in journal.entries] == [Op.TRASH, Op.TRASH]
    # verwijderen is geen batch die de app kan terugdraaien
    assert store.latest_undoable() is None


def test_permanent_delete(setup):
    music, files, store = setup

    def must_not_trash(path: str) -> None:
        raise AssertionError("permanent verwijderen mag de Prullenbak niet gebruiken")

    result, journal = delete_files(
        [DeleteItem(0, files[0])], store, music, "t", permanent=True, trash=must_not_trash
    )
    assert result.deleted == [0]
    assert not files[0].exists()
    assert journal.entries[0].op is Op.DELETE


def test_failure_does_not_stop_the_rest(setup):
    music, files, store = setup

    def flaky(path: str) -> None:
        if path.endswith("0.mp3"):
            raise OSError("in gebruik")
        Path(path).unlink()

    items = [DeleteItem(i, f) for i, f in enumerate(files)] + [DeleteItem(9, music / "weg.mp3")]
    result, journal = delete_files(items, store, music, "t", trash=flaky)
    assert result.deleted == [1, 2]
    assert [f[0] for f in result.failures] == [0, 9]
    assert journal.error_count == 2
    assert files[0].exists()


def test_cancel(setup):
    music, files, store = setup
    result, _ = delete_files(
        [DeleteItem(0, files[0])], store, music, "t", trash=lambda p: None, cancelled=lambda: True
    )
    assert result.cancelled
    assert result.deleted == []
    assert files[0].exists()
