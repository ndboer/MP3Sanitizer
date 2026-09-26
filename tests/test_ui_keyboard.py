"""Toetsenbordbediening van het hoofdvenster (echte key events via QTest)."""

import time

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from mp3sanitizer.core.models import Field
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.ui.main_window import MainWindow
from mp3sanitizer.ui.proxy_model import QuickFilter
from mp3sanitizer.ui.track_model import Col

NAMES = ["ABBA - Waterloo (1974).mp3", "Help! - Beatles.mp3", "Queen - Innuendo (1991).mp3"]


def _wait(qapp, window):
    deadline = time.monotonic() + 10
    while window.busy and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()


@pytest.fixture
def window(qapp, tmp_path):
    music = tmp_path / "muziek"
    music.mkdir()
    for name in NAMES:
        (music / name).write_bytes(b"")
    w = MainWindow(SettingsStore.load(tmp_path / "config"), QThreadPool())
    w.resize(1200, 600)
    w.show()
    w.activateWindow()
    assert QTest.qWaitForWindowActive(w)
    w.start_scan(music)
    _wait(qapp, w)
    w.table.setFocus()
    w.table.setCurrentIndex(w.proxy.index(0, Col.FILENAME))  # ABBA (gesorteerd op artiest)
    yield w
    w.model.edits.clear()  # geen bevestigingsvraag bij het afsluiten
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def _row_text(w, row, col):
    return w.proxy.index(row, col).data()


def _flush():
    for _ in range(3):
        QApplication.processEvents()


def test_f2_on_non_editable_column_edits_artist(window):
    QTest.keyClick(window.table, Qt.Key.Key_F2)
    editor = QApplication.focusWidget()
    assert editor is not window.table
    QTest.keyClicks(editor, "ABBA Gold")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    _flush()
    assert _row_text(window, 0, Col.ARTIST) == "ABBA Gold"
    window._update_stats()
    assert "Gewijzigd: 1" in window.stats_label.text()

    QTest.keyClick(window.table, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    _flush()
    assert _row_text(window, 0, Col.ARTIST) == "ABBA"
    QTest.keyClick(window.table, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    _flush()
    assert _row_text(window, 0, Col.ARTIST) == "ABBA Gold"


def test_ctrl_w_swaps_and_ctrl_r_reverts(window):
    # Direct via het selectionmodel: selectRow() kijkt naar de (in offscreen-tests soms
    # 'blijvende') Ctrl-modifier van een vorige test.
    index = window.proxy.index(1, Col.ARTIST)  # Help! - Beatles
    flags = QItemSelectionModel.SelectionFlag
    window.table.selectionModel().setCurrentIndex(index, flags.ClearAndSelect | flags.Rows)
    assert window.selected_track_ids() == [1]
    QTest.keyClick(window.table, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
    _flush()
    assert (_row_text(window, 1, Col.ARTIST), _row_text(window, 1, Col.TITLE)) == (
        "Beatles",
        "Help!",
    )
    QTest.keyClick(window.table, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    _flush()
    assert _row_text(window, 1, Col.ARTIST) == "Help!"
    assert window.model.changed_count() == 0


def test_ctrl_w_in_search_field_does_not_swap(window):
    QTest.keyClick(window.table, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    _flush()
    assert window.search_edit.hasFocus()
    QTest.keyClick(window.search_edit, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
    _flush()
    assert window.model.changed_count() == 0


def test_changed_filter_updates_after_edit(window):
    QTest.keyClick(window.table, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert window.proxy.quick_filter is QuickFilter.CHANGED
    assert window.proxy.rowCount() == 0
    window.model.set_field([0], Field.YEAR, 1975)
    _flush()
    assert window.proxy.rowCount() == 1


def test_close_asks_confirmation_with_pending_changes(window, monkeypatch):
    window.swap_selected()
    asked = []

    def fake_warning(*args, **kwargs):
        asked.append(args[2])
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(fake_warning))
    assert not window.close()
    assert "1 tracks met niet-opgeslagen wijzigingen" in asked[0]
    assert window.isVisible()


def test_escape_in_editor_cancels_without_error(window):
    """Qt roept model.revert() aan bij Esc; dat mocht niet botsen met onze eigen methode."""
    import sys

    errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda *exc: errors.append(exc)
    try:
        QTest.keyClick(window.table, Qt.Key.Key_F2)
        editor = QApplication.focusWidget()
        QTest.keyClicks(editor, "iets anders")
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        _flush()
    finally:
        sys.excepthook = old_hook
    assert errors == []
    assert _row_text(window, 0, Col.ARTIST) == "ABBA"  # niets gewijzigd
    assert window.model.changed_count() == 0
