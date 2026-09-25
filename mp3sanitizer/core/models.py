"""Datamodel van Mp3Sanitizer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Field(StrEnum):
    ARTIST = "artist"
    TITLE = "title"
    YEAR = "year"


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
        try:
            rel = self.path.parent.relative_to(self.root)
        except ValueError:
            return str(self.path.parent)
        return "" if rel == Path(".") else str(rel)
