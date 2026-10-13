"""Melding in plaats van een lege tabel/boom als het filter niets oplevert."""

import time

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from mp3sanitizer.core.journal import JournalStore
from mp3sanitizer.core.settings import Settings, SettingsStore
from mp3sanitizer.ui.artist_review_dialog import ArtistReviewDialog
from mp3sanitizer.ui.main_window import MainWindow
from mp3sanitizer.ui.preview_dialog import PreviewDialog, PreviewItem
from mp3sanitizer.ui.proxy_model import QuickFilter


def _process(n=3):
    for _ in range(n):
        QApplication.processEvents()


def _wait(w):
    deadline = time.monotonic() + 10
    while w.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    _process()


@pytest.fixture
def window(qapp, tmp_path):
    w = MainWindow(SettingsStore.load(tmp_path / "c"), QThreadPool(), JournalStore(tmp_path / "j"))
    w.resize(900, 500)
    w.show()
    yield w, tmp_path
    w.close()


def test_main_window_without_music(window):
    w, _ = window
    _process()
    assert w.empty_notice.isVisible()
    assert "Nog geen muziek ingelezen" in w.empty_notice.text()


def test_main_window_filter_without_hits(window):
    w, tmp_path = window
    music = tmp_path / "muziek"
    music.mkdir()
    (music / "Queen - Innuendo (1991).mp3").write_bytes(b"x")
    w.start_scan(music)
    _wait(w)
    assert not w.empty_notice.isVisible()
    w.search_edit.setText("queen 1975")
    w._apply_search()
    _process()
    assert w.empty_notice.isVisible()
    assert w.empty_notice.text() == "Het filter heeft geen tracks opgeleverd voor „queen 1975”."
    assert w.empty_notice.geometry() == w.table.rect()  # bedekt de hele tabel
    w.search_edit.setText("")
    w._apply_search()
    w.set_quick_filter(QuickFilter.PARSE_ERRORS)
    _process()
    assert "snelfilter: " in w.empty_notice.text()
    w.set_quick_filter(QuickFilter.ALL)
    _process()
    assert not w.empty_notice.isVisible()


def test_main_window_empty_folder(window):
    w, tmp_path = window
    empty = tmp_path / "leeg"
    empty.mkdir()
    w.start_scan(empty)
    _wait(w)
    assert "Geen audiobestanden gevonden" in w.empty_notice.text()


def test_preview_filter_without_hits(qapp):
    d = PreviewDialog("t", "d")
    d.show()
    d.set_items([PreviewItem(1, "Pad", "a.mp3", "b.mp3")])
    _process()
    assert not d.empty_notice.isVisible()
    d.filter_edit.setText("xyz")
    _process()
    assert d.empty_notice.isVisible()
    assert d.empty_notice.text() == "Het filter heeft geen regels opgeleverd voor „xyz”."
    d.filter_edit.setText("")
    d.set_items([])
    _process()
    assert "Er is niets te doen" in d.empty_notice.text()
    d.close()


def test_artist_review_notice(qapp, tmp_path):
    from PySide6.QtGui import QUndoStack

    from mp3sanitizer.core.scanner import track_from_path
    from mp3sanitizer.ui.track_model import TrackTableModel

    m = TrackTableModel()
    m.undo_stack = QUndoStack()
    m.append_tracks([track_from_path(0, tmp_path / "Queen - Innuendo (1991).mp3", tmp_path)])
    d = ArtistReviewDialog(m, QThreadPool(), lambda: None, Settings())
    d.show()
    _process()
    assert d.empty_notice.text().startswith("Kies één of meer beginletters")
    d.close()
