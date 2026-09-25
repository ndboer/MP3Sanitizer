"""Sectie 10: CSV-export, sessies (projectbestand), Verkenner."""

import time

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from mp3sanitizer.core.journal import JournalStore
from mp3sanitizer.core.models import Field
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.ui import main_window as main_window_module
from mp3sanitizer.ui.main_window import MainWindow
from mp3sanitizer.ui.proxy_model import QuickFilter
from mp3sanitizer.ui.track_model import Col

FILES = ["1985/a-ha - take on me (1985).mp3", "Beyoncé - Halo (2008).mp3", "rommel.mp3"]


def wait_idle(w, timeout=10.0):
    deadline = time.monotonic() + timeout
    while (w.busy or w._batch_worker is not None) and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    for _ in range(3):
        QApplication.processEvents()


@pytest.fixture
def window(qapp, tmp_path):
    music = tmp_path / "muziek"
    for rel in FILES:
        (music / rel).parent.mkdir(parents=True, exist_ok=True)
        (music / rel).write_bytes(b"")
    w = MainWindow(SettingsStore.load(tmp_path / "c"), QThreadPool(), JournalStore(tmp_path / "j"))
    w.start_scan(music)
    wait_idle(w)
    yield w
    w.model.edits.clear()
    w.close()
    w.deleteLater()


def _tid(w, name):
    return next(t.id for t in w.model.tracks if t.filename == name)


def test_csv_export_visible_columns_and_filter(window, tmp_path):
    window.set_quick_filter(QuickFilter.PARSE_ERRORS)
    path = tmp_path / "uit.csv"
    assert window.write_csv(path) == 1
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "Status;Artiest;Titel;Jaar;Folder;Bestandsnaam"  # zonder Play-kolom
    assert lines[1] == "Parse-fout;;rommel;;;rommel.mp3"
    window.set_quick_filter(QuickFilter.ALL)
    window.table.setColumnHidden(Col.STATUS, True)
    assert window.write_csv(path) == 3
    assert "Beyoncé;Halo;2008" in path.read_text(encoding="utf-8-sig")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_session_roundtrip(window, tmp_path):
    tid = _tid(window, "a-ha - take on me (1985).mp3")
    window.model.set_field([tid], Field.ARTIST, "A-ha")
    window.model.set_field([tid], Field.TITLE, "Take On Me")
    other = _tid(window, "rommel.mp3")
    window.model.set_field([other], Field.ARTIST, "Onbekend")
    session = tmp_path / "s.mp3s.json"
    assert window.write_session(session) == 2

    window.model.edits.clear()
    window.start_scan(window._root)  # alles vergeten
    wait_idle(window)
    assert window.model.changed_count() == 0

    window.load_session(session)
    wait_idle(window)
    tid = _tid(window, "a-ha - take on me (1985).mp3")
    assert window.model.edits.artist(tid) == "A-ha"
    assert window.model.edits.title(tid) == "Take On Me"
    assert window.model.edits.artist(_tid(window, "rommel.mp3")) == "Onbekend"
    assert window.undo_stack.count() == 1  # één undo-stap
    assert "Sessie geladen: 3 wijzigingen" in window.message_label.text()


def test_session_with_missing_file_reports(window, tmp_path):
    tid = _tid(window, "rommel.mp3")
    window.model.set_field([tid], Field.ARTIST, "X")
    session = tmp_path / "s.mp3s.json"
    window.write_session(session)
    (window._root / "rommel.mp3").unlink()
    window.model.edits.clear()
    window.load_session(session)
    wait_idle(window)
    assert "1 bestanden niet (meer) gevonden" in window.message_label.text()


def test_load_session_errors(window, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2])))
    bad = tmp_path / "kapot.mp3s.json"
    bad.write_text("{kapot", encoding="utf-8")
    window.load_session(bad)
    assert "onleesbaar" in shown[0]


def test_discard_prompt_can_save_session(window, tmp_path, monkeypatch):
    window.model.set_field([_tid(window, "rommel.mp3")], Field.ARTIST, "X")
    target = tmp_path / "bij-afsluiten.mp3s.json"
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Save)
    )
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    assert window.confirm_discard("Afsluiten") is True
    assert target.exists()


def test_reveal_in_explorer(window, monkeypatch):
    calls = []
    monkeypatch.setattr(main_window_module.subprocess, "Popen", lambda cmd: calls.append(cmd))
    monkeypatch.setattr(main_window_module.sys, "platform", "win32")
    window.table.selectRow(0)
    window.reveal_in_explorer()
    assert calls and calls[0].startswith('explorer /select,"')
    assert calls[0].endswith('.mp3"')
