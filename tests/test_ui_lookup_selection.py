"""Artiest opzoeken met alleen de geselecteerde tekst uit de cel-editor."""

import time

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMenu

from mp3sanitizer.core.journal import JournalStore
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.ui import main_window as main_window_module
from mp3sanitizer.ui.main_window import MainWindow
from mp3sanitizer.ui.track_model import Col


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
    music.mkdir()
    (music / "Queen & David Bowie - Under Pressure (1981).mp3").write_bytes(b"x")
    w = MainWindow(SettingsStore.load(tmp_path / "c"), QThreadPool(), JournalStore(tmp_path / "j"))
    w.start_scan(music)
    wait_for(lambda: not w.busy)
    w.show()
    yield w
    w.model.edits.clear()
    w.close()


@pytest.fixture
def captured(monkeypatch):
    names: list[str] = []

    class FakeMB:
        def __init__(self, client, name, pool, parent=None):
            names.append(name)
            self.chosen = None

        def exec(self):
            return QDialog.DialogCode.Rejected

    class FakeArtists:
        def __init__(self, *args, query="", **kwargs):
            names.append(query)
            self.threshold_slider = type("S", (), {"value": lambda self: 85})()
            self.tabs = None

        def exec(self):
            return 0

    monkeypatch.setattr(main_window_module, "MusicBrainzDialog", FakeMB)
    monkeypatch.setattr(main_window_module, "ArtistDialog", FakeArtists)
    return names


def _open_editor(w) -> QLineEdit:
    index = w.proxy.index(0, Col.ARTIST)
    w.table.setCurrentIndex(index)
    w.table.edit(index)
    wait_for(lambda: isinstance(QApplication.focusWidget(), QLineEdit))
    editor = QApplication.focusWidget()
    assert editor.text() == "Queen & David Bowie"
    return editor


def test_selected_text_is_used_for_lookups(window, captured):
    editor = _open_editor(window)
    editor.setSelection(8, 11)  # "David Bowie"
    window.lookup_musicbrainz()
    window.open_artist_dialog()
    assert captured == ["David Bowie", "David Bowie"]


def test_single_letters_only_when_really_selected(window, captured):
    editor = _open_editor(window)
    editor.setSelection(0, 1)
    window.lookup_musicbrainz()
    editor.deselect()
    editor.setCursorPosition(3)  # cursor midden in "Queen", niets geselecteerd
    window.lookup_musicbrainz()
    window.open_artist_dialog()
    # Zonder selectie: de eerste artiest (MusicBrainz) of het hele veld (zoeken).
    assert captured == ["Q", "Queen", "Queen & David Bowie"]


def test_editor_context_menu_offers_lookups_with_selection(window, captured):
    window.table.selectRow(0)
    menu = QMenu()
    window._add_editor_lookup_actions(menu, "  David   Bowie ")
    texts = [a.text() for a in menu.actions()]
    assert texts[0] == "Artiest “David Bowie” zoeken en corrigeren…"
    menu.actions()[1].trigger()
    assert captured == ["David Bowie"]
    empty = QMenu()
    window._add_editor_lookup_actions(empty, "")
    assert not any(a.isEnabled() for a in empty.actions())
