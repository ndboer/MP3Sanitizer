"""Opstarten van de Qt-applicatie."""

from __future__ import annotations

import logging
import sys
from types import TracebackType

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from mp3sanitizer import __version__
from mp3sanitizer.core.app_logging import setup_logging
from mp3sanitizer.core.paths import APP_NAME, config_dir, log_dir
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.ui.main_window import MainWindow

log = logging.getLogger(__name__)


def _excepthook(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
) -> None:
    log.critical("Onafgehandelde fout", exc_info=(exc_type, exc, tb))
    sys.__excepthook__(exc_type, exc, tb)


def run(argv: list[str] | None = None) -> int:
    setup_logging(log_dir())
    sys.excepthook = _excepthook
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    store = SettingsStore.load(config_dir())
    window = MainWindow(store)
    window.show()
    QTimer.singleShot(0, window.show_load_messages)
    return app.exec()
