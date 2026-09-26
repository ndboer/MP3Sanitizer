"""Datamodel van Mp3Sanitizer."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Field(StrEnum):
    ARTIST = "artist"
    TITLE = "title"
    YEAR = "year"


type FieldValue = str | int | None


class ParseStatus(StrEnum):
    OK = "ok"
    NO_YEAR = "no_year"
    ERROR = "error"


@dataclass(slots=True)
class AudioInfo:
    """Gegevens uit het bestand zelf; wordt lazy op de achtergrond ingelezen."""

    duration_s: float | None = None
    bitrate_kbps: int | None = None
    size_bytes: int | None = None
    tag_artist: str | None = None
    tag_title: str | None = None
    tag_year: int | None = None
    error: str | None = None


@dataclass(slots=True)
class Track:
    id: int
    path: Path
    root: Path
    parse_status: ParseStatus
    artist: str
    title: str
    year: int | None
    info: AudioInfo | None = None
    copy_number: int | None = None  # '(2)' na het jaar: waarschijnlijk een kopie

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def ext(self) -> str:
        return self.path.suffix

    @property
    def folder(self) -> str:
        """Map relatief t.o.v. de hoofdmap; leeg als het bestand direct in de hoofdmap staat."""
        # Stringvergelijking i.p.v. Path.relative_to: dit wordt per rij vaak aangeroepen.
        parent, root = os.fspath(self.path.parent), os.fspath(self.root)
        if parent == root:
            return ""
        prefix = root if root.endswith(os.sep) else root + os.sep
        return parent[len(prefix) :] if parent.startswith(prefix) else parent

    def original(self, field: Field) -> FieldValue:
        """De waarde zoals geparsed uit de bestandsnaam op schijf."""
        match field:
            case Field.ARTIST:
                return self.artist
            case Field.TITLE:
                return self.title
            case Field.YEAR:
                return self.year


class Collision(StrEnum):
    """Wat te doen als het doelbestand al bestaat of door een ander plan wordt geclaimd."""

    SKIP = "skip"
    SUFFIX = "suffix"
    MARK_DUPLICATE = "mark_duplicate"


class PlanWarning(StrEnum):
    EXISTS = "exists"  # doelbestand bestaat al op schijf
    DUPLICATE_TARGET = "duplicate_target"  # twee tracks krijgen hetzelfde doel
    SUFFIXED = "suffixed"  # botsing opgelost met " (2)"
    CASE_ONLY = "case_only"  # alleen hoofdletters wijzigen (twee-staps-rename)
    PATH_TOO_LONG = "path_too_long"  # > 259 tekens
    INVALID_NAME = "invalid_name"  # ongeldige tekens / leeg / gereserveerd
    TAGS_ONLY = "tags_only"  # naam blijft gelijk, alleen tags bijwerken


@dataclass(frozen=True, slots=True)
class TagValues:
    """Te schrijven tags. ``None`` betekent: tag verwijderen."""

    artist: str | None
    title: str | None
    date: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {"artist": self.artist, "title": self.title, "date": self.date}

    @classmethod
    def from_dict(cls, data: dict[str, str | None]) -> TagValues:
        return cls(data.get("artist"), data.get("title"), data.get("date"))


@dataclass(frozen=True, slots=True)
class RenamePlan:
    track_id: int
    src: Path
    dst: Path
    case_only: bool = False
    warnings: tuple[PlanWarning, ...] = ()
    collision: Collision | None = None  # gekozen afhandeling als er een botsing was
    tags: TagValues | None = None  # tags om te schrijven (None = tags niet aanraken)
    blocked: bool = False  # kan niet worden uitgevoerd (ongeldig of overgeslagen botsing)
    changed: bool = True  # False: niet bewerkt, alleen genormaliseerd/verplaatst
    note: str = ""  # leesbare uitleg van de waarschuwingen

    @property
    def renames(self) -> bool:
        # Als strings vergelijken: WindowsPath-gelijkheid negeert hoofdletters.
        return os.fspath(self.src) != os.fspath(self.dst)


@dataclass(frozen=True, slots=True)
class PendingChange:
    """Eén veldwijziging in het geheugen; ``old`` en ``new`` zijn effectieve waarden."""

    track_id: int
    field: Field
    old: FieldValue
    new: FieldValue
    source: str = "manual"  # "manual" | "bulk" | "swap" | "revert" | "rule:<naam>" | ...
