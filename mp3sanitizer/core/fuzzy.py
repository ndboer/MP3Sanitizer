"""Fuzzy zoeken en clusteren van artiesten (rapidfuzz) op een genormaliseerde sleutel.

De sleutel (``normalize.match_key``) negeert hoofdletters, diacrieten, lidwoorden (ook in de
vorm "Naam, The"), leestekens en maakt "&", "and", "en" en "+" gelijk.

Score (0-100): het gemiddelde van ``token_set_ratio`` en ``ratio``. ``token_set_ratio`` alleen
geeft 100 voor "Beatles" ↔ "Beatles Tribute Band"; het gemiddelde met ``ratio`` voorkomt dat,
terwijl tikfouten ("Beatels") boven de standaarddrempel van 85 blijven. Bij zoeken telt ook
``partial_ratio`` mee, zodat een deel van de naam ("beat") al resultaat geeft.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from mp3sanitizer.core.normalize import DEFAULT_ARTICLES, match_key

DEFAULT_THRESHOLD = 85
MIN_PARTIAL_QUERY = 3  # kortere zoektermen matchen niet op een deel van de naam


def combined_score(a_key: str, b_key: str) -> float:
    if a_key == b_key:
        return 100.0
    return (fuzz.token_set_ratio(a_key, b_key) + fuzz.ratio(a_key, b_key)) / 2


def artist_counts(artists: Iterable[str]) -> Counter[str]:
    """Aantal tracks per schrijfwijze (lege artiesten tellen niet mee)."""
    return Counter(a for a in artists if a.strip())


@dataclass(frozen=True, slots=True)
class ArtistMatch:
    spelling: str
    count: int
    score: float


def search_artists(
    query: str,
    counts: Mapping[str, int],
    threshold: float = DEFAULT_THRESHOLD,
    articles: Iterable[str] = DEFAULT_ARTICLES,
) -> list[ArtistMatch]:
    """Alle schrijfwijzen die op ``query`` lijken, beste eerst (dan meeste tracks)."""
    articles = tuple(articles)
    qk = match_key(query, articles)
    if not qk:
        return []
    partial = len(qk) >= MIN_PARTIAL_QUERY
    matches = []
    for spelling, count in counts.items():
        key = match_key(spelling, articles)
        if not key:
            continue
        score = combined_score(qk, key)
        if partial and score < threshold:
            score = max(score, fuzz.partial_ratio(qk, key))
        if score >= threshold:
            matches.append(ArtistMatch(spelling, count, round(score, 1)))
    matches.sort(key=lambda m: (-m.score, -m.count, m.spelling.casefold()))
    return matches


@dataclass(slots=True)
class Cluster:
    """Schrijfwijzen die waarschijnlijk dezelfde artiest zijn."""

    members: list[tuple[str, int]] = field(default_factory=list)  # (schrijfwijze, aantal)

    @property
    def total(self) -> int:
        return sum(n for _, n in self.members)

    @property
    def suggestion(self) -> str:
        """De meest gebruikte schrijfwijze (bij gelijke stand alfabetisch)."""
        return min(self.members, key=lambda m: (-m[1], m[0].casefold()))[0]


def cluster_artists(
    counts: Mapping[str, int],
    threshold: float = DEFAULT_THRESHOLD,
    articles: Iterable[str] = DEFAULT_ARTICLES,
    cancelled: Callable[[], bool] | None = None,
) -> list[Cluster]:
    """Groepeer schrijfwijzen met dezelfde of een sterk gelijkende sleutel."""
    articles = tuple(articles)
    by_key: dict[str, list[str]] = {}
    for spelling in counts:
        key = match_key(spelling, articles)
        if key:
            by_key.setdefault(key, []).append(spelling)
    keys = list(by_key)

    parent = list(range(len(keys)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # Voorselectie met de snelle, native ``ratio``; alleen kandidaten krijgen de volledige score.
    # (token_set_ratio >= ratio, dus combined >= drempel vereist ratio >= 2*drempel - 100.)
    cutoff = max(0.0, 2 * threshold - 100)
    for i, key in enumerate(keys):
        if cancelled is not None and cancelled():
            return []
        for _, _, j in process.extract(
            key, keys, scorer=fuzz.ratio, score_cutoff=cutoff, limit=None
        ):
            if j > i and combined_score(key, keys[j]) >= threshold:
                parent[find(j)] = find(i)

    groups: dict[int, Cluster] = {}
    for i, key in enumerate(keys):
        cluster = groups.setdefault(find(i), Cluster())
        cluster.members.extend((s, counts[s]) for s in by_key[key])
    clusters = [c for c in groups.values() if len(c.members) > 1]
    for c in clusters:
        c.members.sort(key=lambda m: (-m[1], m[0].casefold()))
    clusters.sort(key=lambda c: (-c.total, c.suggestion.casefold()))
    return clusters
