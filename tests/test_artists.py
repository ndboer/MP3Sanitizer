import pytest

from mp3sanitizer.core.artists import artist_names, is_collaboration, replace_artist


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("Queen", ["Queen"]),
        ("Queen & David Bowie", ["Queen", "David Bowie"]),
        ("Eminem ft. Dido", ["Eminem", "Dido"]),
        ("Eminem feat Dido", ["Eminem", "Dido"]),
        ("Jay-Z featuring Rihanna, Kanye West", ["Jay-Z", "Rihanna", "Kanye West"]),
        ("Queen vs. David Bowie", ["Queen", "David Bowie"]),
        ("A x B", ["A", "B"]),
        ("Tiësto with Ava Max", ["Tiësto", "Ava Max"]),
        ("Andre Hazes en Wolter Kroes", ["Andre Hazes", "Wolter Kroes"]),
        ("Beatles, The", ["Beatles, The"]),  # lidwoord achter komma hoort erbij
        ("Beatles, The & Billy Preston", ["Beatles, The", "Billy Preston"]),
        ("AC/DC", ["AC/DC"]),
        ("Axwell", ["Axwell"]),  # 'x' alleen als los woord
        ("Brandy", ["Brandy"]),  # 'and' alleen als los woord
        ("Kenny G", ["Kenny G"]),
    ],
)
def test_split(text, names):
    assert artist_names(text) == names


def test_is_collaboration():
    assert is_collaboration("Queen & David Bowie")
    assert not is_collaboration("Beatles, The")


@pytest.mark.parametrize(
    ("text", "old", "new", "expected"),
    [
        ("queen & David Bowie", "queen", "Queen", "Queen & David Bowie"),
        ("Eminem ft. dido", "dido", "Dido", "Eminem ft. Dido"),
        ("David Bowie & queen", "queen", "Queen", "David Bowie & Queen"),
        ("queen", "queen", "Queen", "Queen"),  # hele veld
        (
            "Queen & David Bowie",
            "Queen & David Bowie",
            "Queen, David Bowie",
            "Queen, David Bowie",
        ),  # hele veld als samenwerking
        ("A & a", "a", "X", "A & X"),  # exacte schrijfwijze, niet hoofdletterongevoelig
        ("Beatles & Beatles", "Beatles", "The Beatles", "The Beatles & The Beatles"),
        (
            "Beatles, The & Billy Preston",
            "Beatles, The",
            "The Beatles",
            "The Beatles & Billy Preston",
        ),
    ],
)
def test_replace_only_that_artist(text, old, new, expected):
    assert replace_artist(text, old, new) == expected


def test_replace_absent_returns_none():
    assert replace_artist("Queen & David Bowie", "Freddie", "X") is None
    assert replace_artist("Queensryche", "Queen", "X") is None  # geen deel van een woord


@pytest.mark.parametrize(
    ("text", "old", "new", "expected"),
    [
        ("adam and the ants", "adam", "Adam and the Ants", "Adam and the Ants"),
        ("adam and the ants", "the ants", "Adam and the Ants", "Adam and the Ants"),
        ("Simon and Garfunkel", "Simon", "Simon & Garfunkel", "Simon & Garfunkel"),
        ("Earth, Wind and Fire", "Earth", "Earth, Wind & Fire", "Earth, Wind & Fire"),
        ("Quien & David Bowie", "Quien", "Queen", "Queen & David Bowie"),
    ],
)
def test_new_name_covering_whole_field_replaces_everything(text, old, new, expected):
    assert replace_artist(text, old, new, ["The"]) == expected


@pytest.mark.parametrize(
    ("text", "old", "new", "expected"),
    [
        (
            "Billy Cotton & His Band, Alan Breeze",
            "Billy Cotton",
            "Billy Cotton & His Band",
            "Billy Cotton & His Band, Alan Breeze",
        ),
        (
            "Alan Breeze & Billy Cotton & His Band",
            "His Band",
            "Billy Cotton and His Band",
            "Alan Breeze & Billy Cotton and His Band",
        ),
        ("Queen & David Bowie & Queen", "Queen", "QUEEN", "QUEEN & David Bowie & QUEEN"),
    ],
)
def test_new_name_covering_adjacent_parts_replaces_that_span(text, old, new, expected):
    assert replace_artist(text, old, new, ["The"]) == expected
