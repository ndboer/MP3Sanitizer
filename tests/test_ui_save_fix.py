"""Herstellen in de opslaan-preview en een track opzoeken op MusicBrainz (artiest + titel)."""

import time

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QDialog

from mp3sanitizer.core.journal import JournalStore
from mp3sanitizer.core.models import Field
from mp3sanitizer.core.musicbrainz import MusicBrainzError, RecordingCandidate
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.core.validate import sanitize_text
from mp3sanitizer.ui import main_window as main_window_module
from mp3sanitizer.ui import save_dialog as save_dialog_module
from mp3sanitizer.ui.main_window import MainWindow
from mp3sanitizer.ui.preview_dialog import PCol
from mp3sanitizer.ui.recording_dialog import RecordingDialog
from mp3sanitizer.ui.save_dialog import SavePreviewDialog, TrackEditDialog

FILES = {
    "ACDC - Thunderstruck (1990).mp3": b"A",
    "Queen - Innuendo (1991).mp3": b"Q1",
    "dubbel/queen - innuendo (1991).mp3": b"Q2",
}


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    assert condition()


@pytest.fixture
def window(qapp, tmp_path):
    music = tmp_path / "muziek"
    for rel, data in FILES.items():
        path = music / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    w = MainWindow(SettingsStore.load(tmp_path / "c"), QThreadPool(), JournalStore(tmp_path / "j"))
    w.trash_function = lambda path: __import__("os").remove(path)
    w.start_scan(music)
    wait_for(lambda: not w.busy)
    yield w
    w.model.edits.clear()
    w.close()


def _tid(w, filename):
    return next(t.id for t in w.model.tracks if t.filename == filename)


def _select(dialog, tid):
    for r in range(dialog.proxy.rowCount()):
        index = dialog.proxy.index(r, PCol.CHECK)
        if dialog.model.items[dialog.proxy.mapToSource(index).row()].key == tid:
            dialog.table.clearSelection()
            dialog.table.selectRow(r)
            return
    raise AssertionError(f"track {tid} staat niet in de preview")


def test_sanitize_text():
    assert sanitize_text("Artiest: Titel") == "Artiest - Titel"
    assert sanitize_text("AC/DC") == "AC-DC"
    assert sanitize_text('Why? "Now" *') == "Why 'Now'"
    assert sanitize_text("a|b<c>") == "a-b(c)"


def test_sanitize_invalid_characters_unblocks_save(window):
    tid = _tid(window, "ACDC - Thunderstruck (1990).mp3")
    window.model.set_field([tid], Field.ARTIST, "AC/DC")
    d = SavePreviewDialog(window.plan_inputs(), window._root, window._settings, fixer=window)
    assert d.plans[tid].blocked
    _select(d, tid)
    assert d.sanitize_button.isEnabled()
    d.sanitize_selected()
    assert window.model.edits.artist(tid) == "AC-DC"
    assert not d.plans[tid].blocked
    assert window.undo_stack.undoText().startswith("Ongeldige tekens vervangen")


def test_edit_selected_updates_track(window, monkeypatch):
    tid = _tid(window, "ACDC - Thunderstruck (1990).mp3")
    window.model.set_field([tid], Field.TITLE, "Thunder?struck")
    d = SavePreviewDialog(window.plan_inputs(), window._root, window._settings, fixer=window)
    _select(d, tid)

    class Edit:
        def __init__(self, artist, title, year, parent=None):
            assert title == "Thunder?struck"

        def exec(self):
            return QDialog.DialogCode.Accepted

        def values(self):
            return "AC/DC fans", "Thunderstruck", 1990

    monkeypatch.setattr(save_dialog_module, "TrackEditDialog", Edit)
    d.edit_selected()
    assert window.model.edits.title(tid) == "Thunderstruck"
    assert d.plans[tid].blocked  # 'AC/DC fans' is nog steeds ongeldig


def test_track_edit_dialog_validates(qapp):
    d = TrackEditDialog("AC/DC", "Back: in Black", 1980)
    ok = d.buttons.button(d.buttons.StandardButton.Ok)
    assert not ok.isEnabled() and d.fix_button.isEnabled()
    d.sanitize()
    assert (d.artist_edit.text(), d.title_edit.text()) == ("AC-DC", "Back - in Black")
    assert ok.isEnabled()
    d.year_edit.setText("abc")
    assert not ok.isEnabled()


def test_delete_duplicate_from_preview(window, monkeypatch):
    dup = _tid(window, "queen - innuendo (1991).mp3")
    window.model.set_field([dup], Field.ARTIST, "Queen")
    window._settings.folder_template = "none"
    d = SavePreviewDialog(window.plan_inputs(), window._root, window._settings, fixer=window)
    assert dup in d.plans

    class Confirm:
        is_permanent = False

        def __init__(self, paths, parent=None):
            assert paths == ["dubbel\\queen - innuendo (1991).mp3"] or len(paths) == 1

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module, "DeleteDialog", Confirm)
    _select(d, dup)
    d.delete_selected()
    assert window.model.is_deleted_id(dup)
    assert dup not in d.plans
    assert not (window._root / "dubbel" / "queen - innuendo (1991).mp3").exists()


def test_preview_without_fixer_hides_buttons(window):
    d = SavePreviewDialog(window.plan_inputs(), window._root, window._settings)
    assert d.edit_button.isHidden() and d.delete_button.isHidden()


# --- MusicBrainz: artiest + titel ----------------------------------------------------------

UNDER_PRESSURE = RecordingCandidate(
    "r1", "Under Pressure", "Queen & David Bowie", 1981, "Under Pressure", "", 100, 248
)


class FakeMB:
    def __init__(self, result=None):
        self.calls = []
        self.result = result if result is not None else [UNDER_PRESSURE]

    def search_recording(self, artist, title):
        self.calls.append((artist, title))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def pool():
    p = QThreadPool()
    yield p
    p.waitForDone(5000)


def test_recording_dialog_searches_and_takes_title(qapp, pool):
    mb = FakeMB()
    d = RecordingDialog(mb, "queen", "under presure", pool)
    wait_for(lambda: d.results.topLevelItemCount() == 1)
    assert mb.calls == [("queen", "under presure")]
    assert d.results.topLevelItem(0).text(3) == "4:08"
    assert d.values() == {"title": "Under Pressure"}
    d.take_artist.setChecked(True)
    d.take_year.setChecked(True)
    assert d.values() == {"title": "Under Pressure", "artist": "Queen & David Bowie", "year": 1981}
    d.take_title.setChecked(False)
    d.take_artist.setChecked(False)
    d.take_year.setChecked(False)
    assert not d.buttons.button(d.buttons.StandardButton.Ok).isEnabled()


def test_recording_dialog_shows_error(qapp, pool):
    d = RecordingDialog(FakeMB(MusicBrainzError("Geen verbinding")), "a", "b", pool)
    wait_for(lambda: d.status.text() == "Geen verbinding")


def test_lookup_recording_applies_values_as_one_undo_step(window, monkeypatch):
    tid = _tid(window, "Queen - Innuendo (1991).mp3")

    class Choose:
        def __init__(self, client, artist, title, pool, parent=None):
            assert (artist, title) == ("Queen", "Innuendo")

        def exec(self):
            return QDialog.DialogCode.Accepted

        def values(self):
            return {"title": "Innuendo (Remastered)", "year": 1992}

    monkeypatch.setattr(main_window_module, "RecordingDialog", Choose)
    window.show_track(tid)
    window.lookup_recording()
    assert window.model.edits.title(tid) == "Innuendo (Remastered)"
    assert window.model.edits.year(tid) == 1992
    window.undo_stack.undo()
    assert window.model.edits.title(tid) == "Innuendo"
    assert window.model.edits.year(tid) == 1991
