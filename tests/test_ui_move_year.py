"""Menu 'Verplaatsen naar jaarmap'."""

import time

import pytest
from PySide6.QtCore import QItemSelectionModel, QThreadPool
from PySide6.QtWidgets import QApplication, QDialog

from mp3sanitizer.core.journal import JournalStore
from mp3sanitizer.core.models import Field
from mp3sanitizer.core.planner import FolderTemplate, PlanInput, PlanOptions, plan_renames
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.ui.main_window import MainWindow
from mp3sanitizer.ui.save_dialog import SavePreviewDialog

FILES = [
    "rommel/queen - innuendo (1991).mp3",
    "rommel/ABBA - Waterloo (1974).mp3",
    "1965/The Beatles - Help! (1965).mp3",
]


def _wait(w):
    deadline = time.monotonic() + 10
    while w.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    music = tmp_path / "muziek"
    for rel in FILES:
        (music / rel).parent.mkdir(parents=True, exist_ok=True)
        (music / rel).write_bytes(b"x")
    w = MainWindow(SettingsStore.load(tmp_path / "c"), QThreadPool(), JournalStore(tmp_path / "j"))
    w.start_scan(music)
    _wait(w)
    shown = []

    def accept(dialog):
        shown.append(dialog)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SavePreviewDialog, "exec", accept)
    w.shown_dialogs = shown
    yield w, music
    w.model.edits.clear()
    w.close()


def test_planner_keep_names_only_moves_unchanged(tmp_path):
    src = tmp_path / "rommel" / "queen - innuendo (1991).mp3"
    opts = PlanOptions(tmp_path, FolderTemplate.YEAR, include_unchanged=True, keep_names=True)
    unchanged = PlanInput(1, src, "Queen", "Innuendo", 1991, False)
    edited = PlanInput(2, tmp_path / "x.mp3", "ABBA", "SOS", 1975, True)
    plans = {p.track_id: p for p in plan_renames([unchanged, edited], opts, lambda p: False)}
    assert plans[1].dst == tmp_path / "1991" / "queen - innuendo (1991).mp3"
    assert plans[2].dst == tmp_path / "1975" / "ABBA - SOS (1975).mp3"


def test_move_all_to_year_folders_keeps_names(window):
    w, music = window
    w.move_to_year_folders()
    (dialog,) = w.shown_dialogs
    assert dialog.windowTitle() == "Verplaatsen naar jaarmap"
    assert dialog.keep_names.isChecked() and dialog.include_unchanged.isChecked()
    _wait(w)
    assert (music / "1991" / "queen - innuendo (1991).mp3").exists()
    assert (music / "1974" / "ABBA - Waterloo (1974).mp3").exists()
    assert (music / "1965" / "The Beatles - Help! (1965).mp3").exists()
    assert w._settings.folder_template == "none"  # gewone opslaan-instelling ongewijzigd


def test_move_only_selected_rows(window):
    w, music = window
    sm = w.table.selectionModel()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for r in range(w.proxy.rowCount()):
        if w.proxy.index(r, 0).siblingAtColumn(0).isValid():
            tid = w.model.track_id(w.proxy.mapToSource(w.proxy.index(r, 0)).row())
            if w.model.tracks[tid].filename != "ABBA - Waterloo (1974).mp3":
                sm.select(w.proxy.index(r, 0), flags)
    tid = next(t.id for t in w.model.tracks if t.filename.startswith("queen"))
    w.model.set_field([tid], Field.TITLE, "Innuendo")
    w.move_to_year_folders()
    _wait(w)
    assert (music / "1991" / "queen - Innuendo (1991).mp3").exists()  # bewerkt: nieuwe naam
    assert (music / "rommel" / "ABBA - Waterloo (1974).mp3").exists()  # niet geselecteerd


def test_clean_tags_menu_presets_dialog(window, monkeypatch):
    w, _music = window
    monkeypatch.setattr(SavePreviewDialog, "exec", lambda self: w.shown_dialogs.append(self) or 0)
    w.act_clean_tags.trigger()
    (dialog,) = w.shown_dialogs
    assert dialog.windowTitle() == "Tags schrijven en opschonen"
    assert dialog.write_tags.isChecked() and dialog.strip_tags.isChecked()
    assert dialog.options().strip_tags and dialog.options().folder_template is FolderTemplate.NONE
    assert all(p.strip_tags and not p.renames for p in dialog.plans.values())
    dialog.write_tags.setChecked(False)
    assert not dialog.strip_tags.isChecked() and not dialog.strip_tags.isEnabled()
