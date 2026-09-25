import pytest

from mp3sanitizer.core.models import ParseStatus
from mp3sanitizer.core.parser import clean_whitespace, parse_filename, split_year


@pytest.mark.parametrize(
    ("stem", "artist", "title", "year", "status"),
    [
        ("Queen - Bohemian Rhapsody (1975)", "Queen", "Bohemian Rhapsody", 1975, ParseStatus.OK),
        ("Queen - Bohemian Rhapsody", "Queen", "Bohemian Rhapsody", None, ParseStatus.NO_YEAR),
        # alleen op de eerste " - " splitsen
        ("A-ha - Take On Me - Live (1986)", "A-ha", "Take On Me - Live", 1986, ParseStatus.OK),
        ("Jay-Z - 99 Problems (2004)", "Jay-Z", "99 Problems", 2004, ParseStatus.OK),
        # dubbele spaties en en-/em-dash
        (
            "Queen  -  Bohemian   Rhapsody (1975)",
            "Queen",
            "Bohemian Rhapsody",
            1975,
            ParseStatus.OK,
        ),
        ("Queen – Innuendo (1991)", "Queen", "Innuendo", 1991, ParseStatus.OK),
        ("Queen — Innuendo (1991)", "Queen", "Innuendo", 1991, ParseStatus.OK),
        # jaar zonder spatie ervoor en met spaties erachter
        ("Queen - Innuendo(1991)  ", "Queen", "Innuendo", 1991, ParseStatus.OK),
        # laatste (dddd) telt; eerdere haakjes horen bij de titel
        ("Prince - 1999 (1999) (1982)", "Prince", "1999 (1999)", 1982, ParseStatus.OK),
        (
            "Queen - We Will Rock You (Live)",
            "Queen",
            "We Will Rock You (Live)",
            None,
            ParseStatus.NO_YEAR,
        ),
    ],
)
def test_parse_ok(stem, artist, title, year, status):
    parsed = parse_filename(stem, upper_year=2027)
    assert (parsed.artist, parsed.title, parsed.year, parsed.status) == (
        artist,
        title,
        year,
        status,
    )


@pytest.mark.parametrize(
    ("stem", "year"),
    [("Queen - Song (1899)", None), ("Queen - Song (2028)", None), ("Queen - Song (2027)", 2027)],
)
def test_year_range(stem, year):
    parsed = parse_filename(stem, upper_year=2027)
    assert parsed.year == year
    if year is None:
        # ongeldig jaar blijft onderdeel van de titel
        assert parsed.title.endswith(")")


@pytest.mark.parametrize(
    ("stem", "title", "year"),
    [
        ("Bohemian Rhapsody (1975)", "Bohemian Rhapsody", 1975),
        ("Queen-Innuendo", "Queen-Innuendo", None),
        ("Queen - ", "Queen -", None),
        (" - Innuendo", "- Innuendo", None),
        ("", "", None),
    ],
)
def test_parse_errors(stem, title, year):
    parsed = parse_filename(stem, upper_year=2027)
    assert parsed.status is ParseStatus.ERROR
    assert parsed.artist == ""
    assert parsed.title == title
    assert parsed.year == year


def test_split_year_default_upper_bound():
    assert split_year("X - Y (1985)") == ("X - Y", 1985)


def test_clean_whitespace():
    assert clean_whitespace("  a \t b  ") == "a b"
