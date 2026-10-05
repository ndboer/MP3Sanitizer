"""Artiestencontrole in batch (zonder netwerk)."""

from mp3sanitizer.core.artist_review import (
    OTHER_LETTER,
    Evidence,
    Status,
    TrackRef,
    best_recording,
    collect,
    letter_counts,
    letter_of,
    run_review,
    summarize,
)
from mp3sanitizer.core.musicbrainz import MusicBrainzError, RecordingCandidate
from mp3sanitizer.core.settings import Settings


def rec(title, credits, year=None, mbid="r", score=100):
    artist = " & ".join(name for _, name in credits)
    return RecordingCandidate(mbid, title, artist, year, "", "", score, None, tuple(credits))


class FakeMB:
    def __init__(self, table, error=None):
        self.table = table  # (artiestveld, titel) -> opnamen
        self.calls = []
        self.error = error

    def search_recording(self, artist, title):
        self.calls.append((artist, title))
        if self.error:
            raise self.error
        return self.table.get((artist, title), [])


QUEEN = ("q1", "Queen")
BOWIE = ("b1", "David Bowie")
NIRVANA_60 = ("n68", "Nirvana")
NIRVANA_90 = ("n91", "Nirvana")


def test_letter_of_follows_sort_key():
    assert letter_of("The Beatles") == "B"
    assert letter_of("Beatles, The") == "B"
    assert letter_of("Éric Serra") == "E"
    assert letter_of("2Pac") == OTHER_LETTER
    assert letter_of("'NSYNC") == "N"


def test_collect_splits_collaborations_and_filters_letters():
    tracks = [
        TrackRef(1, "Queen & David Bowie", "Under Pressure", 1981),
        TrackRef(2, "Queen", "Innuendo", 1991),
        TrackRef(3, "The Beatles", "Help!", 1965),
    ]
    entries = collect(tracks)
    assert [e.name for e in entries] == ["The Beatles", "David Bowie", "Queen"]
    assert [t.track_id for t in entries[2].tracks] == [1, 2]
    assert [e.name for e in collect(tracks, letters=["d"])] == ["David Bowie"]
    assert [e.name for e in collect(tracks, skip={"queen"})] == ["The Beatles", "David Bowie"]
    counts = letter_counts(tracks)
    assert counts["Q"] == (1, 2) and counts["B"] == (1, 1) and counts["Z"] == (0, 0)


def test_best_recording_prefers_title_and_year():
    old = rec("Love Is Blind", [NIRVANA_60], 1969, "old")
    new = rec("Love Is Blind", [NIRVANA_90], 1992, "new")
    other = rec("Something Else", [NIRVANA_90], 1969, "x")
    assert best_recording("Love is blind", 1969, [new, old, other]).mbid == "old"
    assert best_recording("Love is blind", 1992, [old, new]).mbid == "new"
    assert best_recording("Totally different", 1969, [old, new]) is None


def test_summarize_statuses():
    from mp3sanitizer.core.artist_review import ArtistEntry

    entry = ArtistEntry("Beatles", [TrackRef(i, "Beatles", f"t{i}", 1965) for i in range(3)])
    beatles = {i: Evidence(i, "b", "The Beatles") for i in range(3)}
    p = summarize(entry, beatles)
    assert (p.status, p.proposal) == (Status.PROPOSAL, "The Beatles")
    assert summarize(entry, {i: Evidence(i) for i in range(3)}).status is Status.NOT_FOUND
    mixed = {0: Evidence(0, "b", "The Beatles"), 1: Evidence(1, "x", "Beatles Revival")}
    assert summarize(entry, mixed).status is Status.DOUBT
    ok = ArtistEntry("The Beatles", entry.tracks)
    assert summarize(ok, beatles).status is Status.OK


def test_same_name_different_artists_get_per_track_proposal():
    tracks = [
        TrackRef(1, "nirvana", "Rainbow Chaser", 1968),
        TrackRef(2, "nirvana", "Smells Like Teen Spirit", 1991),
        TrackRef(3, "nirvana", "Come As You Are", 1992),
    ]
    mb = FakeMB(
        {
            ("nirvana", "Rainbow Chaser"): [rec("Rainbow Chaser", [NIRVANA_60], 1968)],
            ("nirvana", "Smells Like Teen Spirit"): [
                rec("Smells Like Teen Spirit", [NIRVANA_90], 1991)
            ],
            ("nirvana", "Come As You Are"): [rec("Come as You Are", [NIRVANA_90], 1992)],
        }
    )
    results = []
    run_review(mb, collect(tracks), on_result=results.append)
    (p,) = results
    assert p.status is Status.SPLIT
    assert [(c.mbid, c.track_ids) for c in p.candidates] == [("n91", [2, 3]), ("n68", [1])]
    assert p.track_proposal(1) == "Nirvana"


def test_collaboration_each_artist_gets_its_credit_and_track_is_looked_up_once():
    tracks = [TrackRef(1, "queen & david bowie", "Under Pressure", 1981)]
    mb = FakeMB(
        {("queen & david bowie", "Under Pressure"): [rec("Under Pressure", [QUEEN, BOWIE], 1981)]}
    )
    results, progress = [], []
    run_review(
        mb,
        collect(tracks),
        on_result=results.append,
        progress=lambda d, t: progress.append((d, t)),
    )
    assert {r.entry.name: r.proposal for r in results} == {
        "david bowie": "David Bowie",
        "queen": "Queen",
    }
    assert len(mb.calls) == 1
    assert progress == [(1, 1)]


def test_cancel_and_connection_errors():
    tracks = [TrackRef(i, "A", f"t{i}", None) for i in range(10)]
    results = []
    assert (
        run_review(FakeMB({}), collect(tracks), on_result=results.append, cancelled=lambda: True)
        is None
    )
    assert results == []
    error = run_review(
        FakeMB({}, error=MusicBrainzError("Geen verbinding")),
        collect(tracks),
        on_result=results.append,
    )
    assert error == "Geen verbinding"


def test_recording_credits_from_api_use_official_name():
    data = {
        "id": "r",
        "title": "Under Pressure",
        "score": 100,
        "artist-credit": [
            {"name": "Queen", "joinphrase": " & ", "artist": {"id": "q1", "name": "Queen"}},
            {"name": "Bowie", "artist": {"id": "b1", "name": "David Bowie"}},
        ],
    }
    c = RecordingCandidate.from_api(data)
    assert c.artist == "Queen & Bowie"  # zoals vermeld
    assert c.credits == (("q1", "Queen"), ("b1", "David Bowie"))  # officiële namen


def test_settings_keep_review_decisions():
    s = Settings.from_dict({"artist_review": {"queen": "approved", "x": 3}})
    assert s.artist_review == {}  # ongeldig type valt terug
    s = Settings.from_dict({"artist_review": {"queen": "approved"}})
    assert s.artist_review == {"queen": "approved"}
