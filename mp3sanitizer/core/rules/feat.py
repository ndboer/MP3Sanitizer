"""9b. Featuring normaliseren en eventueel verplaatsen.

Varianten als los woord, hoofdletterongevoelig: ``feat``, ``feat.``, ``featuring``, ``ft``,
``ft.`` en ``f.`` worden de doelnotatie (``ft.`` of ``feat.``), ook binnen haakjes. Er ontstaan
geen dubbele punten of spaties.

Verplaatsen:
- naar de artiest: ``A`` / ``Song (ft. B)`` → ``A ft. B`` / ``Song``
- naar de titel: ``A ft. B`` / ``Song`` → ``A`` / ``Song (ft. B)``
"""

from __future__ import annotations

import re
from dataclasses import replace
from enum import StrEnum

from mp3sanitizer.core.models import Field
from mp3sanitizer.core.rules.base import Context, Rule, Values

_VARIANT = re.compile(r"(?<![\w.])(?:featuring|feat|ft|f(?=\.))\.*(?=\s|$)", re.IGNORECASE)
_SPACES = re.compile(r"\s{2,}")


class FeatTarget(StrEnum):
    FT = "ft."
    FEAT = "feat."


class FeatMove(StrEnum):
    NONE = "none"
    TO_ARTIST = "artist"
    TO_TITLE = "title"


def normalize_feat(text: str, target: str = FeatTarget.FT) -> str:
    text = _VARIANT.sub(target, text)
    return _SPACES.sub(" ", text).strip()


def _split_feat(text: str, target: str) -> tuple[str, str | None]:
    """Haal ``(ft. X)`` / ``[ft. X]`` / ``ft. X`` uit ``text``. Geeft (rest, X) of (text, None)."""
    t = re.escape(target)
    bracketed = re.search(rf"\s*[(\[]\s*{t}\s+([^)\]]+?)\s*[)\]]", text)
    if bracketed:
        rest = (text[: bracketed.start()] + text[bracketed.end() :]).strip()
        return _SPACES.sub(" ", rest), bracketed.group(1).strip()
    trailing = re.search(rf"\s+{t}\s+(.+)$", text)
    if trailing:
        return text[: trailing.start()].strip(), trailing.group(1).strip()
    return text, None


class FeaturingRule(Rule):
    id = "feat"
    label = "Featuring normaliseren"

    def __init__(self, target: str = FeatTarget.FT, move: FeatMove = FeatMove.NONE) -> None:
        self.target = str(target)
        self.move = move

    def apply(self, values: Values, ctx: Context) -> Values:
        artist = normalize_feat(values.artist, self.target)
        title = normalize_feat(values.title, self.target)
        if self.move is FeatMove.TO_ARTIST:
            rest, featured = _split_feat(title, self.target)
            _, already = _split_feat(artist, self.target)
            if featured and rest and already is None:
                artist, title = f"{artist} {self.target} {featured}", rest
        elif self.move is FeatMove.TO_TITLE:
            rest, featured = _split_feat(artist, self.target)
            _, already = _split_feat(title, self.target)
            if featured and rest and already is None:
                artist, title = rest, f"{title} ({self.target} {featured})"
        return replace(values, artist=artist, title=title)

    @property
    def fields(self) -> frozenset[Field]:
        return frozenset({Field.ARTIST, Field.TITLE})
