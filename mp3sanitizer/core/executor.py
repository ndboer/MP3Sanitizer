"""Voert rename-plannen uit op schijf en schrijft alles in het journaal.

Veiligheidsregels:

- Nooit overschrijven: bestaat het doel al, dan wordt die track overgeslagen en gemeld.
- Elke track apart in try/except; een fout stopt de batch niet.
- Case-only renames en plannen waarvan de bron het doel van een ander plan is (A→B terwijl
  B→C, of A↔B), gaan in twee stappen via een tijdelijke naam.
- Na annuleren worden tijdelijke namen teruggezet.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mp3sanitizer.core.journal import JournalEntry, JournalWriter, Op
from mp3sanitizer.core.models import RenamePlan, TagValues
from mp3sanitizer.core.planner import path_key
from mp3sanitizer.core.tags import TagWriteError, write_tags

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Moved:
    track_id: int
    src: Path
    dst: Path


@dataclass(frozen=True, slots=True)
class Failure:
    track_id: int
    path: Path
    message: str


@dataclass(slots=True)
class ExecResult:
    moved: list[Moved] = field(default_factory=list)
    tagged: dict[int, TagValues] = field(default_factory=dict)
    failures: list[Failure] = field(default_factory=list)
    removed_dirs: list[Path] = field(default_factory=list)
    cancelled: bool = False


def _temp_name(src: Path, batch_id: str, index: int) -> Path:
    return src.with_name(f"~mp3s-{batch_id[-6:]}-{index}{src.suffix}")


def _move(source: Path, dst: Path) -> None:
    """Verplaats zonder te overschrijven."""
    if os.path.lexists(dst):
        raise FileExistsError(f"doel bestaat al: {dst}")
    if path_key(source.parent) == path_key(dst.parent):
        os.rename(source, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(os.fspath(source), os.fspath(dst))


def execute(
    plans: Sequence[RenamePlan],
    writer: JournalWriter,
    *,
    cleanup_root: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ExecResult:
    """Voer de (niet-geblokkeerde) plannen uit. ``cleanup_root``: lege mappen opruimen tot hier."""
    plans = [p for p in plans if not p.blocked]
    result = ExecResult()
    total = len(plans)
    batch_id = writer.journal.batch_id
    is_cancelled = cancelled or (lambda: False)

    # Welke plannen hebben een tijdelijke naam nodig?
    dst_keys: dict[str, int] = {}
    for i, p in enumerate(plans):
        if p.renames:
            dst_keys[path_key(p.dst)] = i
    needs_temp = [
        p.renames
        and (
            path_key(p.src) == path_key(p.dst)  # alleen hoofdletters
            or dst_keys.get(path_key(p.src), i) != i  # bron is doel van een ander plan
        )
        for i, p in enumerate(plans)
    ]

    # Stap 1: tijdelijke namen.
    temp: dict[int, Path] = {}
    for i, p in enumerate(plans):
        if not needs_temp[i]:
            continue
        tmp = _temp_name(p.src, batch_id, i)
        try:
            if os.path.lexists(tmp):
                raise FileExistsError(f"tijdelijke naam bestaat al: {tmp}")
            os.rename(p.src, tmp)
            temp[i] = tmp
        except OSError as exc:
            _fail(result, writer, p, Op.RENAME, f"tijdelijke naam mislukt: {exc}")

    # Stap 2: naar het doel.
    old_dirs: set[Path] = set()
    for i, p in enumerate(plans):
        if progress is not None:
            progress(i, total)
        if needs_temp[i] and i not in temp:  # stap 1 mislukte al (en is gemeld)
            continue
        if is_cancelled():
            result.cancelled = True
            _restore_temps(plans, temp, range(i, total), result, writer)
            break
        final = p.src
        if p.renames:
            source = temp.get(i, p.src)
            op = Op.RENAME if path_key(p.src.parent) == path_key(p.dst.parent) else Op.MOVE
            try:
                _move(source, p.dst)
            except OSError as exc:
                _fail(result, writer, p, op, str(exc))
                if i in temp:
                    _restore_temps(plans, temp, [i], result, writer)
                continue
            final = p.dst
            result.moved.append(Moved(p.track_id, p.src, p.dst))
            writer.add(JournalEntry(op, str(p.src), str(p.dst), True, track_id=p.track_id))
            if op is Op.MOVE:
                old_dirs.add(p.src.parent)
        if p.tags is not None:
            try:
                before = write_tags(final, p.tags)
            except TagWriteError as exc:
                result.failures.append(Failure(p.track_id, final, str(exc)))
                writer.add(
                    JournalEntry(Op.TAG, str(final), str(final), False, str(exc), p.track_id)
                )
            else:
                result.tagged[p.track_id] = p.tags
                writer.add(
                    JournalEntry(
                        Op.TAG,
                        str(final),
                        str(final),
                        True,
                        track_id=p.track_id,
                        tags_before=before.to_dict(),
                        tags_after=p.tags.to_dict(),
                    )
                )
    if progress is not None:
        progress(total, total)

    if cleanup_root is not None:
        result.removed_dirs = _remove_empty_dirs(old_dirs, cleanup_root, writer)
    return result


def _fail(result: ExecResult, writer: JournalWriter, p: RenamePlan, op: Op, msg: str) -> None:
    log.warning("Mislukt: %s -> %s: %s", p.src, p.dst, msg)
    result.failures.append(Failure(p.track_id, p.src, msg))
    writer.add(JournalEntry(op, str(p.src), str(p.dst), False, msg, p.track_id))


def _restore_temps(
    plans: Sequence[RenamePlan],
    temp: dict[int, Path],
    indexes: Sequence[int] | range,
    result: ExecResult,
    writer: JournalWriter,
) -> None:
    """Zet tijdelijke namen terug naar de oorspronkelijke naam."""
    for i in indexes:
        tmp = temp.pop(i, None)
        if tmp is None:
            continue
        p = plans[i]
        try:
            os.rename(tmp, p.src)
        except OSError as exc:
            # Het bestand staat nog onder de tijdelijke naam; leg dat vast zodat
            # 'Laatste batch terugdraaien' het kan herstellen.
            msg = f"staat nog onder tijdelijke naam {tmp.name}: {exc}"
            result.failures.append(Failure(p.track_id, tmp, msg))
            writer.add(JournalEntry(Op.RENAME, str(p.src), str(tmp), True, msg, p.track_id))


def _remove_empty_dirs(dirs: set[Path], root: Path, writer: JournalWriter) -> list[Path]:
    removed: list[Path] = []
    prefix = path_key(root).rstrip("\\/") + os.sep
    # Diepste mappen eerst, zodat een lege ouder daarna ook weg kan. De hoofdmap zelf en alles
    # daarbuiten blijft altijd staan.
    for directory in sorted(dirs, key=lambda d: len(d.parts), reverse=True):
        current = directory
        while path_key(current).startswith(prefix):
            try:
                if any(current.iterdir()):
                    break
                current.rmdir()
            except OSError:
                break
            removed.append(current)
            writer.add(JournalEntry(Op.RMDIR, str(current), str(current), True))
            current = current.parent
    return removed
