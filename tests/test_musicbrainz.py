"""MusicBrainz-client zonder netwerk (httpx.MockTransport)."""

import json
from datetime import datetime, timedelta

import httpx
import pytest

from mp3sanitizer.core.musicbrainz import (
    ArtistCandidate,
    MusicBrainzCache,
    MusicBrainzClient,
    MusicBrainzError,
    RateLimiter,
    RecordingCandidate,
    lucene_escape,
    recording_key,
    user_agent,
)

API_RESPONSE = {
    "artists": [
        {
            "id": "b10bbbfc",
            "name": "The Beatles",
            "sort-name": "Beatles, The",
            "country": "GB",
            "score": 100,
            "type": "Group",
        },
        {
            "id": "x1",
            "name": "Beatles Revival Band",
            "sort-name": "Beatles Revival Band",
            "disambiguation": "tribute",
            "score": 81,
        },
        {"id": "x2", "name": "The Beetles", "sort-name": "Beetles, The", "score": 60},
    ]
}


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


@pytest.fixture
def requests_log():
    return []


def _client(requests_log, responses=None, cache=None, clock=None):
    responses = list(responses or [httpx.Response(200, json=API_RESPONSE)])

    def handler(request: httpx.Request) -> httpx.Response:
        requests_log.append(request)
        return responses.pop(0) if len(responses) > 1 else responses[0]

    clock = clock or FakeClock()
    return MusicBrainzClient(
        "1.2.3",
        cache=cache,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        limiter=RateLimiter(1.0, clock.clock, clock.sleep),
        sleep=clock.sleep,
    )


def test_user_agent_contains_version_and_contact():
    assert user_agent("0.6.0", "mail@example.org") == "Mp3Sanitizer/0.6.0 ( mail@example.org )"


def test_search_filters_on_score_and_sends_user_agent(requests_log):
    client = _client(requests_log)
    result = client.search_artist("beatles")
    assert [c.name for c in result] == ["The Beatles", "Beatles Revival Band"]
    assert result[0].sort_name == "Beatles, The"
    assert result[0].country == "GB"
    assert result[1].disambiguation == "tribute"
    [req] = requests_log
    assert req.headers["User-Agent"].startswith("Mp3Sanitizer/1.2.3 ( ")
    assert req.url.params["fmt"] == "json"
    assert req.url.params["query"] == "beatles"


def test_rate_limit_one_request_per_second(requests_log):
    clock = FakeClock()
    client = _client(requests_log, clock=clock)
    client.search_artist("a")
    clock.now += 0.3
    client.search_artist("b")
    client.search_artist("c")
    assert clock.sleeps == [0.7, 1.0]
    assert len(requests_log) == 3


def test_cache_prevents_second_request(tmp_path, requests_log):
    cache = MusicBrainzCache(tmp_path / "mb.json")
    client = _client(requests_log, cache=cache)
    client.search_artist("The Beatles")
    client.search_artist("  the   BEATLES ")
    assert len(requests_log) == 1
    data = json.loads((tmp_path / "mb.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    # een nieuwe sessie leest de cache van schijf
    client2 = _client(requests_log, cache=MusicBrainzCache(tmp_path / "mb.json"))
    assert client2.search_artist("the beatles")[0].name == "The Beatles"
    assert len(requests_log) == 1


def test_cache_expires(tmp_path):
    now = datetime(2026, 1, 1)
    cache = MusicBrainzCache(tmp_path / "mb.json", now=lambda: now)
    cache.put("x", [ArtistCandidate("1", "X", "X", "", "", 100)])
    assert cache.get("x") is not None
    later = MusicBrainzCache(tmp_path / "mb.json", now=lambda: now + timedelta(days=31))
    later._entries = cache._entries
    assert later.get("x") is None


def test_corrupt_cache_is_ignored(tmp_path, requests_log):
    (tmp_path / "mb.json").write_text("{kapot", encoding="utf-8")
    cache = MusicBrainzCache(tmp_path / "mb.json")
    client = _client(requests_log, cache=cache)
    assert client.search_artist("beatles")
    assert (tmp_path / "mb.json.corrupt").exists()


def test_retry_once_on_503(requests_log):
    client = _client(requests_log, [httpx.Response(503), httpx.Response(200, json=API_RESPONSE)])
    assert client.search_artist("beatles")
    assert len(requests_log) == 2


def test_errors_are_reported(requests_log):
    with pytest.raises(MusicBrainzError, match="500"):
        _client(requests_log, [httpx.Response(500)]).search_artist("x")
    with pytest.raises(MusicBrainzError, match="overbelast"):
        _client(requests_log, [httpx.Response(503)]).search_artist("x")

    def boom(request):
        raise httpx.ConnectError("geen netwerk")

    client = MusicBrainzClient(
        "1",
        http=httpx.Client(transport=httpx.MockTransport(boom)),
        limiter=RateLimiter(0),
        sleep=lambda s: None,
    )
    with pytest.raises(MusicBrainzError, match="Geen verbinding"):
        client.search_artist("x")


def test_empty_query_makes_no_request(requests_log):
    assert _client(requests_log).search_artist("   ") == []
    assert requests_log == []


def test_lucene_escape():
    assert lucene_escape('AC/DC: "Live"!') == 'AC\\/DC\\: \\"Live\\"\\!'


# --- opnamen (artiest + titel) ---------------------------------------------------------------

RECORDING_RESPONSE = {
    "recordings": [
        {
            "id": "r1",
            "title": "Under Pressure",
            "score": 100,
            "length": 248000,
            "first-release-date": "1981-10-26",
            "artist-credit": [
                {"name": "Queen", "joinphrase": " & ", "artist": {"name": "Queen"}},
                {"name": "David Bowie", "artist": {"name": "David Bowie"}},
            ],
            "releases": [{"title": "Under Pressure"}],
        },
        {"id": "r2", "title": "Under Pressure (live)", "score": 90, "disambiguation": "live"},
        {"id": "r3", "title": "Pressure", "score": 50},
    ]
}


def test_search_recording_parses_credit_year_and_query(requests_log):
    client = _client(requests_log, [httpx.Response(200, json=RECORDING_RESPONSE)])
    result = client.search_recording("queen", "under pressure")
    assert [r.mbid for r in result] == ["r1", "r2"]  # score < 80 valt af
    first = result[0]
    assert (first.title, first.artist, first.year) == (
        "Under Pressure",
        "Queen & David Bowie",
        1981,
    )
    assert (first.release, first.length_s) == ("Under Pressure", 248)
    assert result[1].year is None and result[1].artist == ""
    request = requests_log[0]
    assert request.url.path == "/ws/2/recording/"
    assert request.url.params["query"] == 'recording:"under pressure" AND artist:"queen"'


def test_search_recording_without_title_makes_no_request(requests_log):
    assert _client(requests_log).search_recording("Queen", "  ") == []
    assert requests_log == []


def test_recording_cache_is_separate_from_artists(tmp_path, requests_log):
    cache = MusicBrainzCache(tmp_path / "mb.json")
    client = _client(
        requests_log,
        [httpx.Response(200, json=RECORDING_RESPONSE), httpx.Response(200, json=API_RESPONSE)],
        cache=cache,
    )
    client.search_recording("Queen", "Under Pressure")
    client.search_recording("QUEEN", "under  pressure")  # uit de cache
    assert len(requests_log) == 1
    assert client.search_artist("Queen")[0].name == "The Beatles"  # eigen sleutel
    assert len(requests_log) == 2
    reloaded = MusicBrainzCache(tmp_path / "mb.json")
    assert (
        reloaded.get(recording_key("queen", "under pressure"), RecordingCandidate)[0].mbid == "r1"
    )
