"""9e. Extra correcties: Title Case, spaties, jaar uit tag en 'Artiest, The' ↔ 'The Artiest'."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace
from enum import StrEnum

from mp3sanitizer.core.models import Field
from mp3sanitizer.core.normalize import DEFAULT_ARTICLES
from mp3sanitizer.core.parser import is_valid_year
from mp3sanitizer.core.rules.base import Context, Rule, TextRule, Values
from mp3sanitizer.core.rules.roman import is_roman

DEFAULT_SMALL_WORDS: tuple[str, ...] = (
    "of",
    "the",
    "a",
    "an",
    "in",
    "on",
    "at",
    "to",
    "and",
    "or",
    "for",
    "van",
    "de",
    "het",
    "een",
    "en",
    "ft",  # featuring/versus blijven klein (ft., feat., vs.)
    "feat",
    "vs",
)

_TOKEN = re.compile(r"(\s+)")
_LETTERS = re.compile(r"[^\W\d_]+", re.UNICODE)


def _core(token: str) -> tuple[str, str, str]:
    """Splits '(word)' in ('(', 'word', ')')."""
    start = 0
    while start < len(token) and not token[start].isalnum():
        start += 1
    end = len(token)
    while end > start and not token[end - 1].isalnum():
        end -= 1
    return token[:start], token[start:end], token[end:]


def _keep_as_is(word: str) -> bool:
    """Afkortingen (DJ, U.S.A.), Romeinse cijfers (IV) en woorden als McCartney/iPod."""
    letters = "".join(_LETTERS.findall(word))
    if not letters:
        return True
    if len(letters) >= 2 and letters.isupper():
        return True
    if word.isupper() and is_roman(word):
        return True
    return any(c.isupper() for c in word[1:])  # interne hoofdletter


def _capitalize(word: str) -> str:
    """Eerste letter groot, rest klein; 'don't' → "Don't", 'a-ha' → 'A-ha'."""
    for i, ch in enumerate(word):
        if ch.isalpha():
            return word[:i] + ch.upper() + word[i + 1 :].lower()
    return word


class TitleCaseRule(TextRule):
    id = "titlecase"
    label = "Title Case (artiest en titel)"

    def __init__(self, small_words: Iterable[str] = DEFAULT_SMALL_WORDS) -> None:
        self.small = {w.strip().casefold() for w in small_words if w.strip()}

    def transform(self, text: str, field: Field) -> str:
        words = [t for t in _TOKEN.split(text) if t and not t.isspace()]
        # Alles in hoofdletters (meer dan één woord) is geen reeks afkortingen: eerst verkleinen.
        if len(words) > 1 and text.isupper():
            text = text.lower()
        parts = _TOKEN.split(text)
        result: list[str] = []
        start_of_phrase = True  # begin, na '(' of na ' - '
        for part in parts:
            if not part or part.isspace():
                result.append(part)
                continue
            if part in ("-", "–", "—", "/"):
                result.append(part)
                start_of_phrase = True
                continue
            prefix, core, suffix = _core(part)
            if not core:
                result.append(part)
                continue
            opens_phrase = "(" in prefix or "[" in prefix
            if _keep_as_is(core):
                new = core
            elif core.casefold() in self.small and not (start_of_phrase or opens_phrase):
                new = core.lower()
            else:
                new = _capitalize(core)
            result.append(prefix + new + suffix)
            start_of_phrase = suffix.endswith(":")
        return "".join(result)


_SPACES = re.compile(r"\s{2,}")
_DASH = re.compile(r"\s+-\s*|\s*-\s+")  # alleen streepjes met een spatie ernaast (niet A-ha)
_OPEN = re.compile(r"([(\[])\s+")
_CLOSE = re.compile(r"\s+([)\]])")
_BEFORE_OPEN = re.compile(r"(?<=[^\s(\[])([(\[])")


class SpacingRule(TextRule):
    id = "spacing"
    label = "Spaties opschonen"

    def transform(self, text: str, field: Field) -> str:
        text = text.strip()
        text = _DASH.sub(" - ", text)
        text = _OPEN.sub(r"\1", text)
        text = _CLOSE.sub(r"\1", text)
        text = _BEFORE_OPEN.sub(r" \1", text)
        return _SPACES.sub(" ", text).strip()


class YearFromTagRule(Rule):
    id = "tagyear"
    label = "Jaar uit de tag overnemen (als het jaar ontbreekt)"

    def apply(self, values: Values, ctx: Context) -> Values:
        if values.year is None and ctx.tag_year is not None and is_valid_year(ctx.tag_year):
            return replace(values, year=ctx.tag_year)
        return values


class ArticlePosition(StrEnum):
    FRONT = "front"  # The Beatles
    BACK = "back"  # Beatles, The


class ArticleRule(TextRule):
    id = "article"
    label = "Lidwoord in de artiest consequent maken"
    fields = frozenset({Field.ARTIST})

    def __init__(
        self,
        position: ArticlePosition = ArticlePosition.FRONT,
        articles: Iterable[str] = DEFAULT_ARTICLES,
    ) -> None:
        self.position = position
        self.articles = [a for a in articles if a.strip()]

    def transform(self, text: str, field: Field) -> str:
        for article in self.articles:
            a = re.escape(article)
            if self.position is ArticlePosition.FRONT:
                m = re.fullmatch(rf"(.+?),\s*({a})", text, re.IGNORECASE)
                if m:  # canonieke schrijfwijze van het lidwoord ('the' → 'The')
                    return f"{article} {m.group(1)}"
            else:
                m = re.fullmatch(rf"({a})\s+(.+)", text, re.IGNORECASE)
                if m and "," not in m.group(2):
                    return f"{m.group(2)}, {article}"
        return text
