"""Configuratie van alle correctieregels (``rules.json``), opschoonprofielen en import/export.

Regels worden altijd in een vaste volgorde toegepast, ongeacht de volgorde waarin ze zijn
aangevinkt: eerst spaties en hoofdletters, daarna vervangingen, lidwoord, featuring, afkortingen
en Romeinse cijfers (die de hoofdletters van Title Case weer rechtzetten), tot slot het jaar.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from mp3sanitizer.core import migrations
from mp3sanitizer.core.normalize import DEFAULT_ARTICLES
from mp3sanitizer.core.rules.abbrev import DEFAULT_ABBREVIATIONS, AbbreviationRule
from mp3sanitizer.core.rules.base import Rule
from mp3sanitizer.core.rules.casing import (
    DEFAULT_SMALL_WORDS,
    ArticlePosition,
    ArticleRule,
    SpacingRule,
    TitleCaseRule,
    YearFromTagRule,
)
from mp3sanitizer.core.rules.feat import FeatMove, FeatTarget, FeaturingRule
from mp3sanitizer.core.rules.replace import ReplacementRule, ReplacementRuleSet, default_rules
from mp3sanitizer.core.rules.roman import (
    DEFAULT_CONTEXT_WORDS,
    DEFAULT_EXCEPTIONS,
    RomanNumeralRule,
)
from mp3sanitizer.core.storage import LoadResult, LoadStatus, load_document, save_document

log = logging.getLogger(__name__)

RULES_SCHEMA_VERSION = 1
RULES_FILENAME = "rules.json"
EXPORT_KIND = "mp3sanitizer.replacement_rules"

# Vaste volgorde (zie moduledocstring).
RULE_ORDER: tuple[str, ...] = (
    SpacingRule.id,
    TitleCaseRule.id,
    ReplacementRuleSet.id,
    ArticleRule.id,  # vóór featuring: 'Beatles, The ft. X' is anders niet meer te herkennen
    FeaturingRule.id,
    AbbreviationRule.id,
    RomanNumeralRule.id,
    YearFromTagRule.id,
)
RULE_LABELS: dict[str, str] = {
    SpacingRule.id: SpacingRule.label,
    TitleCaseRule.id: TitleCaseRule.label,
    ReplacementRuleSet.id: ReplacementRuleSet.label,
    FeaturingRule.id: FeaturingRule.label,
    AbbreviationRule.id: AbbreviationRule.label,
    RomanNumeralRule.id: RomanNumeralRule.label,
    ArticleRule.id: ArticleRule.label,
    YearFromTagRule.id: YearFromTagRule.label,
}
DEFAULT_PROFILE = "Standaard opschonen"


def _default_profiles() -> dict[str, list[str]]:
    return {
        DEFAULT_PROFILE: [
            SpacingRule.id,
            ReplacementRuleSet.id,
            FeaturingRule.id,
            AbbreviationRule.id,
            RomanNumeralRule.id,
        ]
    }


@dataclass(slots=True)
class RulesConfig:
    replacement_rules: list[ReplacementRule] = field(default_factory=default_rules)
    abbreviations: list[str] = field(default_factory=lambda: list(DEFAULT_ABBREVIATIONS))
    abbreviation_exceptions: list[str] = field(default_factory=list)
    feat_target: str = FeatTarget.FT.value
    feat_move: str = FeatMove.NONE.value
    roman_max: int = 39  # 0 = voorwaarde uit
    roman_context: list[str] = field(default_factory=lambda: list(DEFAULT_CONTEXT_WORDS))
    roman_at_end: bool = True
    roman_exceptions: list[str] = field(default_factory=lambda: list(DEFAULT_EXCEPTIONS))
    small_words: list[str] = field(default_factory=lambda: list(DEFAULT_SMALL_WORDS))
    article_position: str = ArticlePosition.FRONT.value
    profiles: dict[str, list[str]] = field(default_factory=_default_profiles)
    last_selection: list[str] = field(default_factory=lambda: _default_profiles()[DEFAULT_PROFILE])

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {f.name: getattr(self, f.name) for f in fields(self)}
        data["replacement_rules"] = [r.to_dict() for r in self.replacement_rules]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RulesConfig:
        """Tolerant: onbekende of verkeerd getypeerde waarden vallen terug op de standaard."""
        cfg = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            value, default = data[f.name], getattr(cfg, f.name)
            if f.name == "replacement_rules":
                if isinstance(value, list):
                    cfg.replacement_rules = _merge_builtins(_parse_rules(value))
            elif f.name == "profiles":
                if isinstance(value, dict):
                    cfg.profiles = {
                        str(k): [str(x) for x in v if str(x) in RULE_LABELS]
                        for k, v in value.items()
                        if isinstance(v, list)
                    }
            elif isinstance(default, bool):
                if isinstance(value, bool):
                    setattr(cfg, f.name, value)
            elif isinstance(default, int):
                if isinstance(value, int) and not isinstance(value, bool):
                    setattr(cfg, f.name, value)
            elif isinstance(default, list):
                if isinstance(value, list):
                    setattr(cfg, f.name, [str(x) for x in value])
            elif isinstance(default, str) and isinstance(value, str):
                setattr(cfg, f.name, value)
        return cfg

    def build(
        self, rule_ids: Iterable[str], articles: Sequence[str] = DEFAULT_ARTICLES
    ) -> list[Rule]:
        """Regels voor de gekozen ids, in de vaste ``RULE_ORDER``."""
        wanted = set(rule_ids)
        factories = {
            SpacingRule.id: SpacingRule,
            TitleCaseRule.id: lambda: TitleCaseRule(self.small_words),
            ReplacementRuleSet.id: lambda: ReplacementRuleSet(self.replacement_rules),
            FeaturingRule.id: lambda: FeaturingRule(self.feat_target, FeatMove(self.feat_move)),
            AbbreviationRule.id: lambda: AbbreviationRule(
                self.abbreviations, self.abbreviation_exceptions
            ),
            RomanNumeralRule.id: lambda: RomanNumeralRule(
                self.roman_max or None, self.roman_context, self.roman_at_end, self.roman_exceptions
            ),
            ArticleRule.id: lambda: ArticleRule(ArticlePosition(self.article_position), articles),
            YearFromTagRule.id: YearFromTagRule,
        }
        return [factories[rid]() for rid in RULE_ORDER if rid in wanted]


def _parse_rules(items: list[Any]) -> list[ReplacementRule]:
    rules = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("find"), str):
            try:
                rules.append(ReplacementRule.from_dict(item))
            except (TypeError, ValueError) as exc:
                log.warning("Vervangingsregel overgeslagen: %s (%s)", item, exc)
    return rules


def _merge_builtins(rules: list[ReplacementRule]) -> list[ReplacementRule]:
    """Standaardregels die (nog) ontbreken worden achteraan toegevoegd."""
    present = {r.id for r in rules}
    return rules + [b for b in default_rules() if b.id not in present]


@dataclass(slots=True)
class RulesStore:
    path: Path
    config: RulesConfig
    load_result: LoadResult

    @classmethod
    def load(cls, config_dir: Path) -> RulesStore:
        path = config_dir / RULES_FILENAME
        result = load_document(path, RULES_SCHEMA_VERSION, migrations.RULES)
        config = RulesConfig.from_dict(result.data) if result.data else RulesConfig()
        return cls(path, config, result)

    def save(self) -> bool:
        if not self.load_result.writable:
            return False
        save_document(self.path, self.config.to_dict(), RULES_SCHEMA_VERSION)
        return True


# --- import/export van vervangingsregels -----------------------------------------------------


def export_rules(path: Path, rules: Sequence[ReplacementRule]) -> None:
    payload = {
        "schema_version": RULES_SCHEMA_VERSION,
        "kind": EXPORT_KIND,
        "rules": [r.to_dict() for r in rules if not r.builtin],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def import_rules(path: Path) -> list[ReplacementRule]:
    """Lees een geëxporteerde regelset. Raises ``ValueError`` met een leesbare melding."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Kan {path.name} niet lezen: {exc}") from exc
    if not isinstance(data, dict) or data.get("kind") != EXPORT_KIND:
        raise ValueError(f"{path.name} is geen Mp3Sanitizer-regelset")
    version = data.get("schema_version", 1)
    if not isinstance(version, int) or version > RULES_SCHEMA_VERSION:
        raise ValueError(f"{path.name} is gemaakt met een nieuwere versie van Mp3Sanitizer")
    rules = _parse_rules(data.get("rules", []))
    for r in rules:
        r.builtin = False
    return rules


__all__ = [
    "DEFAULT_PROFILE",
    "RULE_LABELS",
    "RULE_ORDER",
    "LoadStatus",
    "RulesConfig",
    "RulesStore",
    "export_rules",
    "import_rules",
]
