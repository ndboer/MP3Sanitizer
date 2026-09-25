"""MusicBrainz WS/2 artist search met rate limiting (1 request/s) en een lokale cache.

MusicBrainz vereist een herkenbare User-Agent met contactgegevens; zie
https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from mp3sanitizer.core.normalize import fold
from mp3sanitizer.core.storage import LoadStatus, load_document, save_document

log = logging.getLogger(__name__)

API_URL = "https://musicbrainz.org/ws/2/artist/"
DEFAULT_CONTACT = "https://github.com/ndboer/MP3Sanitizer"
MIN_SCORE = 80
CACHE_SCHEMA_VERSION = 1
CACHE_TTL = timedelta(days=30)
REQUEST_TIMEOUT_S = 15.0
RETRIES_503 = 2  # extra pogingen als MusicBrainz 'overbelast' (503) antwoordt

_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')


class MusicBrainzError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ArtistCandidate:
    mbid: str
    name: str  # officiële naam: deze wordt ingevuld (niet de sort-name)
    sort_name: str
    country: str
    disambiguation: str
    score: int
    type: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ArtistCandidate:
        return cls(
            mbid=str(data.get("id", "")),
            name=str(data.get("name", "")),
            sort_name=str(data.get("sort-name", "")),
            country=str(data.get("country") or data.get("area", {}).get("name") or ""),
            disambiguation=str(data.get("disambiguation", "")),
            score=int(data.get("score", 0)),
            type=str(data.get("type") or ""),
        )


def user_agent(app_version: str, contact: str = DEFAULT_CONTACT) -> str:
    return f"Mp3Sanitizer/{app_version} ( {contact} )"


def lucene_escape(text: str) -> str:
    return _LUCENE_SPECIAL.sub(r"\\\1", text)


def cache_key(name: str) -> str:
    return fold(name)


class RateLimiter:
    """Maximaal één aanroep per ``interval`` seconden, ook over threads heen."""

    def __init__(
        self,
        interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last is not None:
                delay = self._last + self.interval - now
                if delay > 0:
                    self._sleep(delay)
                    now = self._clock()
            self._last = now


class MusicBrainzCache:
    """JSON-cache met ``schema_version``; bij een corrupt bestand wordt opnieuw begonnen."""

    def __init__(self, path: Path, now: Callable[[], datetime] = datetime.now) -> None:
        self.path = path
        self._now = now
        self._entries: dict[str, dict[str, Any]] = {}
        self._writable = True
        result = load_document(path, CACHE_SCHEMA_VERSION)
        if result.status is LoadStatus.NEWER:
            self._writable = False
        elif result.status in (LoadStatus.OK, LoadStatus.MIGRATED):
            entries = result.data.get("entries", {})
            if isinstance(entries, dict):
                self._entries = entries

    def get(self, name: str) -> list[ArtistCandidate] | None:
        entry = self._entries.get(cache_key(name))
        if not entry:
            return None
        try:
            fetched = datetime.fromisoformat(entry["fetched"])
            if self._now() - fetched > CACHE_TTL:
                return None
            return [ArtistCandidate(**c) for c in entry["results"]]
        except (KeyError, TypeError, ValueError):
            return None

    def put(self, name: str, candidates: list[ArtistCandidate]) -> None:
        self._entries[cache_key(name)] = {
            "fetched": self._now().isoformat(timespec="seconds"),
            "results": [asdict(c) for c in candidates],
        }

    def save(self) -> None:
        if self._writable:
            save_document(self.path, {"entries": self._entries}, CACHE_SCHEMA_VERSION)


class MusicBrainzClient:
    def __init__(
        self,
        app_version: str,
        contact: str = DEFAULT_CONTACT,
        cache: MusicBrainzCache | None = None,
        http: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.user_agent = user_agent(app_version, contact)
        self._sleep = sleep
        self.cache = cache
        self._http = http or httpx.Client(timeout=REQUEST_TIMEOUT_S)
        self._limiter = limiter or RateLimiter()

    def search_artist(
        self, name: str, *, min_score: int = MIN_SCORE, use_cache: bool = True
    ) -> list[ArtistCandidate]:
        """Kandidaten voor ``name`` met score >= ``min_score``, beste eerst."""
        name = " ".join(name.split())
        if not name:
            return []
        candidates = self.cache.get(name) if (self.cache and use_cache) else None
        if candidates is None:
            candidates = self._fetch(name)
            if self.cache is not None:
                self.cache.put(name, candidates)
                self.cache.save()
        result = [c for c in candidates if c.score >= min_score]
        result.sort(key=lambda c: -c.score)
        return result

    def _fetch(self, name: str) -> list[ArtistCandidate]:
        params = {"query": lucene_escape(name), "fmt": "json", "limit": "15"}
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        for attempt in range(RETRIES_503 + 1):
            if attempt:
                self._sleep(attempt)  # 1 s, 2 s, ... extra bovenop de rate limit
            self._limiter.wait()
            try:
                response = self._http.get(API_URL, params=params, headers=headers)
            except httpx.HTTPError as exc:
                raise MusicBrainzError(f"Geen verbinding met MusicBrainz: {exc}") from exc
            if response.status_code == 503:  # MusicBrainz is (globaal) druk; even wachten
                log.info("MusicBrainz 503, poging %d", attempt + 1)
                continue
            if response.status_code != 200:
                raise MusicBrainzError(f"MusicBrainz antwoordde met {response.status_code}")
            try:
                artists = response.json().get("artists", [])
                return [ArtistCandidate.from_api(a) for a in artists]
            except (ValueError, TypeError, AttributeError) as exc:
                raise MusicBrainzError(f"Onverwacht antwoord van MusicBrainz: {exc}") from exc
        raise MusicBrainzError("MusicBrainz is tijdelijk overbelast; probeer het later opnieuw")
