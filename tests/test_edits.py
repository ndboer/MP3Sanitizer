from pathlib import Path

from mp3sanitizer.core.edits import EditState
from mp3sanitizer.core.models import Field, PendingChange
from mp3sanitizer.core.scanner import track_from_path


def _state():
    root = Path("/muziek")
    tracks = [
        track_from_path(0, root / "Queen - Innuendo (1991).mp3", root),
        track_from_path(1, root / "Help! - Beatles.mp3", root),
    ]
    return tracks, EditState(tracks)


def test_value_falls_back_to_original():
    _, state = _state()
    assert state.artist(0) == "Queen"
    assert state.year(0) == 1991
    assert state.year(1) is None
    assert not state.is_changed(0)
    assert len(state) == 0


def test_change_and_apply_and_undo():
    _, state = _state()
    change = state.change(0, Field.ARTIST, "Queen + Adam Lambert")
    assert change == PendingChange(0, Field.ARTIST, "Queen", "Queen + Adam Lambert")
    assert state.artist(0) == "Queen"  # change() past nog niets toe
    assert state.apply([change]) == {0}
    assert state.artist(0) == "Queen + Adam Lambert"
    assert state.is_changed(0, Field.ARTIST)
    assert not state.is_changed(0, Field.TITLE)
    assert state.changed_ids == {0}
    state.apply([change], forward=False)
    assert state.artist(0) == "Queen"
    assert not state.is_changed(0)


def test_no_change_when_equal():
    _, state = _state()
    assert state.change(0, Field.YEAR, 1991) is None


def test_setting_back_to_original_removes_override():
    _, state = _state()
    state.apply([state.change(0, Field.YEAR, 1990)])
    assert state.is_changed(0)
    state.apply([state.change(0, Field.YEAR, 1991)])
    assert not state.is_changed(0)
    assert len(state) == 0


def test_undo_restores_intermediate_override_in_order():
    _, state = _state()
    first = state.change(0, Field.TITLE, "A")
    state.apply([first])
    second = state.change(0, Field.TITLE, "B")
    assert second.old == "A"
    state.apply([second])
    state.apply([second], forward=False)
    assert state.title(0) == "A"
    state.apply([first], forward=False)
    assert state.title(0) == "Innuendo"


def test_multi_change_undo_is_reversed():
    _, state = _state()
    c1 = PendingChange(0, Field.TITLE, "Innuendo", "X")
    c2 = PendingChange(0, Field.TITLE, "X", "Y")
    state.apply([c1, c2])
    assert state.title(0) == "Y"
    state.apply([c1, c2], forward=False)
    assert state.title(0) == "Innuendo"


def test_swap():
    _, state = _state()
    changes = state.swap_changes([1])
    state.apply(changes)
    assert (state.artist(1), state.title(1)) == ("Beatles", "Help!")
    assert {c.source for c in changes} == {"swap"}
    state.apply(state.swap_changes([1]))
    assert not state.is_changed(1)


def test_revert():
    _, state = _state()
    state.apply([state.change(0, Field.ARTIST, "X"), state.change(0, Field.YEAR, None)])
    reverts = state.revert_changes([0, 1])
    assert len(reverts) == 2
    state.apply(reverts)
    assert not state.is_changed(0)
    state.apply(reverts, forward=False)  # terugdraaien is zelf ook ongedaan te maken
    assert state.artist(0) == "X"
    assert state.year(0) is None
    assert state.changed_fields(0) == (Field.ARTIST, Field.YEAR)
