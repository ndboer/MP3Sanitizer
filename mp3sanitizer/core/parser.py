"""Parser voor bestandsnamen volgens ``<Artiest> - <Titel> (<Jaar>)``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from mp3sanitizer.core.models import ParseStatus

MIN_YEAR = 1900

# Scheidingsteken: hyphen, en-dash of em-dash met aan beide kanten minstens één spatie.
_SEPARATOR = re.compile(r"\s+[-–—]\s+")
_YEAR_AT_END = re.compile(r"\s*\((\d{4})\)\s*$")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ParsedName:
    artist: str
    title: str
    year: int | None
    status: ParseStatus


def max_year() -> int:
    return date.today().year + 1


def is_valid_year(year: int, *, upper: int | None = None) -> bool:
    return MIN_YEAR <= year <= (upper if upper is not None else max_year())


def clean_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def split_year(stem: str, *, upper: int | None = None) -> tuple[str, int | None]:
    """Haal een geldig jaar ``(dddd)`` van het eind af. Ongeldige jaren blijven in de tekst."""
    match = _YEAR_AT_END.search(stem)
    if match:
        year = int(match.group(1))
        if is_valid_year(year, upper=upper):
            return stem[: match.start()], year
    return stem, None


def format_stem(artist: str, title: str, year: int | None) -> str:
    """Omgekeerde van ``parse_filename``: ``Artiest - Titel (Jaar)`` of zonder jaar."""
    stem = f"{artist} - {title}" if artist else title
    return f"{stem} ({year})" if year is not None else stem


def parse_filename(stem: str, *, upper_year: int | None = None) -> ParsedName:
    """Parse een bestandsnaam zonder extensie.

    Er wordt alleen op het EERSTE scheidingsteken gesplitst; de titel mag zelf " - " bevatten.
    Bij een parse-fout is ``artist`` leeg en bevat ``title`` de (opgeschoonde) naam, zodat de
    gebruiker die handmatig kan corrigeren.
    """
    rest, year = split_year(stem, upper=upper_year)
    parts = _SEPARATOR.split(rest, maxsplit=1)
    if len(parts) == 2:
        artist, title = clean_whitespace(parts[0]), clean_whitespace(parts[1])
        if artist and title:
            status = ParseStatus.OK if year is not None else ParseStatus.NO_YEAR
            return ParsedName(artist, title, year, status)
    return ParsedName("", clean_whitespace(rest), year, ParseStatus.ERROR)
