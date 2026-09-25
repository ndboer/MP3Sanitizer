from datetime import date

import pytest

from mp3sanitizer.core.normalize import natural_key
from mp3sanitizer.core.parser import format_stem, parse_filename
from mp3sanitizer.core.validate import (
    Issue,
    YearError,
    invalid_chars,
    is_reserved_name,
    parse_year_input,
    stem_issues,
    text_issues,
)


@pytest.mark.parametrize("text", ["AC/DC", 'Say "Hi"', "What?", "A|B", "x:y", "a*", "<b>", "a\\b"])
def test_invalid_chars(text):
    assert invalid_chars(text)
    assert Issue.INVALID_CHARS in text_issues(text)


def test_control_chars_are_invalid():
    assert invalid_chars("a\tb") == {"\t"}


def test_valid_text():
    assert text_issues("Guns N' Roses") == ()
    assert text_issues("Beyoncé (Live) [Remix] & Co.") == ()


def test_empty():
    assert text_issues("   ") == (Issue.EMPTY,)


@pytest.mark.parametrize("name", ["CON", "con", "Nul", "COM1", "lpt9", "AUX.txt", "PRN "])
def test_reserved(name):
    assert is_reserved_name(name)
    assert Issue.RESERVED_NAME in stem_issues(name)


@pytest.mark.parametrize("name", ["CONTROL", "NUL - Song", "COM10", "Console"])
def test_not_reserved(name):
    assert not is_reserved_name(name)


def test_reserved_only_checked_on_full_stem():
    assert text_issues("NUL") == ()


def test_parse_year_input():
    assert parse_year_input("") is None
    assert parse_year_input(" 1985 ") == 1985
    assert parse_year_input(str(date.today().year + 1)) == date.today().year + 1
    for bad in ["19a5", "1899", str(date.today().year + 2), "-1985", "١٩٨٥", "85.0"]:
        with pytest.raises(YearError):
            parse_year_input(bad)


@pytest.mark.parametrize(
    ("artist", "title", "year"),
    [("Queen", "Innuendo", 1991), ("Queen", "Innuendo", None), ("A-ha", "Take On Me - Live", 1986)],
)
def test_format_stem_roundtrip(artist, title, year):
    parsed = parse_filename(format_stem(artist, title, year))
    assert (parsed.artist, parsed.title, parsed.year) == (artist, title, year)


def test_format_stem_without_artist():
    assert format_stem("", "Iets", None) == "Iets"


def test_natural_key():
    names = ["song 10", "song 9", "song 100", "song", "10 years", "9 lives", "song 9b"]
    assert sorted(names, key=natural_key) == [
        "9 lives",
        "10 years",
        "song",
        "song 9",
        "song 9b",
        "song 10",
        "song 100",
    ]
