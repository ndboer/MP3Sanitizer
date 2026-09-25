"""Batches uitvoeren met journaal: opslaan en de laatste batch terugdraaien."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from mp3sanitizer.core.executor import ExecResult, execute
from mp3sanitizer.core.journal import Journal, JournalStore, Kind, undo_plans
from mp3sanitizer.core.models import RenamePlan

Progress = Callable[[int, int], None]
Cancelled = Callable[[], bool]


def run_save(
    plans: Sequence[RenamePlan],
    store: JournalStore,
    root: Path,
    app_version: str,
    *,
    cleanup_empty_dirs: bool = False,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> tuple[ExecResult, Journal]:
    journal = store.new(Kind.SAVE, root, app_version)
    with store.writer(journal) as writer:
        result = execute(
            plans,
            writer,
            cleanup_root=root if cleanup_empty_dirs else None,
            progress=progress,
            cancelled=cancelled,
        )
    return result, journal


def run_undo(
    target: Journal,
    store: JournalStore,
    app_version: str,
    *,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> tuple[ExecResult, Journal]:
    """Draai een batch terug. Werkt ook voor journalen van oudere appversies (via migraties)."""
    journal = store.new(Kind.UNDO, target.root, app_version, undoes=target.batch_id)
    with store.writer(journal) as writer:
        result = execute(undo_plans(target), writer, progress=progress, cancelled=cancelled)
    if not result.cancelled:
        target.undone_by = journal.batch_id
        store.save(target)
    return result, journal
