"""Duplicaatdetectie op genormaliseerde artiest + titel, en 'beste automatisch behouden'.

Opties:

- strikt (exact na normalisatie) of fuzzy (met drempel);
- jaar negeren ja/nee;
- versie-aanduidingen negeren ja/nee: (Remix), (Live), (Radio Edit), (Extended Mix),
  (Remastered) — ook tussen [ ] of na " - ";
- optioneel duur ±2 s als extra criterium (onbekende duur telt als 'past').

Fuzzy werkt in twee stappen, zodat het ook bij 10.000+ tracks snel blijft: eerst artiesten
fuzzy clusteren (weinig unieke namen), daarna titels alleen binnen zo'n cluster vergelijken.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from mp3sanitizer.core.fuzzy import cluster_artists, combined_score
from mp3sanitizer.core.normalize import DEFAULT_ARTICLES, fold, match_key

VERSION_MARKERS: tuple[str, ...] = (
    "remix",
    "live",
    "radio edit",
    "extended mix",
    "remastered",
    "remaster",
)
DEFAULT_DURATION_TOLERANCE_S = 2.0


def _marker_pattern(markers: Sequence[str]) -> re.Pattern[str]:
    words = "|".join(re.escape(m) for m in sorted(markers, key=len, reverse=True))
    # "(... Remastered 2009 ...)", "[Live]" of " - Radio Edit" aan het eind
    return re.compile(
        rf"\s*[(\[][^)\]]*\b(?:{words})\b[^)\]]*[)\]]|\s+-\s+[^-]*\b(?:{words})\b[^-]*$",
        re.IGNORECASE,
    )


_DEFAULT_PATTERN = _marker_pattern(VERSION_MARKERS)


def strip_versions(title: str, pattern: re.Pattern[str] = _DEFAULT_PATTERN) -> str:
    stripped = pattern.sub("", title).strip()
    return stripped or title  # een titel die alleen uit '(Live)' bestaat blijft staan


@dataclass(frozen=True, slots=True)
class DupItem:
    track_id: int
    artist: str
    title: str
    year: int | None
    path: Path
    duration_s: float | None = None
    bitrate_kbps: int | None = None
    size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class DupOptions:
    fuzzy: bool = False
    threshold: int = 90
    ignore_year: bool = True
    ignore_versions: bool = False
    use_duration: bool = False
    duration_tolerance_s: float = DEFAULT_DURATION_TOLERANCE_S
    articles: tuple[str, ...] = DEFAULT_ARTICLES


def title_key(title: str, opts: DupOptions) -> str:
    if opts.ignore_versions:
        title = strip_versions(title)
    return match_key(title, ())  # lidwoorden in titels tellen wel mee


def best_item(group: Sequence[DupItem]) -> DupItem:
    """Hoogste bitrate, dan langste duur, dan kortste pad."""
    return max(
        group,
        key=lambda i: (i.bitrate_kbps or 0, i.duration_s or 0.0, -len(str(i.path))),
    )


def find_duplicates(
    items: Iterable[DupItem],
    opts: DupOptions = DupOptions(),  # noqa: B008 - frozen dataclass
    cancelled: Callable[[], bool] | None = None,
) -> list[list[DupItem]]:
    """Groepen van twee of meer tracks die waarschijnlijk hetzelfde nummer zijn.

    Binnen een groep staat de beste track (zie ``best_item``) vooraan.
    """
    items = [i for i in items if i.artist.strip() and i.title.strip()]
    artist_keys = {i.track_id: match_key(i.artist, opts.articles) for i in items}
    title_keys = {i.track_id: title_key(i.title, opts) for i in items}

    # Stap 1: blokken op artiest (exact of via fuzzy artiestclusters).
    if opts.fuzzy:
        counts: dict[str, int] = {}
        for i in items:
            counts[i.artist] = counts.get(i.artist, 0) + 1
        artist_group: dict[str, int] = {}
        for n, cluster in enumerate(
            cluster_artists(counts, opts.threshold, opts.articles, cancelled)
        ):
            for spelling, _ in cluster.members:
                artist_group[spelling] = n
        blocks: dict[object, list[DupItem]] = {}
        for i in items:
            block = (
                ("c", artist_group[i.artist])
                if i.artist in artist_group
                else ("k", artist_keys[i.track_id])
            )
            blocks.setdefault(block, []).append(i)
    else:
        blocks = {}
        for i in items:
            blocks.setdefault(artist_keys[i.track_id], []).append(i)

    # Stap 2: binnen elk blok op titel (exact of fuzzy) en eventueel jaar/duur.
    groups: list[list[DupItem]] = []
    for block_items in blocks.values():
        if cancelled is not None and cancelled():
            return []
        if len(block_items) < 2:
            continue
        for group in _group_titles(block_items, title_keys, opts):
            for sub in _split(group, opts):
                if len(sub) > 1:
                    best = best_item(sub)
                    groups.append([best] + [i for i in sub if i is not best])
    groups.sort(key=lambda g: (fold(g[0].artist), fold(g[0].title)))
    return groups


def _group_titles(
    block: list[DupItem], title_keys: dict[int, str], opts: DupOptions
) -> list[list[DupItem]]:
    if not opts.fuzzy:
        by_title: dict[str, list[DupItem]] = {}
        for i in block:
            by_title.setdefault(title_keys[i.track_id], []).append(i)
        return list(by_title.values())
    # Fuzzy: union-find binnen het (kleine) artiestblok.
    parent = list(range(len(block)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    keys = [title_keys[i.track_id] for i in block]
    for a in range(len(block)):
        for b in range(a + 1, len(block)):
            if combined_score(keys[a], keys[b]) >= opts.threshold:
                parent[find(b)] = find(a)
    result: dict[int, list[DupItem]] = {}
    for n, item in enumerate(block):
        result.setdefault(find(n), []).append(item)
    return list(result.values())


def _split(group: list[DupItem], opts: DupOptions) -> list[list[DupItem]]:
    """Splits verder op jaar en/of duur (als die criteria aan staan)."""
    parts = [group]
    if not opts.ignore_year:
        by_year: dict[int | None, list[DupItem]] = {}
        for i in group:
            by_year.setdefault(i.year, []).append(i)
        parts = list(by_year.values())
    if opts.use_duration:
        parts = [sub for part in parts for sub in _split_duration(part, opts.duration_tolerance_s)]
    return parts


def _split_duration(group: list[DupItem], tolerance: float) -> list[list[DupItem]]:
    known = sorted((i for i in group if i.duration_s is not None), key=lambda i: i.duration_s or 0)
    unknown = [i for i in group if i.duration_s is None]
    clusters: list[list[DupItem]] = []
    for item in known:
        if clusters and (item.duration_s or 0) - (clusters[-1][-1].duration_s or 0) <= tolerance:
            clusters[-1].append(item)
        else:
            clusters.append([item])
    if not clusters:
        return [unknown]
    # Onbekende duur kan niet worden uitgesloten: die hoort bij de grootste groep.
    max(clusters, key=len).extend(unknown)
    return clusters
