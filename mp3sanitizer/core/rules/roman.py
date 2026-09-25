"""9d. Romeinse cijfers naar hoofdletters, met bescherming tegen valse positieven.

Alleen losse woorden die een GELDIG Romeins getal vormen komen in aanmerking. Daarnaast moet
minstens één van deze voorwaarden gelden (elk instelbaar):

- de waarde is ten hoogste ``max_value`` (standaard XXXIX = 39);
- het woord volgt op Part, Pt., Vol., Volume, Chapter, Deel of Act;
- het woord staat aan het eind van de titel.

Woorden op de uitzonderingslijst (Mix, Mi, Di, Dim, …) blijven altijd ongewijzigd.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from mp3sanitizer.core.models import Field
from mp3sanitizer.core.rules.base import TextRule

ROMAN = re.compile(r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$", re.IGNORECASE)
DEFAULT_CONTEXT_WORDS: tuple[str, ...] = (
    "Part",
    "Pt.",
    "Vol.",
    "Volume",
    "Chapter",
    "Deel",
    "Act",
)
DEFAULT_EXCEPTIONS: tuple[str, ...] = (
    "Mix",
    "Mi",
    "Di",
    "Dim",
    "Mid",
    "Vic",
    "Liv",
    "Civil",
    "Mild",
    "Did",
    "Lid",
    "Cd",
    "Dc",
)
_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_WORD = re.compile(r"[A-Za-z]+\.?|[^A-Za-z]+")


def is_roman(word: str) -> bool:
    return bool(word) and ROMAN.match(word) is not None


def roman_value(word: str) -> int:
    total = 0
    values = [_VALUES[c] for c in word.upper()]
    for i, v in enumerate(values):
        total += -v if i + 1 < len(values) and values[i + 1] > v else v
    return total


class RomanNumeralRule(TextRule):
    id = "roman"
    label = "Romeinse cijfers naar hoofdletters"

    def __init__(
        self,
        max_value: int | None = 39,
        context_words: Iterable[str] = DEFAULT_CONTEXT_WORDS,
        at_end_of_title: bool = True,
        exceptions: Iterable[str] = DEFAULT_EXCEPTIONS,
    ) -> None:
        self.max_value = max_value
        self.context = {w.strip().rstrip(".").casefold() for w in context_words if w.strip()}
        self.at_end_of_title = at_end_of_title
        self.exceptions = {w.strip().casefold() for w in exceptions if w.strip()}

    def transform(self, text: str, field: Field) -> str:
        tokens = _WORD.findall(text)
        word_indexes = [i for i, t in enumerate(tokens) if t[0].isalpha()]
        last_word = word_indexes[-1] if word_indexes else -1
        previous_word = ""
        for i in word_indexes:
            token = tokens[i]
            word = token.rstrip(".")
            if (
                is_roman(word)
                and word != word.upper()
                and word.casefold() not in self.exceptions
                and self._qualifies(word, previous_word, field, i == last_word)
            ):
                tokens[i] = word.upper() + token[len(word) :]
            previous_word = word
        return "".join(tokens)

    def _qualifies(self, word: str, previous: str, field: Field, is_last: bool) -> bool:
        if self.max_value is not None and roman_value(word) <= self.max_value:
            return True
        if previous.casefold() in self.context:
            return True
        return self.at_end_of_title and field is Field.TITLE and is_last
