"""Recursief scannen van een map met ``os.scandir``."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from mp3sanitizer.core.models import Track
from mp3sanitizer.core.parser import parse_filename

log = logging.getLogger(__name__)

DEFAULT_EXTENSIONS: tuple[str, ...] = (".mp3", ".flac", ".m4a", ".wav", ".ogg")


def normalize_extensions(extensions: Iterable[str]) -> frozenset[str]:
    result = set()
    for ext in extensions:
        ext = ext.strip().casefold()
        if ext:
            result.add(ext if ext.startswith(".") else "." + ext)
    return frozenset(result)


def iter_audio_files(
    root: Path,
    extensions: Iterable[str] = DEFAULT_EXTENSIONS,
    cancelled: Callable[[], bool] | None = None,
) -> Iterator[Path]:
    """Geef alle audiobestanden onder ``root``. Onleesbare mappen worden gelogd en overgeslagen.

    Symbolische links naar mappen worden niet gevolgd (voorkomt lussen).
    """
    exts = normalize_extensions(extensions)
    stack = [os.fspath(root)]
    while stack:
        if cancelled is not None and cancelled():
            return
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = sorted(it, key=lambda e: e.name.casefold())
        except OSError as exc:
            log.warning("Map overgeslagen: %s (%s)", current, exc)
            continue
        subdirs = []
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    subdirs.append(entry.path)
                elif entry.is_file() and os.path.splitext(entry.name)[1].casefold() in exts:
                    yield Path(entry.path)
            except OSError as exc:
                log.warning("Item overgeslagen: %s (%s)", entry.path, exc)
        # Omgekeerd op de stack zodat mappen alfabetisch worden verwerkt.
        stack.extend(reversed(subdirs))


def track_from_path(track_id: int, path: Path, root: Path) -> Track:
    parsed = parse_filename(path.stem)
    return Track(
        id=track_id,
        path=path,
        root=root,
        parse_status=parsed.status,
        artist=parsed.artist,
        title=parsed.title,
        year=parsed.year,
    )
