"""Opslaan via de preview, journaal en terugdraaien vanuit het hoofdvenster."""

import os
import time

import pytest
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mp3sanitizer.core.journal import JournalStore
from mp3sanitizer.core.models import Collision, Field
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.ui.main_window import MainWindow
from mp3sanitizer.ui.preview_dialog import Level, PCol, PreviewItem
from mp3sanitizer.ui.proxy_model import QuickFilter
from mp3sanitizer.ui.save_dialog import SavePreviewDialog
from mp3sanitizer.ui.track_model import Col

FILES = {
    "rommel/queen - innuendo (1991).mp3": b"Q",
    "rommel/Help! - Beatles (1965).mp3": b"H",
    "1974/ABBA - Waterloo (1974).mp3": b"A",
    "rommel/zonder patroon.mp3": b"Z",
}


def _wait(window):
    deadline = time.monotonic() + 10
    while window.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    for _ in range(3):
        QApplication.processEvents()


@pytest.fixture
def env(qapp, tmp_path):
    music = tmp_path / "muziek"
    for rel, data in FILES.items():
        path = music / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    store = SettingsStore.load(tmp_path / "config")
    journals = JournalStore(tmp_path / "journal")
    window = MainWindow(store, QThreadPool(), journals)
    window.start_scan(music)
    _wait(window)
    yield window, music, journals
    window.model.edits.clear()
    window.close()
    window.deleteLater()


def _tid(window, filename):
    return next(t.id for t in window.model.tracks if t.filename == filename)


def _dialog(window, **settings):
    for key, value in settings.items():
        setattr(window._settings, key, value)
    return SavePreviewDialog(window.plan_inputs(), window._root, window._settings, window)


def test_preview_lists_only_changed_tracks_by_default(env):
    window, _, _ = env
    dialog = _dialog(window)
    assert dialog.model.items == []
    assert not dialog.ok_button.isEnabled()

    window.model.swap_artist_title([_tid(window, "Help! - Beatles (1965).mp3")])
    dialog = _dialog(window)
    [item] = dialog.model.items
    assert item.old == os.path.join("rommel", "Help! - Beatles (1965).mp3")
    assert item.new == os.path.join("rommel", "Beatles - Help! (1965).mp3")
    assert dialog.ok_button.isEnabled()


def test_include_unchanged_normalizes_and_moves(env):
    window, _, _ = env
    dialog = _dialog(window, folder_template="year")
    dialog.include_unchanged.setChecked(True)
    news = sorted(i.new for i in dialog.model.items)
    assert news == [
        os.path.join("1965", "Help! - Beatles (1965).mp3"),
        os.path.join("1991", "queen - innuendo (1991).mp3"),
    ]  # parse-fout blijft buiten beschouwing; ABBA staat al goed


def test_preview_keeps_unchecked_rows_after_replan(env):
    window, _, _ = env
    dialog = _dialog(window)
    dialog.include_unchanged.setChecked(True)
    dialog.template_combo.setCurrentIndex(dialog.template_combo.findData("year"))
    assert len(dialog.model.items) == 2
    dialog.model.set_checked([0], False)
    key = dialog.model.items[0].key
    dialog.template_combo.setCurrentIndex(dialog.template_combo.findData("decade"))
    assert len(dialog.model.items) == 3  # nu staat ABBA (map 1974) ook verkeerd
    assert key not in dialog.checked_keys()
    assert len(dialog.checked_keys()) == 2


def test_space_and_select_buttons(env):
    window, _, _ = env
    dialog = _dialog(window, folder_template="year")
    dialog.include_unchanged.setChecked(True)
    dialog.show()
    dialog.select_none_button.click()
    assert dialog.checked_keys() == []
    assert not dialog.ok_button.isEnabled()
    dialog.table.setFocus()
    dialog.table.selectAll()
    QTest.keyClick(dialog.table, Qt.Key.Key_Space)
    assert len(dialog.checked_keys()) == 2
    dialog.filter_edit.setText("queen")
    assert dialog.proxy.rowCount() == 1
    dialog.select_none_button.click()  # werkt alleen op zichtbare regels
    assert len(dialog.checked_keys()) == 1
    dialog.close()


def test_blocked_rows_not_checkable(env):
    window, _, _ = env
    tid = _tid(window, "zonder patroon.mp3")
    window.model.set_field([tid], Field.YEAR, 2000)  # artiest ontbreekt nog
    dialog = _dialog(window)
    [item] = dialog.model.items
    assert not item.checkable
    assert item.level is Level.ERROR
    assert "artiest ontbreekt" in item.note
    assert dialog.proxy.index(0, PCol.CHECK).data() == "✕"


def test_save_updates_model_and_undo_restores(env):
    window, music, journals = env
    tid = _tid(window, "queen - innuendo (1991).mp3")
    window.model.set_field([tid], Field.ARTIST, "Queen")
    window.model.set_field([tid], Field.TITLE, "Innuendo")
    window.undo_stack.setClean()
    dialog = _dialog(window, folder_template="year", cleanup_empty_dirs=True)
    window.start_save(dialog.selected_plans(), cleanup_empty_dirs=True)
    _wait(window)

    new_path = music / "1991" / "Queen - Innuendo (1991).mp3"
    assert os.listdir(new_path.parent) == [new_path.name]  # echte schrijfwijze
    assert new_path.read_bytes() == b"Q"
    track = window.model.tracks[tid]
    assert track.path == new_path
    assert (track.artist, track.title) == ("Queen", "Innuendo")
    assert window.model.changed_count() == 0
    assert window.undo_stack.count() == 0
    assert "Opgeslagen: 1" in window.last_report
    row = window.model.row_of(tid)
    assert window.model.index(row, Col.FOLDER).data() == "1991"
    assert journals.latest_undoable() is not None

    window.start_undo(journals.latest_undoable())
    _wait(window)  # terugdraaien + opnieuw scannen
    assert (music / "rommel" / "queen - innuendo (1991).mp3").read_bytes() == b"Q"
    assert not new_path.exists()
    assert "Teruggedraaid: 1" in window.last_report
    assert any(t.filename == "queen - innuendo (1991).mp3" for t in window.model.tracks)
    assert journals.latest_undoable() is None


def test_mark_duplicate_on_collision(env):
    window, music, _ = env
    (music / "rommel" / "ABBA - Waterloo (1974).mp3").write_bytes(b"dubbel")
    window.start_scan(music)
    _wait(window)
    tid = _tid(window, "Help! - Beatles (1965).mp3")
    window.model.set_field([tid], Field.ARTIST, "ABBA")
    window.model.set_field([tid], Field.TITLE, "Waterloo")
    window.model.set_field([tid], Field.YEAR, 1974)
    dialog = _dialog(window, collision_policy=Collision.MARK_DUPLICATE.value)
    assert dialog.duplicate_ids() == [tid]
    assert dialog.selected_plans() == []
    window.model.flag_duplicates(dialog.duplicate_ids())
    status = window.model.index(window.model.row_of(tid), Col.STATUS).data()
    assert "duplicaat" in status


def test_wrong_folder_filter(env):
    window, _, _ = env
    window.set_quick_filter(QuickFilter.WRONG_FOLDER)
    assert window.proxy.rowCount() == 0  # geen sjabloon ingesteld
    window._settings.folder_template = "year"
    window._apply_folder_rule()
    QApplication.processEvents()
    names = sorted(
        window.proxy.index(r, Col.FILENAME).data() for r in range(window.proxy.rowCount())
    )
    assert names == [
        "Help! - Beatles (1965).mp3",
        "queen - innuendo (1991).mp3",
        "zonder patroon.mp3",
    ]


def test_preview_item_defaults():
    item = PreviewItem("k", "Pad", "a", "b")
    assert item.checkable and item.checked and item.level is Level.OK
