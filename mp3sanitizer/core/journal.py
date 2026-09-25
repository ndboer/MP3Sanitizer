"""Journaal van uitgevoerde batches (JSON + leesbaar logbestand) en het terugdraaien ervan.

Per batch ontstaan twee bestanden in de journaalmap:

- ``<batch_id>.json``: machineleesbaar, met ``schema_version`` en de appversie
- ``<batch_id>.log``: leesbaar, wordt tijdens het uitvoeren regel voor regel bijgeschreven,
  zodat er na een crash toch een spoor is
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, TextIO

from mp3sanitizer.core import migrations
from mp3sanitizer.core.models import RenamePlan, TagValues
from mp3sanitizer.core.storage import LoadStatus, Migration, load_document, save_document

log = logging.getLogger(__name__)

# 2: appversie per entry (zie migrations.migrate_journal_1_to_2)
JOURNAL_SCHEMA_VERSION = 2
JOURNAL_MIGRATIONS: Mapping[int, Migration] = migrations.JOURNAL


class Op(StrEnum):
    RENAME = "rename"  # zelfde map
    MOVE = "move"  # andere map
    TAG = "tag"
    RMDIR = "rmdir"  # lege map opgeruimd
    TRASH = "trash"  # naar de Prullenbak (herstellen via de Prullenbak zelf)
    DELETE = "delete"  # permanent verwijderd


class Kind(StrEnum):
    SAVE = "save"
    UNDO = "undo"
    DELETE = "delete"  # niet terug te draaien vanuit de app


@dataclass(slots=True)
class JournalEntry:
    op: Op
    src: str
    dst: str
    ok: bool
    error: str | None = None
    track_id: int | None = None
    tags_before: dict[str, str | None] | None = None
    tags_after: dict[str, str | None] | None = None
    app_version: str = ""  # versie die deze bewerking uitvoerde

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["op"] = self.op.value
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> JournalEntry:
        return cls(
            op=Op(data["op"]),
            src=str(data["src"]),
            dst=str(data["dst"]),
            ok=bool(data["ok"]),
            error=data.get("error"),
            track_id=data.get("track_id"),
            tags_before=data.get("tags_before"),
            tags_after=data.get("tags_after"),
            app_version=str(data.get("app_version", "")),
        )


@dataclass(slots=True)
class Journal:
    batch_id: str
    created: str  # ISO 8601, lokale tijd
    app_version: str
    root: str
    kind: Kind = Kind.SAVE
    entries: list[JournalEntry] = field(default_factory=list)
    finished: bool = False
    undoes: str | None = None  # bij kind=undo: de batch die is teruggedraaid
    undone_by: str | None = None  # bij kind=save: de undo-batch die hem terugdraaide

    @property
    def ok_count(self) -> int:
        return sum(1 for e in self.entries if e.ok and e.op in (Op.RENAME, Op.MOVE, Op.TAG))

    @property
    def error_count(self) -> int:
        return sum(1 for e in self.entries if not e.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "created": self.created,
            "app_version": self.app_version,
            "root": self.root,
            "kind": self.kind.value,
            "finished": self.finished,
            "undoes": self.undoes,
            "undone_by": self.undone_by,
            "entries": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Journal:
        return cls(
            batch_id=str(data["batch_id"]),
            created=str(data.get("created", "")),
            app_version=str(data.get("app_version", "onbekend")),
            root=str(data.get("root", "")),
            kind=Kind(data.get("kind", Kind.SAVE)),
            entries=[JournalEntry.from_dict(e) for e in data.get("entries", [])],
            finished=bool(data.get("finished", False)),
            undoes=data.get("undoes"),
            undone_by=data.get("undone_by"),
        )


def new_batch_id(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


class JournalWriter:
    """Houdt het journaal van één batch bij tijdens het uitvoeren."""

    def __init__(self, store: JournalStore, journal: Journal) -> None:
        self.store = store
        self.journal = journal
        self._log: TextIO | None = None

    def __enter__(self) -> JournalWriter:
        self.store.directory.mkdir(parents=True, exist_ok=True)
        self._log = self.store.log_path(self.journal.batch_id).open("a", encoding="utf-8")
        j = self.journal
        self._log.write(
            f"# Mp3Sanitizer {j.app_version} | batch {j.batch_id} | {j.kind.value} | "
            f"{j.created} | hoofdmap {j.root}\n"
        )
        if j.undoes:
            self._log.write(f"# draait batch {j.undoes} terug\n")
        self._log.flush()
        self.store.save(j)  # vroeg wegschrijven: bij een crash staat de batch er al
        return self

    def add(self, entry: JournalEntry) -> None:
        if not entry.app_version:
            entry.app_version = self.journal.app_version
        self.journal.entries.append(entry)
        if self._log is not None:
            status = "OK  " if entry.ok else "FOUT"
            line = f"{datetime.now():%H:%M:%S} {status} {entry.op.value:<6} {entry.src}"
            if entry.dst != entry.src:
                line += f"  ->  {entry.dst}"
            if entry.tags_after:
                line += f"  tags={entry.tags_after}"
            if entry.error:
                line += f"  ({entry.error})"
            self._log.write(line + "\n")
            self._log.flush()

    def __exit__(self, *exc: object) -> None:
        self.journal.finished = True
        j = self.journal
        if self._log is not None:
            self._log.write(f"# klaar: {j.ok_count} gelukt, {j.error_count} fouten\n")
            self._log.close()
            self._log = None
        self.store.save(j)


class JournalStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def json_path(self, batch_id: str) -> Path:
        return self.directory / f"{batch_id}.json"

    def log_path(self, batch_id: str) -> Path:
        return self.directory / f"{batch_id}.log"

    def new(
        self, kind: Kind, root: Path | str, app_version: str, undoes: str | None = None
    ) -> Journal:
        return Journal(
            batch_id=new_batch_id(),
            created=datetime.now().isoformat(timespec="seconds"),
            app_version=app_version,
            root=str(root),
            kind=kind,
            undoes=undoes,
        )

    def writer(self, journal: Journal) -> JournalWriter:
        return JournalWriter(self, journal)

    def save(self, journal: Journal) -> None:
        save_document(self.json_path(journal.batch_id), journal.to_dict(), JOURNAL_SCHEMA_VERSION)

    def load(self, path: Path) -> Journal | None:
        result = load_document(path, JOURNAL_SCHEMA_VERSION, JOURNAL_MIGRATIONS)
        if result.status not in (LoadStatus.OK, LoadStatus.MIGRATED):
            if result.message:
                log.warning(result.message)
            return None
        try:
            journal = Journal.from_dict(result.data)
        except (KeyError, ValueError, TypeError) as exc:
            log.warning("Journaal %s onleesbaar: %s", path.name, exc)
            return None
        if result.status is LoadStatus.MIGRATED:
            self.save(journal)  # eenmalig migreren; de .bak bevat het origineel
        return journal

    def all(self) -> list[Journal]:
        """Alle leesbare journalen, nieuwste eerst."""
        if not self.directory.is_dir():
            return []
        paths = sorted(self.directory.glob("*.json"), reverse=True)
        return [j for p in paths if (j := self.load(p)) is not None]

    def latest_undoable(self) -> Journal | None:
        for journal in self.all():
            if journal.kind is Kind.SAVE and journal.undone_by is None and journal.ok_count:
                return journal
        return None


def undo_plans(journal: Journal) -> list[RenamePlan]:
    """Plannen die de gelukte operaties van een batch in omgekeerde volgorde terugdraaien."""
    # Per eindpad de tags van vóór de batch, zodat die na het terugzetten worden hersteld.
    tags_at: dict[str, TagValues] = {}
    for e in journal.entries:
        if e.ok and e.op is Op.TAG and e.tags_before is not None:
            tags_at[e.dst] = TagValues.from_dict(e.tags_before)

    # Tags op een pad dat ook hernoemd is, worden met die rename meegenomen.
    renamed_to = {e.dst for e in journal.entries if e.ok and e.op in (Op.RENAME, Op.MOVE)}

    plans: list[RenamePlan] = []
    for e in reversed(journal.entries):
        if not e.ok:
            continue
        tid = e.track_id if e.track_id is not None else -1
        if e.op in (Op.RENAME, Op.MOVE):
            plans.append(RenamePlan(tid, Path(e.dst), Path(e.src), tags=tags_at.get(e.dst)))
        elif e.op is Op.TAG and e.dst not in renamed_to and e.dst in tags_at:
            # Alleen tags gewijzigd, geen rename: tags op dezelfde plek herstellen.
            plans.append(RenamePlan(tid, Path(e.dst), Path(e.dst), tags=tags_at[e.dst]))
    return plans
