import time
from pathlib import Path

import pytest

from mp3sanitizer.core.duplicates import (
    DupItem,
    DupOptions,
    best_item,
    find_duplicates,
    strip_versions,
)


def item(tid, artist, title, year=None, *, dur=None, br=None, path=None, size=None):
    return DupItem(tid, artist, title, year, Path(path or f"/m/{tid}.mp3"), dur, br, size)


def ids(groups):
    return [sorted(i.track_id for i in g) for g in groups]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Help! (Remastered 2009)", "Help!"),
        ("Help! [Live]", "Help!"),
        ("Help! - Radio Edit", "Help!"),
        ("Blue Monday (Extended Mix)", "Blue Monday"),
        ("One (Remix) (Live)", "One"),
        ("Live and Let Die", "Live and Let Die"),  # 'Live' als deel van de titel blijft
        ("(Live)", "(Live)"),
        ("Help! (feat. X)", "Help! (feat. X)"),
    ],
)
def test_strip_versions(title, expected):
    assert strip_versions(title) == expected


def test_strict_after_normalization():
    groups = find_duplicates(
        [
            item(0, "The Beatles", "Help!", 1965),
            item(1, "Beatles, The", "help", 1965),
            item(2, "BEATLES", "Help!", 2009),
            item(3, "The Beatles", "Yesterday"),
            item(4, "Beatles Tribute", "Help!"),
        ]
    )
    assert ids(groups) == [[0, 1, 2]]


def test_year_criterion():
    items = [item(0, "A", "B", 1990), item(1, "A", "B", 1990), item(2, "A", "B", 2000)]
    assert ids(find_duplicates(items, DupOptions(ignore_year=True))) == [[0, 1, 2]]
    assert ids(find_duplicates(items, DupOptions(ignore_year=False))) == [[0, 1]]


def test_version_markers():
    items = [item(0, "A", "Song"), item(1, "A", "Song (Live)"), item(2, "A", "Song (Remix)")]
    assert find_duplicates(items, DupOptions(ignore_versions=False)) == []
    assert ids(find_duplicates(items, DupOptions(ignore_versions=True))) == [[0, 1, 2]]


def test_duration_tolerance():
    items = [
        item(0, "A", "B", dur=200.0),
        item(1, "A", "B", dur=201.5),
        item(2, "A", "B", dur=260.0),
        item(3, "A", "B", dur=None),
        item(4, "A", "B", dur=259.0),
    ]
    assert ids(find_duplicates(items)) == [[0, 1, 2, 3, 4]]
    groups = ids(find_duplicates(items, DupOptions(use_duration=True)))
    assert sorted(groups) == [[0, 1, 3], [2, 4]]  # onbekende duur bij de grootste groep


def test_fuzzy_catches_typos():
    items = [
        item(0, "The Beatles", "Yesterday"),
        item(1, "Beatels", "Yesterdy"),
        item(2, "Queen", "Innuendo"),
        item(3, "Queen", "Inuendo"),
        item(4, "Queen", "I Want It All"),
    ]
    assert find_duplicates(items) == []
    groups = ids(find_duplicates(items, DupOptions(fuzzy=True, threshold=85)))
    assert sorted(groups) == [[0, 1], [2, 3]]


def test_best_item_rule():
    a = item(0, "A", "B", br=192, dur=200, path="/m/kort.mp3")
    b = item(1, "A", "B", br=320, dur=180, path="/m/heel/lang/pad.mp3")
    c = item(2, "A", "B", br=320, dur=200, path="/m/heel/lang/pad2.mp3")
    d = item(3, "A", "B", br=320, dur=200, path="/m/p.mp3")
    assert best_item([a, b]) is b  # bitrate eerst
    assert best_item([b, c]) is c  # dan duur
    assert best_item([c, d]) is d  # dan kortste pad
    [group] = find_duplicates([a, b, c, d])
    assert group[0] is d  # beste vooraan


def test_empty_fields_ignored():
    assert find_duplicates([item(0, "", "X"), item(1, "", "X")]) == []


def test_cancel():
    items = [item(0, "A", "B"), item(1, "A", "B")]
    assert find_duplicates(items, cancelled=lambda: True) == []


def test_performance_10k_strict():
    items = [item(i, f"Artiest {i % 1500}", f"Titel {i % 7}") for i in range(10_000)]
    t = time.perf_counter()
    find_duplicates(items)
    assert time.perf_counter() - t < 2


def test_copy_number_files_are_duplicates(tmp_path):
    from mp3sanitizer.core.scanner import track_from_path

    names = ["Queen - Innuendo (1991).mp3", "Queen - Innuendo (1991)(2).mp3"]
    tracks = [track_from_path(i, tmp_path / n, tmp_path) for i, n in enumerate(names)]
    items = [DupItem(t.id, t.artist, t.title, t.year, t.path) for t in tracks]
    assert ids(find_duplicates(items, DupOptions(ignore_year=False))) == [[0, 1]]
