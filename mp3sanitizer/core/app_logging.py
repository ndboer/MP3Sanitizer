"""Logging naar een roterend logbestand in de user-data-map."""

from __future__ import annotations

import logging
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from mp3sanitizer import __version__

LOG_FILENAME = "mp3sanitizer.log"


class _VersionHeaderHandler(RotatingFileHandler):
    """Schrijft de appversie als eerste regel van elk (nieuw) logbestand."""

    def _header(self) -> None:
        if self.stream is not None and self.stream.tell() == 0:
            self.stream.write(
                f"Mp3Sanitizer {__version__} | Python {platform.python_version()} "
                f"| {platform.platform()}\n"
            )

    def _open(self):  # type: ignore[override]
        stream = super()._open()
        self.stream = stream
        self._header()
        return stream


def setup_logging(log_dir: Path, level: int = logging.INFO) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / LOG_FILENAME
    handler = _VersionHeaderHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    if sys.stderr is not None:  # in een --windowed PyInstaller-build is stderr None
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        root.addHandler(console)
    logging.getLogger(__name__).info("Mp3Sanitizer %s gestart", __version__)
    return path
