import random
import time

import pytest

from mp3sanitizer.core.fuzzy import (
    artist_counts,
    cluster_artists,
    combined_score,
    search_artists,
)
from mp3sanitizer.core.normalize import match_key

COUNTS = {
    "Beatles": 12,
    "The Beatles": 40,
    "Beatles, The": 3,
    "The Beatels": 1,
    "Beatles Tribute Band": 2,
    "Beyoncé": 5,
    "Beyonce": 2,
    "Queen": 20,
    "Simon & Garfunkel": 4,
    "Simon and Garfunkel": 1,
    "Prince": 6,
}


def _spellings(matches):
    return [m.spelling for m in matches]


def test_artist_counts_skips_empty():
    assert artist_counts(["A", "A", "", " ", "B"]) == {"A": 2, "B": 1}


def test_search_groups_spellings_with_counts():
    result = search_artists("beatles", COUNTS)
    assert _spellings(result)[:3] == ["The Beatles", "Beatles", "Beatles, The"]
    assert {m.spelling: m.count for m in result}["Beatles, The"] == 3
    assert "The Beatels" in _spellings(result)  # tikfout
    assert "Queen" not in _spellings(result)


def test_search_partial_query():
    assert "The Beatles" in _spellings(search_artists("beat", COUNTS))
    assert search_artists("be", COUNTS) == []  # te kort voor een deelmatch


def test_search_diacritics_and_and():
    assert set(_spellings(search_artists("beyonce", COUNTS))) >= {"Beyoncé", "Beyonce"}
    assert set(_spellings(search_artists("simon + garfunkel", COUNTS))) >= {
        "Simon & Garfunkel",
        "Simon and Garfunkel",
    }


def test_threshold():
    loose = search_artists("prinse", COUNTS, threshold=60)
    strict = search_artists("prinse", COUNTS, threshold=95)
    assert "Prince" in _spellings(loose)
    assert "Prince" not in _spellings(strict)


def test_empty_query():
    assert search_artists("  ", COUNTS) == []
    assert isinstance(search_artists("The", COUNTS), list)  # alleen een lidwoord: geen crash


def test_tribute_band_is_not_the_same_artist():
    assert combined_score(match_key("Beatles"), match_key("Beatles Tribute Band")) < 85
    assert combined_score(match_key("Beatles"), match_key("Beatels")) >= 85


def test_clusters_with_suggestion():
    clusters = cluster_artists(COUNTS)
    by_suggestion = {c.suggestion: c for c in clusters}
    beatles = by_suggestion["The Beatles"]
    assert {s for s, _ in beatles.members} == {
        "Beatles",
        "The Beatles",
        "Beatles, The",
        "The Beatels",
    }
    assert beatles.total == 56
    assert beatles.members[0] == ("The Beatles", 40)
    assert {s for s, _ in by_suggestion["Beyoncé"].members} == {"Beyoncé", "Beyonce"}
    assert "Simon & Garfunkel" in by_suggestion
    assert all(len(c.members) > 1 for c in clusters)  # Queen en Prince staan er niet in
    assert clusters[0].suggestion == "The Beatles"  # grootste cluster eerst


@pytest.mark.parametrize("articles", [("The",), ()])
def test_clusters_respect_article_list(articles):
    clusters = cluster_artists({"The Cure": 3, "Cure": 1}, articles=articles)
    assert bool(clusters) is bool(articles)


def test_cluster_cancel():
    assert cluster_artists(COUNTS, cancelled=lambda: True) == []


def test_cluster_performance_2000_artists():
    # Realistisch gevarieerde namen (lettergrepen); ~0,3 s op een gewone laptop.
    rnd = random.Random(7)
    syllables = ["ka", "lo", "mi", "ra", "ste", "van", "der", "bo", "ne", "tri", "ox", "ul",
                 "zu", "pe", "gor", "lin", "sa", "ve", "ing", "ton", "ber", "mo", "ry"]  # fmt: skip
    counts: dict[str, int] = {}
    while len(counts) < 2000:
        words = [
            "".join(rnd.choice(syllables) for _ in range(rnd.randint(1, 3))).capitalize()
            for _ in range(rnd.randint(1, 3))
        ]
        counts[" ".join(words)] = 1
    t = time.perf_counter()
    cluster_artists(counts)
    assert time.perf_counter() - t < 5
