import pytest

from mp3sanitizer.core.models import Field
from mp3sanitizer.core.rules.base import Context, Values
from mp3sanitizer.core.rules.casing import (
    ArticlePosition,
    ArticleRule,
    SpacingRule,
    TitleCaseRule,
    YearFromTagRule,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("the long and winding road", "The Long and Winding Road"),
        ("THE LONG AND WINDING ROAD", "The Long and Winding Road"),
        ("in the air tonight", "In the Air Tonight"),
        ("hotel california (live at the forum)", "Hotel California (Live at the Forum)"),
        ("born in the U.S.A.", "Born in the U.S.A."),
        ("paul McCartney", "Paul McCartney"),
        ("rocky IV", "Rocky IV"),
        ("dj shadow", "Dj Shadow"),  # 'DJ' zet de afkortingsregel goed
        ("DJ shadow", "DJ Shadow"),
        ("don't stop me now", "Don't Stop Me Now"),
        ("a-ha - take on me", "A-ha - Take on Me"),
        ("de dijk - mag het licht uit", "De Dijk - Mag het Licht Uit"),
        ("99 red balloons", "99 Red Balloons"),
        ("ABBA", "ABBA"),
        ("iPod song", "iPod Song"),
    ],
)
def test_title_case(text, expected):
    assert TitleCaseRule().transform(text, Field.TITLE) == expected


def test_title_case_idempotent():
    rule = TitleCaseRule()
    once = rule.transform("the long and winding road (live in the u.k.)", Field.TITLE)
    assert rule.transform(once, Field.TITLE) == once


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  Queen  ", "Queen"),
        ("A  -B", "A - B"),
        ("A-  B", "A - B"),
        ("A-ha", "A-ha"),
        ("Song( Live )", "Song (Live)"),
        ("Song [ Remix]", "Song [Remix]"),
        ("Song  (Live)", "Song (Live)"),
        ("((x))", "((x))"),
    ],
)
def test_spacing(text, expected):
    assert SpacingRule().transform(text, Field.TITLE) == expected


def test_year_from_tag():
    rule = YearFromTagRule()
    assert rule.apply(Values("A", "B", None), Context(tag_year=1985)).year == 1985
    assert rule.apply(Values("A", "B", 1990), Context(tag_year=1985)).year == 1990
    assert rule.apply(Values("A", "B", None), Context(tag_year=1066)).year is None
    assert rule.apply(Values("A", "B", None), Context()).year is None


@pytest.mark.parametrize(
    ("position", "text", "expected"),
    [
        (ArticlePosition.FRONT, "Beatles, The", "The Beatles"),
        (ArticlePosition.FRONT, "Dijk, De", "De Dijk"),
        (ArticlePosition.FRONT, "The Beatles", "The Beatles"),
        (ArticlePosition.BACK, "The Beatles", "Beatles, The"),
        (ArticlePosition.BACK, "Beatles, The", "Beatles, The"),
        (ArticlePosition.BACK, "Theo Maassen", "Theo Maassen"),
        (ArticlePosition.BACK, "The", "The"),
        (ArticlePosition.BACK, "Earth, Wind & Fire", "Earth, Wind & Fire"),
    ],
)
def test_article_position(position, text, expected):
    assert ArticleRule(position).transform(text, Field.ARTIST) == expected


def test_article_rule_only_touches_artist():
    out = ArticleRule(ArticlePosition.BACK).apply(Values("The Who", "The Seeker"), Context())
    assert (out.artist, out.title) == ("Who, The", "The Seeker")


def test_article_uses_canonical_case():
    assert (
        ArticleRule(ArticlePosition.FRONT).transform("beatles, the", Field.ARTIST) == "The beatles"
    )
    assert (
        ArticleRule(ArticlePosition.BACK).transform("the beatles", Field.ARTIST) == "beatles, The"
    )
