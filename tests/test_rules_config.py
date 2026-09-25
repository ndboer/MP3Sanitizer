import json

import pytest

from mp3sanitizer.core.rules.base import Context, Values, run_rules
from mp3sanitizer.core.rules.config import (
    DEFAULT_PROFILE,
    RULE_ORDER,
    RulesConfig,
    RulesStore,
    export_rules,
    import_rules,
)
from mp3sanitizer.core.rules.replace import ReplacementRule


def test_build_uses_fixed_order():
    cfg = RulesConfig()
    rules = cfg.build(["roman", "titlecase", "spacing", "feat"])
    assert [r.id for r in rules] == ["spacing", "titlecase", "feat", "roman"]
    assert [r.id for r in cfg.build(["feat", "article"])] == ["article", "feat"]
    assert [r.id for r in cfg.build(RULE_ORDER)] == list(RULE_ORDER)


def test_full_profile_example():
    cfg = RulesConfig(feat_move="artist")
    rules = cfg.build(["spacing", "titlecase", "replace", "feat", "abbrev", "roman", "article"])
    out = run_rules(
        rules,
        Values("beatles, the", "  rocky iv  (featuring dj x) vs the u.s.a"),
        Context(),
    )
    assert out.artist == "The Beatles ft. DJ X"
    assert out.title == "Rocky IV vs. the U.S.A."


def test_year_from_tag_in_profile():
    rules = RulesConfig().build(["tagyear"])
    assert run_rules(rules, Values("A", "B"), Context(tag_year=1999)).year == 1999


def test_roman_max_zero_disables_value_condition():
    rules = RulesConfig(roman_max=0, roman_at_end=False, roman_context=[]).build(["roman"])
    assert run_rules(rules, Values("A", "Rocky Iv")).title == "Rocky Iv"


def test_store_roundtrip_and_profiles(tmp_path):
    store = RulesStore.load(tmp_path)
    assert DEFAULT_PROFILE in store.config.profiles
    store.config.profiles["Alleen hoofdletters"] = ["titlecase", "abbrev", "bestaat-niet"]
    store.config.replacement_rules.append(ReplacementRule("Pt.", "Part", name="eigen"))
    store.config.abbreviations.append("NASA")
    assert store.save()
    again = RulesStore.load(tmp_path)
    assert again.config.abbreviations[-1] == "NASA"
    assert again.config.replacement_rules[-1].find == "Pt."
    # onbekende regel-ids verdwijnen bij het laden
    assert again.config.profiles["Alleen hoofdletters"] == ["titlecase", "abbrev"]
    data = json.loads((tmp_path / "rules.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1


def test_unknown_rule_ids_dropped_on_load(tmp_path):
    (tmp_path / "rules.json").write_text(
        json.dumps({"schema_version": 1, "profiles": {"P": ["abbrev", "weg"]}, "roman_max": "x"}),
        encoding="utf-8",
    )
    cfg = RulesStore.load(tmp_path).config
    assert cfg.profiles == {"P": ["abbrev"]}
    assert cfg.roman_max == 39


def test_builtins_are_restored_if_missing():
    cfg = RulesConfig.from_dict({"replacement_rules": [{"find": "x", "replace": "y"}]})
    ids = [r.id for r in cfg.replacement_rules]
    assert ids[0] != "builtin-vs"
    assert "builtin-vs" in ids and "builtin-amp" in ids


def test_export_import(tmp_path):
    rules = [ReplacementRule("a", "b", name="mijn regel"), *RulesConfig().replacement_rules]
    export_rules(tmp_path / "set.json", rules)
    imported = import_rules(tmp_path / "set.json")
    assert [r.find for r in imported] == ["a"]  # standaardregels worden niet geëxporteerd
    assert not imported[0].builtin


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{kapot", "niet lezen"),
        ('{"kind": "iets anders"}', "geen Mp3Sanitizer-regelset"),
        ('{"kind": "mp3sanitizer.replacement_rules", "schema_version": 9}', "nieuwere versie"),
    ],
)
def test_import_errors(tmp_path, content, message):
    path = tmp_path / "x.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        import_rules(path)
    assert path.exists()  # een importbestand wordt nooit hernoemd of aangepast
