import pytest

from mp3sanitizer.core.models import Field
from mp3sanitizer.core.rules.abbrev import AbbreviationRule
from mp3sanitizer.core.rules.base import (
    Context,
    CorrectionInput,
    Values,
    compute_corrections,
    run_rules,
)
from mp3sanitizer.core.rules.feat import FeatMove, FeatTarget, FeaturingRule, normalize_feat


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Born In The U.s.a", "Born In The U.S.A."),
        ("Made in u.k.", "Made in U.K."),
        ("L.a. Woman", "L.A. Woman"),
        ("R.e.m.", "R.E.M."),
        ("U.S.A.", "U.S.A."),  # al goed: geen dubbele punt
        ("U.S.A..", "U.S.A."),
        ("St. Louis Blues", "St. Louis Blues"),  # één letter + punt is geen afkorting
        ("dj shadow", "DJ Shadow".replace("Shadow", "shadow")),
        ("Mc Hammer", "MC Hammer"),
        ("ac/dc", "AC/DC"),
        ("Abba Gold", "ABBA Gold"),
        ("Abbatoir", "Abbatoir"),  # geen los woord
        ("Radio Djibouti", "Radio Djibouti"),
        ("ub40", "UB40"),
    ],
)
def test_abbreviations(text, expected):
    assert AbbreviationRule().transform(text, Field.TITLE) == expected


def test_abbreviation_exceptions_and_custom_list():
    rule = AbbreviationRule(abbreviations=["NASA"], exceptions=["u.s.a", "Nasa"])
    assert rule.transform("u.s.a nasa", Field.TITLE) == "u.s.a nasa"
    assert rule.transform("u.k. nasa", Field.TITLE) == "U.K. nasa"
    assert AbbreviationRule(abbreviations=[]).transform("dj", Field.TITLE) == "dj"


def test_abbreviation_idempotent():
    rule = AbbreviationRule()
    once = rule.transform("u.s.a dj L.a.", Field.TITLE)
    assert rule.transform(once, Field.TITLE) == once


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A feat B", "A ft. B"),
        ("A feat. B", "A ft. B"),
        ("A Featuring B", "A ft. B"),
        ("A FT B", "A ft. B"),
        ("A ft.. B", "A ft. B"),
        ("A f. B", "A ft. B"),
        ("Song (Featuring X)", "Song (ft. X)"),
        ("Song [feat. X]", "Song [ft. X]"),
        ("Song (feat.  X)", "Song (ft. X)"),
        ("Aftermath", "Aftermath"),
        ("Feather", "Feather"),
        ("Lift Off", "Lift Off"),
    ],
)
def test_normalize_feat(text, expected):
    assert normalize_feat(text) == expected


def test_feat_target_notation():
    assert normalize_feat("A ft. B", FeatTarget.FEAT) == "A feat. B"
    assert normalize_feat("A feat. B", FeatTarget.FEAT) == "A feat. B"  # nooit 'feat..'


def test_move_to_artist():
    rule = FeaturingRule(move=FeatMove.TO_ARTIST)
    out = rule.apply(Values("Eminem", "Stan (Featuring Dido)"), Context())
    assert (out.artist, out.title) == ("Eminem ft. Dido", "Stan")
    out = rule.apply(Values("Eminem", "Stan feat. Dido"), Context())
    assert (out.artist, out.title) == ("Eminem ft. Dido", "Stan")
    # artiest heeft al een featuring: niets verplaatsen
    out = rule.apply(Values("A ft. B", "Song (ft. C)"), Context())
    assert (out.artist, out.title) == ("A ft. B", "Song (ft. C)")


def test_move_to_title():
    rule = FeaturingRule(move=FeatMove.TO_TITLE)
    out = rule.apply(Values("Eminem feat Dido", "Stan (Remix)"), Context())
    assert (out.artist, out.title) == ("Eminem", "Stan (Remix) (ft. Dido)")
    out = rule.apply(Values("Eminem (feat. Dido)", "Stan"), Context())
    assert (out.artist, out.title) == ("Eminem", "Stan (ft. Dido)")


def test_move_is_idempotent():
    for move in (FeatMove.TO_ARTIST, FeatMove.TO_TITLE):
        rule = FeaturingRule(move=move)
        once = rule.apply(Values("A feat B", "Song (featuring C)"), Context())
        assert rule.apply(once, Context()) == once


def test_compute_corrections_per_field():
    changes = compute_corrections(
        [
            CorrectionInput(1, Values("Eminem", "Stan (Featuring Dido)", 2000)),
            CorrectionInput(2, Values("Queen", "Innuendo", 1991)),
        ],
        [FeaturingRule(move=FeatMove.TO_ARTIST)],
        source="rule:feat",
    )
    assert [(c.track_id, c.field, c.old, c.new) for c in changes] == [
        (1, Field.ARTIST, "Eminem", "Eminem ft. Dido"),
        (1, Field.TITLE, "Stan (Featuring Dido)", "Stan"),
    ]
    assert {c.source for c in changes} == {"rule:feat"}


def test_run_rules_in_order():
    rules = [FeaturingRule(), AbbreviationRule()]
    assert run_rules(rules, Values("dj x feat y", "u.s.a")).artist == "DJ x ft. y"
