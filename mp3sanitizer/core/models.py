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


@dataclass(frozen=True, slots=True)
class PendingChange:
    """Eén veldwijziging in het geheugen; ``old`` en ``new`` zijn effectieve waarden."""

    track_id: int
    field: Field
    old: FieldValue
    new: FieldValue
    source: str = "manual"  # "manual" | "bulk" | "swap" | "revert" | "rule:<naam>" | ...
