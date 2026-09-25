"""Achtergrondtaken via ``QThreadPool`` + ``QRunnable`` met signals."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from mp3sanitizer.core.batch import run_save, run_undo
from mp3sanitizer.core.deleter import DeleteItem, Trash, delete_files
from mp3sanitizer.core.journal import Journal, JournalStore
from mp3sanitizer.core.models import AudioInfo, RenamePlan, Track
from mp3sanitizer.core.scanner import iter_audio_files, track_from_path
from mp3sanitizer.core.tags import read_audio_info

log = logging.getLogger(__name__)

BATCH_INTERVAL_S = 0.2
# Kleine batches houden de UI-thread per verwerkingsslag kort.
MAX_SCAN_BATCH = 1000


class WorkerSignals(QObject):
    progress = Signal(int, int)  # gedaan, totaal (-1 = onbekend)
    batch = Signal(object)  # deelresultaat, zodat de UI al kan bijwerken
    error = Signal(str)
    finished = Signal(bool)  # True als geannuleerd


class Worker(QRunnable):
    """Basisklasse. Subklassen implementeren ``work`` en controleren ``cancelled`` regelmatig."""

    def __init__(self) -> None:
        super().__init__()
        # De eigenaar houdt een referentie vast tot ``finished``; Qt mag het object niet opruimen.
        self.setAutoDelete(False)
        self.signals = WorkerSignals()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> None:
        try:
            self.work()
        except Exception as exc:
            log.exception("Fout in %s", type(self).__name__)
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit(self.cancelled)

    def work(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


class ScanWorker(Worker):
    """Scant de hoofdmap en parse de bestandsnamen. Levert ``list[Track]`` in batches."""

    def __init__(self, root: Path, extensions: Iterable[str]) -> None:
        super().__init__()
        self.root = root
        self.extensions = list(extensions)

    def work(self) -> None:
        batch: list[Track] = []
        count = 0
        last = time.monotonic()
        for path in iter_audio_files(self.root, self.extensions, lambda: self.cancelled):
            if self.cancelled:
                break
            batch.append(track_from_path(count, path, self.root))
            count += 1
            if len(batch) >= MAX_SCAN_BATCH or time.monotonic() - last >= BATCH_INTERVAL_S:
                self.signals.batch.emit(batch)
                self.signals.progress.emit(count, -1)
                batch = []
                last = time.monotonic()
        if batch:
            self.signals.batch.emit(batch)
        self.signals.progress.emit(count, -1)
        log.info("Scan van %s: %d bestanden", self.root, count)


class TagWorker(Worker):
    """Leest tags, duur en bitrate. Levert ``list[tuple[int, AudioInfo]]`` in batches."""

    def __init__(self, items: Sequence[tuple[int, Path]]) -> None:
        super().__init__()
        self.items = list(items)

    def work(self) -> None:
        total = len(self.items)
        batch: list[tuple[int, AudioInfo]] = []
        last = time.monotonic()
        for done, (track_id, path) in enumerate(self.items, start=1):
            if self.cancelled:
                break
            batch.append((track_id, read_audio_info(path)))
            if time.monotonic() - last >= BATCH_INTERVAL_S:
                self.signals.batch.emit(batch)
                self.signals.progress.emit(done, total)
                batch = []
                last = time.monotonic()
        if batch:
            self.signals.batch.emit(batch)
        self.signals.progress.emit(total if not self.cancelled else 0, total)


class SaveWorker(Worker):
    """Voert een opslaan-batch uit. ``batch`` levert ``(ExecResult, Journal)``."""

    def __init__(
        self,
        plans: Sequence[RenamePlan],
        store: JournalStore,
        root: Path,
        app_version: str,
        cleanup_empty_dirs: bool,
    ) -> None:
        super().__init__()
        self.plans = list(plans)
        self.store = store
        self.root = root
        self.app_version = app_version
        self.cleanup_empty_dirs = cleanup_empty_dirs

    def work(self) -> None:
        result = run_save(
            self.plans,
            self.store,
            self.root,
            self.app_version,
            cleanup_empty_dirs=self.cleanup_empty_dirs,
            progress=self.signals.progress.emit,
            cancelled=lambda: self.cancelled,
        )
        self.signals.batch.emit(result)


class UndoWorker(Worker):
    """Draait een batch terug. ``batch`` levert ``(ExecResult, Journal)``."""

    def __init__(self, target: Journal, store: JournalStore, app_version: str) -> None:
        super().__init__()
        self.target = target
        self.store = store
        self.app_version = app_version

    def work(self) -> None:
        result = run_undo(
            self.target,
            self.store,
            self.app_version,
            progress=self.signals.progress.emit,
            cancelled=lambda: self.cancelled,
        )
        self.signals.batch.emit(result)


class DeleteWorker(Worker):
    """Verwijdert bestanden. ``batch`` levert ``(DeleteResult, Journal)``."""

    def __init__(
        self,
        items: Sequence[DeleteItem],
        store: JournalStore,
        root: Path,
        app_version: str,
        permanent: bool,
        trash: Trash | None = None,
    ) -> None:
        super().__init__()
        self.items = list(items)
        self.store = store
        self.root = root
        self.app_version = app_version
        self.permanent = permanent
        self.trash = trash

    def work(self) -> None:
        kwargs = {"trash": self.trash} if self.trash is not None else {}
        result = delete_files(
            self.items,
            self.store,
            self.root,
            self.app_version,
            permanent=self.permanent,
            progress=self.signals.progress.emit,
            cancelled=lambda: self.cancelled,
            **kwargs,
        )
        self.signals.batch.emit(result)
