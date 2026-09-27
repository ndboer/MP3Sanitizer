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
