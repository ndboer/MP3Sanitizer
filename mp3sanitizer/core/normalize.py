"""Normalisatie van namen voor sorteren, vergelijken en fuzzy matching."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

DEFAULT_ARTICLES: tuple[str, ...] = (
    "The",
    "De",
    "Het",
    "Die",
    "Der",
    "Das",
    "Les",
    "Le",
    "La",
    "Los",
    "El",
    "Il",
)

_WHITESPACE = re.compile(r"\s+")
_AND_WORDS = re.compile(r"\s*(?:&|\+)\s*|\s+(?:and|en)\s+")
_PUNCTUATION = re.compile(r"[^\w\s&]")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "´": "'", "`": "'"})


def strip_diacritics(text: str) -> str:
    """Beyoncé → Beyonce."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def fold(text: str) -> str:
    """Hoofdletterongevoelig en zonder diacrieten, met opgeschoonde spaties."""
    return _WHITESPACE.sub(" ", strip_diacritics(text).casefold()).strip()


def strip_article(folded: str, articles: Iterable[str] = DEFAULT_ARTICLES) -> str:
    """Verwijder een lidwoord aan het begin ('the beatles') of in de vorm 'beatles, the'."""
    for article in articles:
        a = fold(article)
        if folded.startswith(a + " ") and len(folded) > len(a) + 1:
            return folded[len(a) + 1 :]
        if folded.endswith(", " + a):
            return folded[: -(len(a) + 2)].rstrip()
    return folded


def sort_key(artist: str, articles: Iterable[str] = DEFAULT_ARTICLES) -> str:
    """Sorteersleutel waarmee 'The Beatles' bij de B staat."""
    return strip_article(fold(artist.translate(_QUOTES)), articles)


def match_key(name: str, articles: Iterable[str] = DEFAULT_ARTICLES) -> str:
    """Sleutel voor fuzzy vergelijken: lidwoorden, '&/and/en/+' en leestekens genegeerd."""
    key = strip_article(fold(name.translate(_QUOTES)), articles)
    key = _AND_WORDS.sub(" & ", key)
    key = _PUNCTUATION.sub(" ", key)
    return _WHITESPACE.sub(" ", key).strip()


def loose_equal(a: str | None, b: str | None) -> bool:
    """Vergelijking voor tag-mismatch: hoofdletters, spaties en quotes tellen niet mee."""
    if a is None or b is None:
        return a == b
    return fold(a.translate(_QUOTES)) == fold(b.translate(_QUOTES))
