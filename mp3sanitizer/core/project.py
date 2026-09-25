"""Sessie/projectbestand: niet-opgeslagen wijzigingen bewaren en later weer laden.

Formaat (JSON, ``schema_version``)::

    {
      "schema_version": 1,
      "app_version": "0.9.0",
      "saved": "2026-09-25T20:15:00",
      "root": "D:\\Muziek",
      "changes": [
        {"path": "1985\\A-ha - Take On Me.mp3", "fields": {"year": 1985}},
        ...
      ]
    }

Paden zijn relatief t.o.v. de hoofdmap; bij het laden wordt hoofdletterongevoelig vergeleken.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mp3sanitizer.core import migrations
from mp3sanitizer.core.models import Field, FieldValue, PendingChange
from mp3sanitizer.core.storage import LoadStatus, Migration, load_document, save_document

PROJECT_SCHEMA_VERSION = 1
PROJECT_MIGRATIONS: Mapping[int, Migration] = migrations.PROJECT
PROJECT_SUFFIX = ".mp3s.json"


class ProjectError(Exception):
    pass


@dataclass(slots=True)
class ProjectEntry:
    path: str  # relatief t.o.v. de hoofdmap
    fields: dict[Field, FieldValue] = field(default_factory=dict)


@dataclass(slots=True)
class Project:
    root: str
    entries: list[ProjectEntry]
    app_version: str = ""
    saved: str = ""


def _key(rel: str) -> str:
    return os.path.normcase(rel.replace("/", os.sep)).casefold()


def save_project(path: Path, root: Path, app_version: str, entries: Iterable[ProjectEntry]) -> int:
    changes = [
        {"path": e.path, "fields": {f.value: v for f, v in e.fields.items()}}
        for e in entries
        if e.fields
    ]
    save_document(
        path,
        {
            "app_version": app_version,
            "saved": datetime.now().isoformat(timespec="seconds"),
            "root": str(root),
            "changes": changes,
        },
        PROJECT_SCHEMA_VERSION,
    )
    return len(changes)


def load_project(path: Path) -> Project:
    """Raises ``ProjectError`` met een leesbare melding (corrupt, nieuwer, ontbreekt)."""
    result = load_document(path, PROJECT_SCHEMA_VERSION, PROJECT_MIGRATIONS)
    if result.status is LoadStatus.MISSING:
        raise ProjectError(f"{path.name} bestaat niet")
    if result.status in (LoadStatus.CORRUPT, LoadStatus.NEWER):
        raise ProjectError(result.message or f"{path.name} is niet te laden")
    data: dict[str, Any] = result.data
    entries = []
    for item in data.get("changes", []):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        fields: dict[Field, FieldValue] = {}
        for name, value in (item.get("fields") or {}).items():
            try:
                f = Field(name)
            except ValueError:
                continue
            if f is Field.YEAR:
                if value is None or (isinstance(value, int) and not isinstance(value, bool)):
                    fields[f] = value
            elif isinstance(value, str):
                fields[f] = value
        entries.append(ProjectEntry(item["path"], fields))
    root = data.get("root")
    if not isinstance(root, str) or not root:
        raise ProjectError(f"{path.name} bevat geen hoofdmap")
    return Project(root, entries, str(data.get("app_version", "")), str(data.get("saved", "")))


@dataclass(slots=True)
class MatchResult:
    changes: list[PendingChange]
    unmatched: list[str]


def match_project(
    project: Project,
    tracks: Iterable[tuple[int, str]],
    current: Mapping[int, Mapping[Field, FieldValue]],
) -> MatchResult:
    """Koppel projectregels aan tracks (``(track_id, relatief pad)``).

    ``current`` geeft per track-id de huidige (effectieve) waarden, zodat ``old`` klopt.
    """
    by_path = {_key(rel): tid for tid, rel in tracks}
    changes: list[PendingChange] = []
    unmatched: list[str] = []
    for entry in project.entries:
        tid = by_path.get(_key(entry.path))
        if tid is None:
            unmatched.append(entry.path)
            continue
        for f, value in entry.fields.items():
            old = current[tid][f]
            if old != value:
                changes.append(PendingChange(tid, f, old, value, "project"))
    return MatchResult(changes, unmatched)
