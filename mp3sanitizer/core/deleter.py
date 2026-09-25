"""Bestanden verwijderen: standaard naar de Prullenbak (send2trash), permanent alleen expliciet.

Elke verwijdering komt in het journaal (soort ``delete``). Zo'n batch is niet terug te draaien
vanuit de app; bestanden in de Prullenbak herstel je via de Prullenbak zelf.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from send2trash import send2trash

from mp3sanitizer.core.journal import Journal, JournalEntry, JournalStore, Kind, Op

log = logging.getLogger(__name__)

Trash = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class DeleteItem:
    track_id: int
    path: Path


@dataclass(slots=True)
class DeleteResult:
    deleted: list[int] = field(default_factory=list)  # track-ids
    failures: list[tuple[int, Path, str]] = field(default_factory=list)
    cancelled: bool = False


def delete_files(
    items: Sequence[DeleteItem],
    store: JournalStore,
    root: Path | str,
    app_version: str,
    *,
    permanent: bool = False,
    trash: Trash = send2trash,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[DeleteResult, Journal]:
    """Verwijder bestanden. Een fout bij één bestand stopt de rest niet."""
    result = DeleteResult()
    journal = store.new(Kind.DELETE, root, app_version)
    op = Op.DELETE if permanent else Op.TRASH
    total = len(items)
    with store.writer(journal) as writer:
        for i, item in enumerate(items):
            if progress is not None:
                progress(i, total)
            if cancelled is not None and cancelled():
                result.cancelled = True
                break
            path = os.fspath(item.path)
            try:
                if not os.path.lexists(path):
                    raise FileNotFoundError(f"bestaat niet (meer): {path}")
                if permanent:
                    os.remove(path)
                else:
                    trash(path)
            except Exception as exc:  # send2trash gooit eigen exceptietypes per platform
                msg = str(exc) or type(exc).__name__
                log.warning("Verwijderen mislukt: %s (%s)", path, msg)
                result.failures.append((item.track_id, item.path, msg))
                writer.add(JournalEntry(op, path, path, False, msg, item.track_id))
            else:
                result.deleted.append(item.track_id)
                writer.add(JournalEntry(op, path, path, True, track_id=item.track_id))
        if progress is not None:
            progress(total, total)
    return result, journal
