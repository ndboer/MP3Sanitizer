import pytest

from mp3sanitizer.core.models import Field
from mp3sanitizer.core.rules.replace import (
    ReplacementRule,
    ReplacementRuleSet,
    RuleField,
    default_rules,
)
from mp3sanitizer.core.rules.roman import RomanNumeralRule, is_roman, roman_value


def _defaults(text, field=Field.TITLE):
    return ReplacementRuleSet(default_rules()).transform(text, field)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Queen vs David Bowie", "Queen vs. David Bowie"),
        ("Queen Vs. David Bowie", "Queen vs. David Bowie"),
        ("Queen VS. Bowie", "Queen vs. Bowie"),
        ("Queen versus Bowie", "Queen vs. Bowie"),
        ("Queen vs. Bowie", "Queen vs. Bowie"),  # nooit 'vs..'
        ("Vsauce", "Vsauce"),
        ("Simon &amp; Garfunkel", "Simon & Garfunkel"),
        ("A  -   B", "A - B"),
        ("Song (Live )", "Song (Live)"),
        ("Don´t Stop", "Don't Stop"),
        ("Don`t Stop", "Don't Stop"),
    ],
)
def test_default_rules(text, expected):
    assert _defaults(text) == expected


def test_defaults_can_be_disabled():
    rules = default_rules()
    for r in rules:
        r.active = r.id != "builtin-vs"
    assert ReplacementRuleSet(rules).transform("A vs B", Field.TITLE) == "A vs B"


def test_whole_word_and_case():
    rule = ReplacementRule("the", "de", whole_word=True)
    assert rule.apply_to("The Other theme") == "de Other theme"
    rule = ReplacementRule("The", "De", whole_word=True, case_sensitive=True)
    assert rule.apply_to("the The") == "the De"


def test_plain_replacement_has_no_backslash_escapes():
    assert ReplacementRule("x", r"\1").apply_to("axb") == r"a\1b"


def test_regex_with_groups():
    rule = ReplacementRule(r"(\w+), The", r"The \1", regex=True)
    assert rule.error() is None
    assert rule.apply_to("Beatles, The") == "The Beatles"


@pytest.mark.parametrize(
    ("find", "replace", "regex", "message"),
    [
        ("(", "", True, "Ongeldige regex"),
        ("a", r"\2", True, "Ongeldige regex"),
        ("", "x", False, "leeg"),
    ],
)
def test_invalid_rules_are_reported_and_skipped(find, replace, regex, message):
    rule = ReplacementRule(find, replace, regex=regex)
    assert message in (rule.error() or "")
    # een ongeldige regel breekt de set niet
    assert ReplacementRuleSet([rule]).transform("abc", Field.TITLE) == "abc"


def test_field_scope():
    rules = [ReplacementRule("x", "y", field=RuleField.ARTIST)]
    rs = ReplacementRuleSet(rules)
    assert rs.transform("x", Field.ARTIST) == "y"
    assert rs.transform("x", Field.TITLE) == "x"


def test_roundtrip_dict():
    rule = ReplacementRule("a", "b", RuleField.TITLE, whole_word=True, name="test")
    again = ReplacementRule.from_dict(rule.to_dict() | {"onbekend": 1})
    assert again == rule


# --- Romeinse cijfers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "valid", "value"),
    [
        ("iv", True, 4),
        ("XXXIX", True, 39),
        ("mcmxc", True, 1990),
        ("IIII", False, 0),
        ("Mix", True, 1009),  # geldig! daarom staat Mix op de uitzonderingslijst
        ("", False, 0),
        ("IC", False, 0),
    ],
)
def test_is_roman(word, valid, value):
    assert is_roman(word) is valid
    if valid:
        assert roman_value(word) == value


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Rocky Iv", "Rocky IV"),
        ("Part Ii", "Part II"),
        ("Pt. iii of the Saga", "Pt. III of the Saga"),
        ("Club Mix", "Club Mix"),
        ("Vol. Mcm", "Vol. MCM"),  # boven XXXIX, maar na Vol.
        ("Symphony No. Mcm Dreams", "Symphony No. Mcm Dreams"),  # groot en niet in context
        ("Super Bowl Liv", "Super Bowl Liv"),  # uitzondering
        ("Final Fantasy Xiv", "Final Fantasy XIV"),
        ("Civil War", "Civil War"),
        ("Mi Amor", "Mi Amor"),
        ("Louis Xvi Suite", "Louis XVI Suite"),
        ("Ramses Cl", "Ramses CL"),  # aan het eind van de titel
        ("i Love You", "I Love You"),
        ("ROCKY IV", "ROCKY IV"),
    ],
)
def test_roman_in_titles(text, expected):
    assert RomanNumeralRule().transform(text, Field.TITLE) == expected


def test_roman_options():
    strict = RomanNumeralRule(max_value=None, context_words=[], at_end_of_title=False)
    assert strict.transform("Rocky Iv", Field.TITLE) == "Rocky Iv"
    no_end = RomanNumeralRule(at_end_of_title=False)
    assert no_end.transform("Ramses Cl", Field.TITLE) == "Ramses Cl"
    # 'aan het eind' geldt alleen voor titels
    assert RomanNumeralRule().transform("Ramses Cl", Field.ARTIST) == "Ramses Cl"
    assert RomanNumeralRule(exceptions=[]).transform("Club Mix", Field.TITLE) == "Club MIX"


def test_roman_artist():
    assert RomanNumeralRule().transform("Boyz Ii Men", Field.ARTIST) == "Boyz II Men"
