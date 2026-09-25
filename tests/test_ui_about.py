"""Over-dialoog, 'Kopieer info', updatecheck (zonder netwerk) en --version."""

import subprocess
import sys
import time

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QLabel

from mp3sanitizer import __version__
from mp3sanitizer.core.journal import JournalStore
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.core.update_check import UpdateResult
from mp3sanitizer.core.version_info import VersionInfo
from mp3sanitizer.ui.about_dialog import AboutDialog
from mp3sanitizer.ui.main_window import MainWindow

INFO = VersionInfo("1.2.3", "abc1234", "2026-09-25 12:00", "3.13", "6.11", "1.48", "Windows")


def test_about_shows_versions_and_copies(qapp):
    d = AboutDialog(info=INFO)
    texts = " ".join(label.text() for label in d.findChildren(QLabel))
    for value in ("1.2.3", "abc1234", "2026-09-25 12:00", "6.11", "1.48"):
        assert value in texts
    d.copy_info()
    clip = QGuiApplication.clipboard().text()
    assert clip.startswith("Mp3Sanitizer 1.2.3\nCommit: abc1234")
    assert "mutagen: 1.48" in clip


def _window(tmp_path):
    w = MainWindow(SettingsStore.load(tmp_path / "c"), QThreadPool(), JournalStore(tmp_path / "j"))
    w.show_update_dialogs = False
    return w


def _wait(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not cond() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    assert cond()


def test_update_check_off_by_default(qapp, tmp_path):
    w = _window(tmp_path)
    assert w._settings.check_updates is False
    assert not w.act_auto_updates.isChecked()
    w.act_auto_updates.setChecked(True)
    assert w._settings.check_updates is True
    w.close()


def test_manual_update_check_reports(qapp, tmp_path):
    w = _window(tmp_path)
    w.update_checker = lambda: UpdateResult("v99.0.0", "https://example.org/r", True)
    w.check_updates(manual=True)
    _wait(lambda: w.last_update_result is not None)
    assert "v99.0.0" in w.message_label.text()

    w.last_update_result = None
    w.update_checker = lambda: UpdateResult(None, None, False, "Geen verbinding: x")
    w.check_updates(manual=True)
    _wait(lambda: w.last_update_result is not None)
    assert "Updatecheck mislukt" in w.message_label.text()
    w.close()


def test_silent_check_only_reports_news(qapp, tmp_path):
    w = _window(tmp_path)
    w.update_checker = lambda: UpdateResult("v0.0.1", None, False)
    w._flash("")
    w.check_updates(manual=False)
    _wait(lambda: w.last_update_result is not None)
    assert w.message_label.text() == ""
    w.close()


def test_version_flag_prints_without_gui():
    out = subprocess.run(
        [sys.executable, "-m", "mp3sanitizer", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert out.stdout.startswith(f"Mp3Sanitizer {__version__}")
