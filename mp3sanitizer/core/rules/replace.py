"""9c. Eigen vervangingsregels (zoek → vervang), met standaardregels die uit te zetten zijn."""

from __future__ import annotations

import dataclasses
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from typing import Any

from mp3sanitizer.core.models import Field
from mp3sanitizer.core.rules.base import TextRule


class RuleField(StrEnum):
    ARTIST = "artist"
    TITLE = "title"
    BOTH = "both"

    def covers(self, f: Field) -> bool:
        return self is RuleField.BOTH or self.value == f.value


@dataclass(slots=True)
class ReplacementRule:
    find: str
    replace: str = ""
    field: RuleField = RuleField.BOTH
    whole_word: bool = False
    case_sensitive: bool = False
    regex: bool = False
    active: bool = True
    builtin: bool = False  # standaardregel: niet te verwijderen, wel uit te zetten
    name: str = ""
    # dataclasses.field voluit: het attribuut 'field' hierboven overschaduwt de korte naam.
    id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex[:8])

    def compile(self) -> re.Pattern[str]:
        """Raises ``re.error`` bij een ongeldige reguliere expressie."""
        pattern = self.find if self.regex else re.escape(self.find)
        if self.whole_word:
            pattern = rf"(?<!\w)(?:{pattern})(?!\w)"
        return re.compile(pattern, 0 if self.case_sensitive else re.IGNORECASE)

    def error(self) -> str | None:
        """Foutmelding als de regel ongeldig is, anders ``None``."""
        if not self.find:
            return "Zoektekst is leeg"
        try:
            pattern = self.compile()
            if self.regex:
                pattern.sub(self.replace, "")  # controleert ook groepsverwijzingen als \1
        except (re.error, IndexError) as exc:
            return f"Ongeldige regex: {exc}"
        return None

    def apply_to(self, text: str) -> str:
        pattern = self.compile()
        if self.regex:
            return pattern.sub(self.replace, text)
        return pattern.sub(lambda _m: self.replace, text)  # geen backslash-escapes

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["field"] = self.field.value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReplacementRule:
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["field"] = RuleField(kwargs.get("field", RuleField.BOTH))
        return cls(**kwargs)


def default_rules() -> list[ReplacementRule]:
    """Standaardregels uit de specificatie (uitschakelbaar)."""
    return [
        ReplacementRule(
            r"(?<!\w)(?:vs\.?|versus)(?!\w)(?!\.)",
            "vs.",
            regex=True,
            builtin=True,
            name="vs / Vs. / versus → vs.",
            id="builtin-vs",
        ),
        ReplacementRule("&amp;", "&", builtin=True, name="&amp; → &", id="builtin-amp"),
        ReplacementRule(
            r"\s{2,}", " ", regex=True, builtin=True, name="dubbele spaties", id="builtin-spaces"
        ),
        ReplacementRule(
            r"\s+\)", ")", regex=True, builtin=True, name="spatie vóór ) weg", id="builtin-paren"
        ),
        ReplacementRule(
            "[´`]", "'", regex=True, builtin=True, name="´ en ` → '", id="builtin-quote"
        ),
    ]


class ReplacementRuleSet(TextRule):
    """Past alle actieve (en geldige) regels in volgorde toe."""

    id = "replace"
    label = "Eigen vervangingsregels"

    def __init__(self, rules: Iterable[ReplacementRule]) -> None:
        self.rules = [r for r in rules if r.active and r.error() is None]
        self._compiled = [(r, r.compile()) for r in self.rules]

    def transform(self, text: str, field: Field) -> str:
        for rule, pattern in self._compiled:
            if rule.field.covers(field):
                text = (
                    pattern.sub(rule.replace, text)
                    if rule.regex
                    else pattern.sub(lambda _m, r=rule.replace: r, text)
                )
        return text.strip()
