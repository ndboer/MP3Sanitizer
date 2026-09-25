"""9a. Afkortingen naar hoofdletters.

- Tokens van losse letters met punten: ``U.s.a`` → ``U.S.A.``, ``u.k.`` → ``U.K.``. De afsluitende
  punt wordt toegevoegd als die ontbreekt, maar nooit dubbel.
- Een instelbare lijst vaste afkortingen (hele woorden, hoofdletterongevoelig): DJ, MC, ABBA, …
- Een uitzonderingslijst voor woorden die niet mogen worden aangepast.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from mp3sanitizer.core.models import Field
from mp3sanitizer.core.rules.base import TextRule

DEFAULT_ABBREVIATIONS: tuple[str, ...] = (
    "DJ",
    "MC",
    "UB40",
    "ABBA",
    "AC/DC",
    "USA",
    "UK",
    "TLC",
    "INXS",
    "KLF",
    "OMD",
    "ELO",
    "XTC",
    "UFO",
)

# Minstens twee losse letters met punten ertussen; niet vast aan andere letters/punten.
_DOTTED = re.compile(r"(?<![\w.])([A-Za-z](?:\.[A-Za-z])+)(\.*)(?![\w])")


class AbbreviationRule(TextRule):
    id = "abbrev"
    label = "Afkortingen naar hoofdletters"

    def __init__(
        self,
        abbreviations: Iterable[str] = DEFAULT_ABBREVIATIONS,
        exceptions: Iterable[str] = (),
    ) -> None:
        self.exceptions = {e.strip().casefold() for e in exceptions if e.strip()}
        words = [a.strip() for a in abbreviations if a.strip()]
        self._canonical = {w.casefold(): w for w in words}
        if words:
            alternatives = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
            self._fixed: re.Pattern[str] | None = re.compile(
                rf"(?<![\w])({alternatives})(?![\w])", re.IGNORECASE
            )
        else:
            self._fixed = None

    def _is_exception(self, token: str) -> bool:
        return (
            token.casefold().rstrip(".") in self.exceptions or token.casefold() in self.exceptions
        )

    def transform(self, text: str, field: Field) -> str:
        def dotted(m: re.Match[str]) -> str:
            token = m.group(0)
            if self._is_exception(token):
                return token
            return m.group(1).upper() + "."

        text = _DOTTED.sub(dotted, text)
        if self._fixed is not None:

            def fixed(m: re.Match[str]) -> str:
                token = m.group(1)
                if self._is_exception(token):
                    return token
                return self._canonical[token.casefold()]

            text = self._fixed.sub(fixed, text)
        return text
