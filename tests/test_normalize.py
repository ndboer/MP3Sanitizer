import pytest

from mp3sanitizer.core.normalize import (
    fold,
    loose_equal,
    match_key,
    sort_key,
    strip_article,
    strip_diacritics,
)


def test_strip_diacritics():
    assert strip_diacritics("Beyoncé") == "Beyonce"
    assert strip_diacritics("Motörhead") == "Motorhead"
    assert strip_diacritics("Sigur Rós") == "Sigur Ros"


def test_fold():
    assert fold("  BeYoncé  Knowles ") == "beyonce knowles"
    assert fold("STRASSE") == fold("straße")


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("The Beatles", "beatles"),
        ("Beatles, The", "beatles"),
        ("Beatles", "beatles"),
        ("De Dijk", "dijk"),
        ("Die Toten Hosen", "toten hosen"),
        ("Les Negresses Vertes", "negresses vertes"),
        ("The", "the"),  # alleen een lidwoord blijft staan
        ("Theo Maassen", "theo maassen"),  # geen los woord
        ("Lady Gaga", "lady gaga"),
    ],
)
def test_sort_key(name, key):
    assert sort_key(name) == key


def test_sort_key_orders_the_beatles_under_b():
    names = ["Queen", "The Beatles", "ABBA", "Beatles, The", "Coldplay"]
    assert sorted(names, key=sort_key) == [
        "ABBA",
        "The Beatles",
        "Beatles, The",
        "Coldplay",
        "Queen",
    ]


def test_custom_articles():
    assert strip_article("the beatles", ["De"]) == "the beatles"
    assert sort_key("Het Goede Doel", ["Het"]) == "goede doel"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Simon & Garfunkel", "Simon and Garfunkel"),
        ("Simon & Garfunkel", "Simon en Garfunkel"),
        ("Simon & Garfunkel", "Simon+Garfunkel"),
        ("Beyoncé", "BEYONCE"),
        ("The Beatles", "Beatles, The"),
        ("AC/DC", "AC DC"),
        ("Guns N' Roses", "Guns N Roses"),
        ("Earth,  Wind & Fire", "Earth Wind and Fire"),
    ],
)
def test_match_key_equal(a, b):
    assert match_key(a) == match_key(b)


def test_match_key_keeps_words_containing_and():
    assert match_key("Andrea Bocelli") == "andrea bocelli"
    assert match_key("Brandy") == "brandy"


def test_loose_equal():
    assert loose_equal("Don’t Stop", "don't  stop")
    assert not loose_equal("Queen", "Queens")
    assert loose_equal(None, None)
    assert not loose_equal("x", None)
