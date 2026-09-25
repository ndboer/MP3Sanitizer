"""Gemeenschappelijke basis voor correctieregels en het toepassen van een profiel."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import ClassVar

from mp3sanitizer.core.models import Field, PendingChange


@dataclass(frozen=True, slots=True)
class Values:
    artist: str
    title: str
    year: int | None = None

    def get(self, field: Field) -> str | int | None:
        return {Field.ARTIST: self.artist, Field.TITLE: self.title, Field.YEAR: self.year}[field]


@dataclass(frozen=True, slots=True)
class Context:
    """Extra gegevens die sommige regels nodig hebben."""

    tag_year: int | None = None


class Rule(ABC):
    id: ClassVar[str]
    label: ClassVar[str]

    @abstractmethod
    def apply(self, values: Values, ctx: Context) -> Values: ...


class TextRule(Rule):
    """Regel die artiest en/of titel los van elkaar bewerkt."""

    fields: frozenset[Field] = frozenset({Field.ARTIST, Field.TITLE})

    @abstractmethod
    def transform(self, text: str, field: Field) -> str: ...

    def apply(self, values: Values, ctx: Context) -> Values:
        artist = (
            self.transform(values.artist, Field.ARTIST)
            if Field.ARTIST in self.fields
            else values.artist
        )
        title = (
            self.transform(values.title, Field.TITLE)
            if Field.TITLE in self.fields
            else values.title
        )
        return replace(values, artist=artist, title=title)


def run_rules(rules: Sequence[Rule], values: Values, ctx: Context = Context()) -> Values:  # noqa: B008
    for rule in rules:
        values = rule.apply(values, ctx)
    return values


@dataclass(frozen=True, slots=True)
class CorrectionInput:
    track_id: int
    values: Values
    ctx: Context = field(default_factory=Context)


def compute_corrections(
    inputs: Iterable[CorrectionInput], rules: Sequence[Rule], source: str = "rule"
) -> list[PendingChange]:
    """Wijzigingen per veld die het profiel zou maken (alleen velden die echt veranderen)."""
    changes: list[PendingChange] = []
    for inp in inputs:
        new = run_rules(rules, inp.values, inp.ctx)
        for f in (Field.ARTIST, Field.TITLE, Field.YEAR):
            old_value, new_value = inp.values.get(f), new.get(f)
            if old_value != new_value:
                changes.append(PendingChange(inp.track_id, f, old_value, new_value, source))
    return changes
