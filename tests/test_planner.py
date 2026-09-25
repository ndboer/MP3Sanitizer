from pathlib import Path

import pytest

from mp3sanitizer.core.models import Collision, PlanWarning
from mp3sanitizer.core.planner import (
    MAX_PATH,
    DecadeStyle,
    FolderTemplate,
    PlanInput,
    PlanOptions,
    folder_for_year,
    is_misplaced,
    plan_renames,
)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def _inp(tid, src, artist, title, year=None, changed=True, tag_mismatch=False):
    return PlanInput(tid, src, artist, title, year, changed, tag_mismatch)


@pytest.mark.parametrize(
    ("year", "template", "style", "expected"),
    [
        (1985, FolderTemplate.NONE, DecadeStyle.RANGE, None),
        (1985, FolderTemplate.YEAR, DecadeStyle.RANGE, "1985"),
        (1985, FolderTemplate.DECADE, DecadeStyle.RANGE, "1980-1989"),
        (1985, FolderTemplate.DECADE, DecadeStyle.SHORT, "80s"),
        (1901, FolderTemplate.DECADE, DecadeStyle.SHORT, "00s"),
        (2005, FolderTemplate.DECADE, DecadeStyle.SHORT, "2000s"),
        (2019, FolderTemplate.DECADE, DecadeStyle.RANGE, "2010-2019"),
        (None, FolderTemplate.YEAR, DecadeStyle.RANGE, "_Onbekend"),
    ],
)
def test_folder_for_year(year, template, style, expected):
    assert folder_for_year(year, template, style) == expected


def test_is_misplaced():
    opts = PlanOptions(Path("/m"), FolderTemplate.YEAR)
    assert is_misplaced("1984", 1985, opts)
    assert not is_misplaced("1985", 1985, opts)
    assert is_misplaced("", None, opts)
    assert not is_misplaced("_onbekend", None, opts)
    assert not is_misplaced("wat dan ook", 1985, PlanOptions(Path("/m")))


def test_simple_rename_in_place(tmp_path):
    src = _touch(tmp_path / "sub" / "queen - innuendo.mp3")
    [plan] = plan_renames([_inp(0, src, "Queen", "Innuendo", 1991)], PlanOptions(tmp_path))
    assert plan.dst == tmp_path / "sub" / "Queen - Innuendo (1991).mp3"
    assert not plan.blocked
    assert plan.warnings == ()


def test_extension_is_kept(tmp_path):
    src = _touch(tmp_path / "a - b.FLAC")
    [plan] = plan_renames([_inp(0, src, "A", "C")], PlanOptions(tmp_path))
    assert plan.dst.name == "A - C.FLAC"


def test_unchanged_tracks_skipped_unless_requested(tmp_path):
    src = _touch(tmp_path / "Queen  -  Innuendo(1991).mp3")
    inp = _inp(0, src, "Queen", "Innuendo", 1991, changed=False)
    assert plan_renames([inp], PlanOptions(tmp_path)) == []
    [plan] = plan_renames([inp], PlanOptions(tmp_path, include_unchanged=True))
    assert plan.dst.name == "Queen - Innuendo (1991).mp3"
    assert not plan.changed


def test_no_plan_when_nothing_changes(tmp_path):
    src = _touch(tmp_path / "Queen - Innuendo (1991).mp3")
    inp = _inp(0, src, "Queen", "Innuendo", 1991, changed=False)
    assert plan_renames([inp], PlanOptions(tmp_path, include_unchanged=True)) == []


def test_move_to_year_and_unknown_folder(tmp_path):
    a = _touch(tmp_path / "x" / "A - B (1985).mp3")
    b = _touch(tmp_path / "x" / "C - D.mp3")
    opts = PlanOptions(tmp_path, FolderTemplate.DECADE, DecadeStyle.SHORT, include_unchanged=True)
    plans = plan_renames(
        [_inp(0, a, "A", "B", 1985, changed=False), _inp(1, b, "C", "D", changed=False)], opts
    )
    assert [p.dst for p in plans] == [
        tmp_path / "80s" / "A - B (1985).mp3",
        tmp_path / "_Onbekend" / "C - D.mp3",
    ]


def test_case_only_rename(tmp_path):
    src = _touch(tmp_path / "queen - innuendo.mp3")
    [plan] = plan_renames([_inp(0, src, "Queen", "Innuendo")], PlanOptions(tmp_path))
    assert plan.case_only
    assert PlanWarning.CASE_ONLY in plan.warnings
    assert not plan.blocked


@pytest.mark.parametrize(
    ("policy", "blocked", "name"),
    [
        (Collision.SKIP, True, "Queen - Innuendo.mp3"),
        (Collision.MARK_DUPLICATE, True, "Queen - Innuendo.mp3"),
        (Collision.SUFFIX, False, "Queen - Innuendo (2).mp3"),
    ],
)
def test_existing_target_is_never_overwritten(tmp_path, policy, blocked, name):
    _touch(tmp_path / "Queen - Innuendo.mp3")  # een ander bestand, niet in het plan
    src = _touch(tmp_path / "q - i.mp3")
    [plan] = plan_renames(
        [_inp(0, src, "Queen", "Innuendo")], PlanOptions(tmp_path, collision=policy)
    )
    assert PlanWarning.EXISTS in plan.warnings
    assert plan.blocked is blocked
    assert plan.collision is policy
    assert plan.dst.name == name


def test_suffix_skips_taken_numbers(tmp_path):
    _touch(tmp_path / "A - B.mp3")
    _touch(tmp_path / "A - B (2).mp3")
    src = _touch(tmp_path / "x.mp3")
    [plan] = plan_renames(
        [_inp(0, src, "A", "B")], PlanOptions(tmp_path, collision=Collision.SUFFIX)
    )
    assert plan.dst.name == "A - B (3).mp3"


def test_two_tracks_same_target(tmp_path):
    a = _touch(tmp_path / "1.mp3")
    b = _touch(tmp_path / "2.mp3")
    plans = plan_renames(
        [_inp(0, a, "A", "B"), _inp(1, b, "A", "B")],
        PlanOptions(tmp_path, collision=Collision.SUFFIX),
    )
    assert [p.dst.name for p in plans] == ["A - B.mp3", "A - B (2).mp3"]
    assert PlanWarning.DUPLICATE_TARGET in plans[1].warnings

    plans = plan_renames([_inp(0, a, "A", "B"), _inp(1, b, "a", "b")], PlanOptions(tmp_path))
    assert not plans[0].blocked
    assert plans[1].blocked  # hoofdletterongevoelig dezelfde naam


def test_swap_names_is_allowed(tmp_path):
    # A→B en B→A: geen botsing, want beide bestanden gaan weg (executor gebruikt tijdelijke namen)
    a = _touch(tmp_path / "A - B.mp3")
    b = _touch(tmp_path / "B - A.mp3")
    plans = plan_renames([_inp(0, a, "B", "A"), _inp(1, b, "A", "B")], PlanOptions(tmp_path))
    assert [p.blocked for p in plans] == [False, False]
    assert [p.warnings for p in plans] == [(), ()]


def test_target_of_blocked_file_counts_as_occupied(tmp_path):
    # Track 0 wil naar X maar X bestaat (overslaan) -> track 0 blijft staan.
    # Track 1 wil naar de naam van track 0 -> moet nu ook botsen.
    _touch(tmp_path / "X - X.mp3")
    a = _touch(tmp_path / "A - A.mp3")
    b = _touch(tmp_path / "b.mp3")
    plans = plan_renames([_inp(0, a, "X", "X"), _inp(1, b, "A", "A")], PlanOptions(tmp_path))
    assert [p.blocked for p in plans] == [True, True]
    assert PlanWarning.EXISTS in plans[1].warnings


def test_invalid_names_are_blocked(tmp_path):
    src = _touch(tmp_path / "x.mp3")
    plans = plan_renames(
        [
            _inp(0, src, "AC/DC", "Thunder"),
            _inp(1, src, "", "Titel"),
            _inp(2, src, "A", "What?"),
        ],
        PlanOptions(tmp_path),
    )
    assert all(p.blocked for p in plans)
    assert all(PlanWarning.INVALID_NAME in p.warnings for p in plans)
    assert "artiest ontbreekt" in plans[1].note


def test_invalid_unknown_folder_is_blocked(tmp_path):
    src = _touch(tmp_path / "x.mp3")
    opts = PlanOptions(tmp_path, FolderTemplate.YEAR, unknown_folder="Geen:jaar")
    [plan] = plan_renames([_inp(0, src, "A", "B")], opts)
    assert plan.blocked


def test_long_path_warning(tmp_path):
    src = _touch(tmp_path / "x.mp3")
    title = "T" * (MAX_PATH - len(str(tmp_path)))
    [plan] = plan_renames([_inp(0, src, "A", title)], PlanOptions(tmp_path))
    assert PlanWarning.PATH_TOO_LONG in plan.warnings
    assert not plan.blocked  # waarschuwing, geen blokkade


def test_tags_only_plan(tmp_path):
    src = _touch(tmp_path / "A - B (1990).mp3")
    inp = _inp(0, src, "A", "B", 1990, changed=False, tag_mismatch=True)
    assert plan_renames([inp], PlanOptions(tmp_path, include_unchanged=True)) == []
    [plan] = plan_renames([inp], PlanOptions(tmp_path, include_unchanged=True, write_tags=True))
    assert plan.dst == plan.src
    assert not plan.renames
    assert PlanWarning.TAGS_ONLY in plan.warnings
    assert plan.tags is not None and plan.tags.date == "1990"
