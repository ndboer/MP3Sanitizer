"""Bewerken, undo/redo, bulk, wisselen, terugdraaien en de bijbehorende filters."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack

from mp3sanitizer.core.models import Field
from mp3sanitizer.core.scanner import track_from_path
from mp3sanitizer.ui.proxy_model import QuickFilter, TrackFilterProxy
from mp3sanitizer.ui.track_model import (
    CHANGED_BACKGROUND,
    INVALID_BACKGROUND,
    Col,
    TrackTableModel,
)

NAMES = [
    "Queen - Innuendo (1991).mp3",
    "Help! - Beatles.mp3",
    "rommel.mp3",
]
EDIT = Qt.ItemDataRole.EditRole


@pytest.fixture
def setup(qapp, tmp_path: Path):
    model = TrackTableModel()
    stack = QUndoStack()
    model.undo_stack = stack
    model.append_tracks([track_from_path(i, tmp_path / n, tmp_path) for i, n in enumerate(NAMES)])
    proxy = TrackFilterProxy()
    proxy.setSourceModel(model)
    return model, stack, proxy


def _cell(model, track_id: int, col: Col):
    return model.index(model.row_of(track_id), col)


def test_editable_flags(setup):
    model, _, _ = setup
    assert _cell(model, 0, Col.ARTIST).flags() & Qt.ItemFlag.ItemIsEditable
    assert _cell(model, 0, Col.YEAR).flags() & Qt.ItemFlag.ItemIsEditable
    assert not _cell(model, 0, Col.FILENAME).flags() & Qt.ItemFlag.ItemIsEditable


def test_inline_edit_with_undo_redo(setup):
    model, stack, _ = setup
    idx = _cell(model, 0, Col.TITLE)
    assert idx.data(EDIT) == "Innuendo"
    assert model.setData(idx, "  The   Show Must Go On ", EDIT)
    assert idx.data() == "The Show Must Go On"
    assert model.changed_count() == 1
    assert idx.data(Qt.ItemDataRole.BackgroundRole) == CHANGED_BACKGROUND
    assert "Origineel: Innuendo" in idx.data(Qt.ItemDataRole.ToolTipRole)
    status = _cell(model, 0, Col.STATUS)
    assert status.data() == "Gewijzigd"
    assert "Queen - The Show Must Go On (1991).mp3" in status.data(Qt.ItemDataRole.ToolTipRole)
    assert stack.undoText() == "Titel wijzigen"

    stack.undo()
    assert idx.data() == "Innuendo"
    assert model.changed_count() == 0
    assert idx.data(Qt.ItemDataRole.BackgroundRole) is None
    stack.redo()
    assert idx.data() == "The Show Must Go On"


def test_same_value_is_no_undo_step(setup):
    model, stack, _ = setup
    assert model.setData(_cell(model, 0, Col.ARTIST), "Queen", EDIT)
    assert stack.count() == 0


def test_year_validation(setup):
    model, stack, _ = setup
    rejected = []
    model.editRejected.connect(rejected.append)
    idx = _cell(model, 0, Col.YEAR)
    assert not model.setData(idx, "19x1", EDIT)
    assert not model.setData(idx, "1850", EDIT)
    assert len(rejected) == 2
    assert stack.count() == 0
    assert model.setData(idx, "", EDIT)  # leeg = jaar weghalen
    assert idx.data() == ""
    assert _cell(model, 0, Col.STATUS).data() == "Gewijzigd"


def test_empty_artist_rejected(setup):
    model, _, _ = setup
    rejected = []
    model.editRejected.connect(rejected.append)
    assert not model.setData(_cell(model, 0, Col.ARTIST), "   ", EDIT)
    assert rejected == ["Artiest mag niet leeg zijn"]


def test_invalid_chars_are_marked(setup):
    model, _, proxy = setup
    idx = _cell(model, 0, Col.ARTIST)
    assert model.setData(idx, "AC/DC", EDIT)
    assert idx.data(Qt.ItemDataRole.BackgroundRole) == INVALID_BACKGROUND
    assert "Windows" in idx.data(Qt.ItemDataRole.ToolTipRole)
    assert _cell(model, 0, Col.STATUS).data() == "Gewijzigd · ongeldig"
    proxy.set_quick_filter(QuickFilter.INVALID)
    # parse-fout (lege artiest) + AC/DC
    assert sorted(proxy.index(r, Col.FILENAME).data() for r in range(proxy.rowCount())) == [
        "Queen - Innuendo (1991).mp3",
        "rommel.mp3",
    ]


def test_bulk_edit_is_one_undo_step(setup):
    model, stack, _ = setup
    assert model.set_field([0, 1, 2], Field.YEAR, 1999)
    assert stack.count() == 1
    assert stack.undoText() == "Jaar invullen (3 tracks)"
    assert [model.edits.year(i) for i in range(3)] == [1999, 1999, 1999]
    stack.undo()
    assert [model.edits.year(i) for i in range(3)] == [1991, None, None]


def test_bulk_edit_skips_tracks_that_already_match(setup):
    model, stack, _ = setup
    assert model.set_field([0], Field.ARTIST, "Queen") is False
    assert stack.count() == 0


def test_swap_and_revert(setup):
    model, stack, _ = setup
    assert model.swap_artist_title([1])
    assert (model.edits.artist(1), model.edits.title(1)) == ("Beatles", "Help!")
    assert stack.undoText() == "Wissel artiest ⇄ titel (1 tracks)"
    model.setData(_cell(model, 1, Col.YEAR), "1965", EDIT)
    assert model.revert([1])
    assert not model.edits.is_changed(1)
    stack.undo()  # terugdraaien is zelf ongedaan te maken
    assert model.edits.year(1) == 1965
    assert model.edits.artist(1) == "Beatles"


def test_changed_and_no_year_filters_use_effective_values(setup):
    model, _, proxy = setup
    proxy.set_quick_filter(QuickFilter.NO_YEAR)
    assert proxy.rowCount() == 2
    model.set_field([1], Field.YEAR, 1965)
    proxy.refresh()
    assert proxy.rowCount() == 1
    proxy.set_quick_filter(QuickFilter.CHANGED)
    assert proxy.rowCount() == 1
    assert proxy.index(0, Col.ARTIST).data() == "Help!"


def test_sort_uses_edited_values_after_resort(setup):
    model, _, proxy = setup
    proxy.sort(Col.ARTIST, Qt.SortOrder.AscendingOrder)
    assert model.track(0).id == 1  # "Help!" < "Queen"
    model.setData(_cell(model, 1, Col.ARTIST), "The Zombies", EDIT)
    assert model.track(0).id == 1  # niet automatisch hersorteren
    model.resort()
    assert [model.track(r).id for r in range(3)] == [0, 1, 2]  # Queen, Zombies, (leeg)


def test_search_uses_edited_values(setup):
    model, _, proxy = setup
    model.setData(_cell(model, 2, Col.ARTIST), "Prince", EDIT)
    proxy.set_text_filter("prince")
    assert proxy.rowCount() == 1


def test_parse_error_fixed_by_editing(setup):
    model, _, _ = setup
    status = _cell(model, 2, Col.STATUS)
    assert status.data() == "Parse-fout"
    model.setData(_cell(model, 2, Col.ARTIST), "Prince", EDIT)
    assert status.data() == "Gewijzigd"
    assert model.target_filename(2) == "Prince - rommel.mp3"
