"""Afspelen: spatiebalk, Play-kolom, automatisch volgende en stoppen vóór bestandsoperaties.

Er wordt niet gecontroleerd of er echt geluid klinkt (CI heeft geen audio-apparaat); wel welke
track actief is en dat het bestand wordt losgelaten.
"""

import struct
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mp3sanitizer.core.journal import JournalStore
from mp3sanitizer.core.models import Field
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.ui.main_window import MainWindow
from mp3sanitizer.ui.player import next_in_selection
from mp3sanitizer.ui.track_model import Col

NAMES = ["A - Een (1990).wav", "B - Twee (1991).wav", "C - Drie (1992).wav"]


def _wav(path: Path, seconds: float = 0.5, rate: int = 8000) -> None:
    data = b"\x80" * int(seconds * rate)
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate, 1, 8)
    path.write_bytes(header + fmt + b"data" + struct.pack("<I", len(data)) + data)


def _flush(n=3):
    for _ in range(n):
        QApplication.processEvents()


@pytest.fixture
def window(qapp, tmp_path):
    music = tmp_path / "muziek"
    music.mkdir()
    for name in NAMES:
        _wav(music / name)
    store = SettingsStore.load(tmp_path / "config")
    store.settings.extensions = [".wav"]
    w = MainWindow(store, QThreadPool(), JournalStore(tmp_path / "journal"))
    w.resize(1200, 600)
    w.show()
    w.activateWindow()
    QTest.qWaitForWindowActive(w)
    w.start_scan(music)
    deadline = time.monotonic() + 10
    while w.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    w.table.setFocus()
    yield w
    w.player.stop()
    w.model.edits.clear()
    w.close()
    w.deleteLater()
    _flush()


def _select_rows(w, rows):
    sm = w.table.selectionModel()
    flags = QItemSelectionModel.SelectionFlag
    sm.clearSelection()
    for r in rows:
        sm.select(w.proxy.index(r, 0), flags.Select | flags.Rows)
    sm.setCurrentIndex(w.proxy.index(rows[0], Col.ARTIST), flags.NoUpdate)


def test_next_in_selection():
    assert next_in_selection([3, 1, 7], 1) == 7
    assert next_in_selection([3, 1, 7], 7) is None
    assert next_in_selection([3, 1, 7], 5) is None
    assert next_in_selection([], None) is None


def test_play_column_is_first_and_shows_state(window):
    hh = window.table.horizontalHeader()
    assert hh.logicalIndex(0) == Col.PLAY
    assert window.proxy.index(0, Col.PLAY).data(Qt.ItemDataRole.ToolTipRole) == "Afspelen (spatie)"
    assert not window.proxy.index(0, Col.PLAY).data(Qt.ItemDataRole.DecorationRole).isNull()


def test_space_plays_and_stops(window):
    _select_rows(window, [1])
    QTest.keyClick(window.table, Qt.Key.Key_Space)
    _flush()
    tid = window.model.track_id(1)
    assert window.player.current_track == tid
    assert window.player.source.toLocalFile().endswith("B - Twee (1991).wav")
    assert window.proxy.index(1, Col.PLAY).data(Qt.ItemDataRole.ToolTipRole) == "Stoppen (spatie)"
    assert window.proxy.index(1, Col.ARTIST).data(Qt.ItemDataRole.FontRole).bold()
    assert window.mini_player.title_label.text() == "B - Twee"

    QTest.keyClick(window.table, Qt.Key.Key_Space)
    _flush()
    assert window.player.current_track is None
    assert window.player.source.isEmpty()  # bestand losgelaten
    assert window.model.playing_track is None


def test_new_play_replaces_previous(window):
    window.toggle_play(window.model.track_id(0))
    window.toggle_play(window.model.track_id(2))
    _flush()
    assert window.player.current_track == window.model.track_id(2)
    assert window.proxy.index(0, Col.PLAY).data(Qt.ItemDataRole.ToolTipRole) == "Afspelen (spatie)"
    assert not window.proxy.index(0, Col.PLAY).data(Qt.ItemDataRole.DecorationRole).isNull()


def test_click_on_play_column(window):
    index = window.proxy.index(2, Col.PLAY)
    rect = window.table.visualRect(index)
    QTest.mouseClick(window.table.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    _flush()
    assert window.player.current_track == window.model.track_id(2)


def test_space_in_editor_types_a_space(window):
    _select_rows(window, [0])
    window.table.edit(window.proxy.index(0, Col.TITLE))
    editor = QApplication.focusWidget()
    QTest.keyClicks(editor, "x y")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    _flush()
    assert window.player.current_track is None
    assert window.proxy.index(0, Col.TITLE).data() == "x y"


def test_autoplay_next_selected(window):
    _select_rows(window, [0, 2])
    first, last = window.model.track_id(0), window.model.track_id(2)
    window.mini_player.autoplay.setChecked(False)
    window._on_track_finished(first)
    assert window.player.current_track is None
    window.mini_player.autoplay.setChecked(True)
    window._on_track_finished(first)
    assert window.player.current_track == last
    window.player.stop()
    window._on_track_finished(last)  # laatste van de selectie: stoppen
    assert window.player.current_track is None


def test_save_stops_playback(window):
    tid = window.model.track_id(0)
    window.toggle_play(tid)
    window.model.set_field([tid], Field.TITLE, "Nieuw")
    from mp3sanitizer.ui.save_dialog import SavePreviewDialog

    dialog = SavePreviewDialog(window.plan_inputs(), window._root, window._settings, window)
    window.start_save(dialog.selected_plans(), False)
    assert window.player.current_track is None
    deadline = time.monotonic() + 10
    while window.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert (window._root / "A - Nieuw (1990).wav").exists()


def test_volume_and_autoplay_saved_in_settings(window):
    window.mini_player.volume_slider.setValue(33)
    window.mini_player.autoplay.setChecked(True)
    window._save_view_state()
    assert window._settings.volume == 33
    assert window._settings.autoplay_next is True
