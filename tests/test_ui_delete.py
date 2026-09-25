"""Verwijderen vanuit het hoofdvenster. De echte Prullenbak wordt nooit gebruikt."""

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from mp3sanitizer.core.journal import JournalStore
from mp3sanitizer.core.models import Field
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.ui import main_window as main_window_module
from mp3sanitizer.ui.delete_dialog import DeleteDialog
from mp3sanitizer.ui.main_window import MainWindow
from mp3sanitizer.ui.track_model import Col

NAMES = ["A - Een (1990).mp3", "B - Twee (1991).mp3", "C - Drie (1992).mp3", "rommel.mp3"]


def _wait(w):
    deadline = time.monotonic() + 10
    while (w.busy or w._batch_worker is not None) and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    for _ in range(3):
        QApplication.processEvents()


@pytest.fixture
def window(qapp, tmp_path):
    music = tmp_path / "muziek"
    music.mkdir()
    for n in NAMES:
        (music / n).write_bytes(b"x")
    w = MainWindow(SettingsStore.load(tmp_path / "c"), QThreadPool(), JournalStore(tmp_path / "j"))
    trashed: list[str] = []

    def fake_trash(path: str) -> None:
        trashed.append(path)
        Path(path).unlink()

    w.trash_function = fake_trash
    w.trashed = trashed  # type: ignore[attr-defined]
    w.resize(1200, 600)
    w.show()
    w.activateWindow()
    QTest.qWaitForWindowActive(w)
    w.start_scan(music)
    _wait(w)
    w.table.setFocus()
    yield w
    w.model.edits.clear()
    w.close()
    w.deleteLater()


def _select(w, rows):
    sm = w.table.selectionModel()
    f = QItemSelectionModel.SelectionFlag
    sm.clearSelection()
    for r in rows:
        sm.select(w.proxy.index(r, 0), f.Select | f.Rows)
    sm.setCurrentIndex(w.proxy.index(rows[0], Col.ARTIST), f.NoUpdate)


class _AcceptDialog:
    """Vervangt DeleteDialog: toont niets, legt de lijst vast en kiest de opgegeven optie."""

    last: "_AcceptDialog | None" = None

    def __init__(self, permanent: bool, accept: bool = True):
        self.permanent, self.accept = permanent, accept

    def __call__(self, paths, parent=None):
        self.paths = list(paths)
        _AcceptDialog.last = self
        return self

    @property
    def is_permanent(self):
        return self.permanent

    def exec(self):
        return QDialog.DialogCode.Accepted if self.accept else QDialog.DialogCode.Rejected


def test_del_key_trashes_selected_after_confirmation(window, monkeypatch):
    fake = _AcceptDialog(permanent=False)
    monkeypatch.setattr(main_window_module, "DeleteDialog", fake)
    _select(window, [0, 2])
    QTest.keyClick(window.table, Qt.Key.Key_Delete)
    _wait(window)
    assert fake.paths == ["A - Een (1990).mp3", "C - Drie (1992).mp3"]
    assert [Path(p).name for p in window.trashed] == fake.paths
    assert window.proxy.rowCount() == 2
    window._update_stats()
    assert "Totaal: 2" in window.stats_label.text()
    assert "naar de Prullenbak" in window.last_report


def test_cancel_deletes_nothing(window, monkeypatch):
    monkeypatch.setattr(main_window_module, "DeleteDialog", _AcceptDialog(False, accept=False))
    _select(window, [0])
    window.delete_selected()
    _wait(window)
    assert window.trashed == []
    assert window.proxy.rowCount() == 4


def test_permanent_delete_skips_trash(window, monkeypatch):
    monkeypatch.setattr(main_window_module, "DeleteDialog", _AcceptDialog(permanent=True))
    _select(window, [1])
    root = window._root
    window.delete_selected()
    _wait(window)
    assert window.trashed == []
    assert not (root / "B - Twee (1991).mp3").exists()
    assert "permanent" in window.last_report


def test_delete_stops_playback_and_discards_edits(window, monkeypatch):
    monkeypatch.setattr(main_window_module, "DeleteDialog", _AcceptDialog(False))
    tid = window.model.track_id(0)
    window.model.set_field([tid], Field.TITLE, "X")
    window.toggle_play(tid)
    _select(window, [0])
    window.delete_selected()
    assert window.player.current_track is None
    _wait(window)
    assert window.model.changed_count() == 0
    assert all(i.track_id != tid for i in window.plan_inputs())


def test_del_in_editor_does_not_delete(window, monkeypatch):
    called = []
    monkeypatch.setattr(main_window_module, "DeleteDialog", lambda *a, **k: called.append(1))
    _select(window, [0])
    window.table.edit(window.proxy.index(0, Col.TITLE))
    editor = QApplication.focusWidget()
    QTest.keyClick(editor, Qt.Key.Key_Delete)
    assert called == []


# --- het dialoog zelf ---------------------------------------------------------------------


def test_dialog_lists_files_and_defaults_to_trash(qapp):
    d = DeleteDialog(["a.mp3", "b.mp3"])
    assert d.list.count() == 2
    assert "2 bestanden naar de Prullenbak" in d.heading.text()
    assert d.ok_button.text() == "Naar Prullenbak"
    assert not d.is_permanent
    assert d.warning.isHidden()


def test_permanent_needs_extra_confirmation(qapp, monkeypatch):
    d = DeleteDialog(["a.mp3"])
    d.permanent.setChecked(True)
    assert "permanent" in d.heading.text()
    assert d.cancel_button.isDefault()
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: answers.pop(0)))
    d.accept()
    assert d.result() != QDialog.DialogCode.Accepted  # 'Nee' bij de tweede vraag
    d.accept()
    assert d.result() == QDialog.DialogCode.Accepted
