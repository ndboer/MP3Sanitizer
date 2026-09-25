"""Validatie van velden en bestandsnamen (met Windows als strengste doelplatform)."""

from __future__ import annotations

import re
from enum import StrEnum

from mp3sanitizer.core.parser import MIN_YEAR, max_year

INVALID_CHARS = frozenset('<>:"/\\|?*')
_CONTROL = re.compile(r"[\x00-\x1f]")
RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)


class Issue(StrEnum):
    EMPTY = "empty"
    INVALID_CHARS = "invalid_chars"
    RESERVED_NAME = "reserved_name"

    @property
    def message(self) -> str:
        return _MESSAGES[self]


_MESSAGES = {
    Issue.EMPTY: "Mag niet leeg zijn",
    Issue.INVALID_CHARS: 'Bevat tekens die Windows niet toestaat: < > : " / \\ | ? *',
    Issue.RESERVED_NAME: "Is een gereserveerde Windows-naam (CON, NUL, COM1, ...)",
}


def invalid_chars(text: str) -> set[str]:
    found = {ch for ch in text if ch in INVALID_CHARS}
    found.update(_CONTROL.findall(text))
    return found


def is_reserved_name(text: str) -> bool:
    """Windows weigert o.a. 'CON', 'con.txt' en 'NUL ' als bestandsnaam."""
    stem = text.split(".", 1)[0].strip().upper()
    return stem in RESERVED_NAMES


def text_issues(text: str) -> tuple[Issue, ...]:
    """Problemen met een artiest of titel als onderdeel van een bestandsnaam.

    Gereserveerde namen worden hier niet gecontroleerd: 'NUL - Song.mp3' is prima; alleen een
    volledige bestandsnaam 'NUL.mp3' is ongeldig (zie ``stem_issues``).
    """
    issues: list[Issue] = []
    if not text.strip():
        issues.append(Issue.EMPTY)
    if invalid_chars(text):
        issues.append(Issue.INVALID_CHARS)
    return tuple(issues)


def stem_issues(stem: str) -> tuple[Issue, ...]:
    """Problemen met een volledige bestandsnaam (zonder extensie) of mapnaam."""
    issues = list(text_issues(stem))
    if is_reserved_name(stem):
        issues.append(Issue.RESERVED_NAME)
    return tuple(issues)


class YearError(ValueError):
    pass


def parse_year_input(text: str) -> int | None:
    """Zet gebruikersinvoer om naar een jaar. Leeg betekent 'geen jaar'.

    Raises:
        YearError: als de invoer niet numeriek is of buiten het bereik valt.
    """
    text = text.strip()
    if not text:
        return None
    if not text.isdigit() or not text.isascii():
        raise YearError(f"'{text}' is geen jaartal")
    year = int(text)
    upper = max_year()
    if not MIN_YEAR <= year <= upper:
        raise YearError(f"Jaar moet tussen {MIN_YEAR} en {upper} liggen")
    return year
