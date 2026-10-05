"""Artiestencontrole-dialoog met een nep-MusicBrainz."""

import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from mp3sanitizer.core.musicbrainz import RecordingCandidate
from mp3sanitizer.core.scanner import track_from_path
from mp3sanitizer.core.settings import Settings
from mp3sanitizer.ui.artist_review_dialog import ArtistReviewDialog, Col
from mp3sanitizer.ui.track_model import TrackTableModel

NAMES = [
    "beatles - Help! (1965).mp3",
    "beatles - Yesterday (1965).mp3",
    "Queen & david bowie - Under Pressure (1981).mp3",
    "Nirvana - Rainbow Chaser (1968).mp3",
    "Nirvana - Lithium (1991).mp3",
    "Zappa - Unknown Song (1975).mp3",
]


def rec(title, credits, year):
    return RecordingCandidate("r", title, "", year, "", "", 100, None, tuple(credits))


TABLE = {
    "Help!": [rec("Help!", [("b", "The Beatles")], 1965)],
    "Yesterday": [rec("Yesterday", [("b", "The Beatles")], 1965)],
    "Under Pressure": [rec("Under Pressure", [("q", "Queen"), ("d", "David Bowie")], 1981)],
    "Rainbow Chaser": [rec("Rainbow Chaser", [("n68", "Nirvana")], 1968)],
    "Lithium": [rec("Lithium", [("n91", "Nirvana")], 1992)],
}


class FakeMB:
    def __init__(self):
        self.calls = []

    def search_recording(self, artist, title):
        self.calls.append((artist, title))
        return TABLE.get(title, [])


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    assert condition()


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


def _dialog(model, pool, settings=None, mb=None):
    mb = mb or FakeMB()
    d = ArtistReviewDialog(model, pool, lambda: mb, settings or Settings())
    return d, mb


def _run(d, *letters):
    for letter in letters:
        d.letter_buttons[letter].setChecked(True)
    d.start()
    wait_for(lambda: d._worker is None)


def _top(d, name):
    return d._items[name]


def test_letters_show_counts_and_disable_empty(model, pool):
    d, _ = _dialog(model, pool)
    assert d.letter_buttons["B"].isEnabled()
    assert "2 artiesten" not in d.letter_buttons["B"].toolTip()
    assert d.letter_buttons["B"].toolTip() == "1 artiesten, 2 tracks"
    assert not d.letter_buttons["X"].isEnabled()
    d.letter_buttons["N"].setChecked(True)
    assert "1 artiesten, 2 tracks" in d.selection_label.text()


def test_review_only_selected_letters(model, pool):
    d, mb = _dialog(model, pool)
    _run(d, "B", "Q")
    assert set(d._items) == {"beatles", "Queen"}
    assert {title for _, title in mb.calls} == {"Help!", "Yesterday", "Under Pressure"}
    beatles = _top(d, "beatles")
    assert beatles.text(Col.PROPOSAL) == "The Beatles"
    assert beatles.text(Col.STATUS) == "Voorstel"
    assert _top(d, "Queen").text(Col.STATUS) == "Juist"


def test_same_name_split_and_not_found(model, pool):
    d, _ = _dialog(model, pool)
    d.filter_combo.setCurrentIndex(1)  # alles
    _run(d, "N", "Z")
    nirvana = _top(d, "Nirvana")
    assert nirvana.text(Col.STATUS) == "Meerdere artiesten"
    assert nirvana.checkState(Col.ARTIST) == Qt.CheckState.Unchecked
    assert _top(d, "Zappa").text(Col.STATUS) == "Niet gevonden"


def test_apply_renames_collaboration_part_and_remembers(model, pool):
    settings = Settings()
    d, _ = _dialog(model, pool, settings)
    _run(d, "B", "D")
    bowie = _top(d, "david bowie")
    assert bowie.text(Col.PROPOSAL) == "David Bowie"
    d.filter_combo.setCurrentIndex(1)
    d.apply_checked()
    e = model.edits
    assert e.artist(0) == "The Beatles" and e.artist(1) == "The Beatles"
    assert e.artist(2) == "Queen & David Bowie"  # alleen die artiest vervangen
    assert settings.artist_review["beatles"] == "approved"
    assert settings.artist_review["david bowie"] == "approved"
    assert d.tree.topLevelItemCount() == 0
    model.undo_stack.undo()  # één undo-stap voor de hele toepassing
    assert e.artist(0) == "beatles" and e.artist(2) == "Queen & david bowie"


def test_edited_proposal_applies_to_all_tracks(model, pool):
    d, _ = _dialog(model, pool)
    _run(d, "B")
    top = _top(d, "beatles")
    top.setText(Col.PROPOSAL, "Beatles, The")
    assert {top.child(j).text(Col.PROPOSAL) for j in range(top.childCount())} == {"Beatles, The"}
    top.child(1).setCheckState(Col.ARTIST, Qt.CheckState.Unchecked)
    d.apply_checked()
    assert model.edits.artist(0) == "Beatles, The"
    assert model.edits.artist(1) == "beatles"


def test_ignored_artists_are_skipped_next_time(model, pool):
    settings = Settings()
    d, _ = _dialog(model, pool, settings)
    d.filter_combo.setCurrentIndex(1)
    _run(d, "Z")
    _top(d, "Zappa").setCheckState(Col.ARTIST, Qt.CheckState.Checked)
    d.ignore_checked()
    assert settings.artist_review == {"zappa": "ignored"}
    d2, _ = _dialog(model, pool, settings)
    assert not d2.letter_buttons["Z"].isEnabled()
    assert d2.letter_buttons["Z"].text() == "Z✓"
    d2.include_reviewed.setChecked(True)
    assert d2.letter_buttons["Z"].isEnabled()


class StrictMB:
    """Vindt alleen iets als de artiest goed geschreven is (zoals MusicBrainz in de praktijk)."""

    def __init__(self):
        self.calls = []

    def search_recording(self, artist, title):
        self.calls.append((artist, title))
        if "queen" not in artist.casefold():
            return []
        credits = [("q", "Queen")]
        if "bowie" in artist.casefold():
            credits.append(("d", "David Bowie"))
        return [rec(title, credits, 1981)]


def test_correct_name_and_search_again_keeps_dialog_open(qapp, pool, tmp_path):
    names = ["Quien & David Bowie - Under Pressure (1981).mp3", "Quien - Innuendo (1991).mp3"]
    m = TrackTableModel()
    m.undo_stack = QUndoStack()
    m.append_tracks([track_from_path(i, tmp_path / n, tmp_path) for i, n in enumerate(names)])
    mb = StrictMB()
    d, _ = _dialog(m, pool, mb=mb)
    _run(d, "Q")
    top = _top(d, "Quien")
    assert top.text(Col.STATUS) == "Niet gevonden"
    d.recheck(top, "  Queen ")
    wait_for(lambda: _top(d, "Quien").text(Col.STATUS) == "Voorstel")
    assert ("Queen & David Bowie", "Under Pressure") in mb.calls  # alleen Quien vervangen
    top = _top(d, "Quien")
    assert top.text(Col.PROPOSAL) == "Queen"
    assert top.checkState(Col.ARTIST) == Qt.CheckState.Checked
    d.apply_checked()
    assert m.edits.artist(0) == "Queen & David Bowie"
    assert m.edits.artist(1) == "Queen"


def test_recheck_not_found_proposes_own_correction(qapp, pool, tmp_path):
    m = TrackTableModel()
    m.undo_stack = QUndoStack()
    m.append_tracks([track_from_path(0, tmp_path / "Quien - Song (1990).mp3", tmp_path)])
    d, _ = _dialog(m, pool, mb=StrictMB())
    _run(d, "Q")
    d.recheck(_top(d, "Quien"), "Quinn")
    wait_for(lambda: _top(d, "Quien").text(Col.STATUS) == "Niet gevonden")
    top = _top(d, "Quien")
    assert top.text(Col.PROPOSAL) == "Quinn"
    assert top.checkState(Col.ARTIST) == Qt.CheckState.Checked
