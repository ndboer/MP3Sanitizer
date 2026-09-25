"""Artiesten zoeken/corrigeren, clustervoorstellen en MusicBrainz (zonder netwerk)."""

import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QDialog

from mp3sanitizer.core.musicbrainz import ArtistCandidate, MusicBrainzError
from mp3sanitizer.core.scanner import track_from_path
from mp3sanitizer.ui import main_window as main_window_module
from mp3sanitizer.ui.artist_search import ArtistDialog, MusicBrainzDialog
from mp3sanitizer.ui.track_model import TrackTableModel

NAMES = [
    "The Beatles - Help! (1965).mp3",
    "The Beatles - Yesterday (1965).mp3",
    "Beatles - Let It Be (1970).mp3",
    "Beatles, The - Something (1969).mp3",
    "The Beatels - Girl (1965).mp3",
    "Queen - Innuendo (1991).mp3",
]


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    assert condition()


class FakeMB:
    def __init__(self, candidates=None, error=None):
        self.calls: list[str] = []
        self.candidates = candidates or [
            ArtistCandidate("b10b", "The Beatles", "Beatles, The", "GB", "UK rock band", 100),
            ArtistCandidate("x1", "Beatles Revival", "Beatles Revival", "", "tribute", 82),
        ]
        self.error = error

    def search_artist(self, name):
        self.calls.append(name)
        if self.error:
            raise self.error
        return self.candidates


@pytest.fixture
def model(qapp, tmp_path: Path):
    m = TrackTableModel()
    m.undo_stack = QUndoStack()
    m.append_tracks([track_from_path(i, tmp_path / n, tmp_path) for i, n in enumerate(NAMES)])
    return m


@pytest.fixture
def pool():
    p = QThreadPool()
    yield p
    p.waitForDone(5000)


def _dialog(model, pool, query="beatles", mb=None):
    d = ArtistDialog(model, pool, lambda: mb or FakeMB(), threshold=85, query=query)
    wait_for(
        lambda: d.results.topLevelItemCount() > 0 or d.search_status.text() == "Geen resultaten."
    )
    return d


def _groups(d):
    return [d.results.topLevelItem(i).text(0) for i in range(d.results.topLevelItemCount())]


def test_search_groups_per_spelling_with_counts(model, pool):
    d = _dialog(model, pool)
    groups = _groups(d)
    assert groups[0] == "The Beatles (2)"
    assert set(groups) == {"The Beatles (2)", "Beatles (1)", "Beatles, The (1)", "The Beatels (1)"}
    assert d.correct_edit.text() == "The Beatles"  # meestgebruikte schrijfwijze
    assert len(d.checked_track_ids()) == 5
    assert "5 tracks" in d.apply_button.text()


def test_apply_to_checked_is_one_undo_step(model, pool):
    d = _dialog(model, pool)
    # 'The Beatels' uitvinken
    for i in range(d.results.topLevelItemCount()):
        item = d.results.topLevelItem(i)
        if item.text(0).startswith("The Beatels"):
            item.setCheckState(0, Qt.CheckState.Unchecked)
    assert len(d.checked_track_ids()) == 4
    d.apply_search()
    artists = [model.edits.artist(i) for i in range(len(NAMES))]
    assert artists[:4] == ["The Beatles"] * 4
    assert artists[4] == "The Beatels"
    assert model.undo_stack.count() == 1
    assert model.undo_stack.undoText() == "Artiest invullen (2 tracks)"  # 2 waren al goed
    model.undo_stack.undo()
    assert model.edits.artist(2) == "Beatles"


def test_threshold_slider(model, pool):
    d = _dialog(model, pool, query="beatles")
    d.threshold_slider.setValue(100)
    wait_for(lambda: "The Beatels (1)" not in _groups(d))


def test_clusters_and_apply(model, pool):
    d = _dialog(model, pool)
    wait_for(lambda: d.clusters.topLevelItemCount() > 0)
    top = d.clusters.topLevelItem(0)
    assert top.text(0) == "The Beatles"
    assert top.text(1) == "5"
    assert d.cluster_edit.text() == "The Beatles"
    d.cluster_edit.setText("Beatles, The")
    d.apply_cluster()
    assert {model.edits.artist(i) for i in range(5)} == {"Beatles, The"}
    wait_for(lambda: d.cluster_status.text() == "Geen voorstellen gevonden.")


def test_overview_lists_all_artists(model, pool):
    d = _dialog(model, pool)
    counts = {
        d.overview.topLevelItem(i).text(0): d.overview.topLevelItem(i).text(1)
        for i in range(d.overview.topLevelItemCount())
    }
    assert counts["Queen"] == "1"
    assert counts["The Beatles"] == "2"
    d._search_from_overview(d.overview.findItems("Queen", Qt.MatchFlag.MatchExactly)[0])
    wait_for(lambda: _groups(d) == ["Queen (1)"])


def test_musicbrainz_dialog_uses_official_name(qapp, pool):
    mb = FakeMB()
    d = MusicBrainzDialog(mb, "beatles", pool)
    wait_for(lambda: d.results.topLevelItemCount() == 2)
    assert mb.calls == ["beatles"]
    first = d.results.topLevelItem(0)
    assert [first.text(c) for c in range(5)] == [
        "The Beatles",
        "Beatles, The",
        "GB",
        "UK rock band",
        "100",
    ]
    d.accept()
    assert d.chosen.name == "The Beatles"  # niet de sort-name


def test_musicbrainz_dialog_shows_error(qapp, pool):
    d = MusicBrainzDialog(FakeMB(error=MusicBrainzError("Geen verbinding")), "x", pool)
    wait_for(lambda: "Geen verbinding" in d.status.text())
    assert not d.buttons.button(d.buttons.StandardButton.Ok).isEnabled()


def test_lookup_from_context_menu_applies_to_selection(qapp, tmp_path, monkeypatch):
    from mp3sanitizer.core.journal import JournalStore
    from mp3sanitizer.core.settings import SettingsStore
    from mp3sanitizer.ui.main_window import MainWindow

    music = tmp_path / "m"
    music.mkdir()
    for n in NAMES[:3]:
        (music / n).write_bytes(b"")
    w = MainWindow(SettingsStore.load(tmp_path / "c"), QThreadPool(), JournalStore(tmp_path / "j"))
    w.start_scan(music)
    wait_for(lambda: not w.busy)

    class ChooseFirst:
        def __init__(self, client, name, pool, parent=None):
            self.chosen = ArtistCandidate("b10b", "The Beatles", "Beatles, The", "GB", "", 100)
            self.name = name

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module, "MusicBrainzDialog", ChooseFirst)
    w.table.selectAll()
    w.lookup_musicbrainz()
    assert {w.model.edits.artist(i) for i in range(3)} == {"The Beatles"}
    w.model.edits.clear()
    w.close()


def test_overview_sorts_by_sort_key(model, pool):
    d = _dialog(model, pool)
    names = [d.overview.topLevelItem(i).text(0) for i in range(d.overview.topLevelItemCount())]
    assert names.index("The Beatles") < names.index("Queen")
