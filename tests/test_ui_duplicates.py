"""Duplicatenvenster, 'beste behouden', verwijderen via bevestiging en het snelfilter."""

import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from mp3sanitizer.core.journal import JournalStore
from mp3sanitizer.core.models import AudioInfo
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.ui import main_window as main_window_module
from mp3sanitizer.ui.duplicates_view import KEEP_TEXT, TRACK_ID_ROLE, DuplicatesDialog
from mp3sanitizer.ui.main_window import MainWindow
from mp3sanitizer.ui.proxy_model import QuickFilter

FILES = {
    "a/The Beatles - Help! (1965).mp3": 320,
    "b/Beatles, The - Help! (1965).mp3": 128,
    "c/The Beatles - Help! (Remastered) (2009).mp3": 256,
    "Queen - Innuendo (1991).mp3": 320,
    "Queen - Inuendo (1991).mp3": 192,
    "ABBA - Waterloo (1974).mp3": 320,
}


def wait_for(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not cond() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    assert cond()


@pytest.fixture
def window(qapp, tmp_path):
    music = tmp_path / "muziek"
    for rel in FILES:
        (music / rel).parent.mkdir(parents=True, exist_ok=True)
        (music / rel).write_bytes(b"x")
    w = MainWindow(SettingsStore.load(tmp_path / "c"), QThreadPool(), JournalStore(tmp_path / "j"))
    w.trash_function = lambda p: Path(p).unlink()
    w.start_scan(music)
    wait_for(lambda: not w.busy)
    # bitrates zoals een echte tag-scan die zou vinden
    infos = [
        (t.id, AudioInfo(200.0, FILES[t.path.relative_to(music).as_posix()], 1000))
        for t in w.model.tracks
    ]
    w.model.set_infos(infos)
    yield w
    w.model.edits.clear()
    w.close()
    w.deleteLater()


def _dialog(w, **settings):
    for k, v in settings.items():
        setattr(w._settings, k, v)
    d = DuplicatesDialog(w.model, w._settings, w._pool, w._root, w.play_track, w)
    wait_for(lambda: d.search_button.isEnabled())
    return d


def _group_names(d):
    return [
        sorted(
            d.tree.topLevelItem(i).child(j).text(0)
            for j in range(d.tree.topLevelItem(i).childCount())
        )
        for i in range(d.tree.topLevelItemCount())
    ]


def test_strict_groups_and_best_kept(window):
    d = _dialog(window)
    assert _group_names(d) == [
        ["Beatles, The - Help! (1965).mp3", "The Beatles - Help! (1965).mp3"]
    ]
    group = d.tree.topLevelItem(0)
    rows = {group.child(j).text(0): group.child(j) for j in range(group.childCount())}
    best = rows["The Beatles - Help! (1965).mp3"]  # 320 kbps
    assert best.text(6) == KEEP_TEXT
    assert best.checkState(0) == Qt.CheckState.Unchecked
    assert rows["Beatles, The - Help! (1965).mp3"].checkState(0) == Qt.CheckState.Checked
    assert best.text(2) == "320 kbps"
    assert best.text(1) == "a"
    assert "1 aangevinkt" in d.status.text()


def test_options_versions_and_fuzzy(window):
    d = _dialog(window)
    d.ignore_versions.setChecked(True)
    d.search()
    wait_for(lambda: d.search_button.isEnabled())
    assert len(_group_names(d)[0]) == 3
    d.fuzzy.setChecked(True)
    d.threshold.setValue(85)
    d.search()
    wait_for(lambda: d.search_button.isEnabled())
    assert ["Queen - Innuendo (1991).mp3", "Queen - Inuendo (1991).mp3"] in _group_names(d)
    d.reject()
    assert window._settings.dup_fuzzy is True  # opties bewaard
    assert window._settings.dup_ignore_versions is True


def test_space_toggles_and_warns_when_nothing_left(window):
    d = _dialog(window)
    d.show()
    group = d.tree.topLevelItem(0)
    keep = next(group.child(j) for j in range(2) if group.child(j).text(6) == KEEP_TEXT)
    d.tree.setCurrentItem(keep)
    d.tree.setFocus()
    QTest.keyClick(d.tree, Qt.Key.Key_Space)
    assert keep.checkState(0) == Qt.CheckState.Checked
    assert "blijft niets over" in d.status.text()
    d.auto_select()
    assert keep.checkState(0) == Qt.CheckState.Unchecked
    d.close()


def test_delete_goes_through_confirmation(window, monkeypatch):
    class AutoDupDialog(DuplicatesDialog):
        def exec(self):
            wait_for(lambda: self.search_button.isEnabled())
            self.request_delete()
            return QDialog.DialogCode.Accepted

    confirmed = []

    class Confirm:
        def __init__(self, paths, parent=None):
            confirmed.append(list(paths))
            self.is_permanent = False

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module, "DuplicatesDialog", AutoDupDialog)
    monkeypatch.setattr(main_window_module, "DeleteDialog", Confirm)
    window.open_duplicates()
    wait_for(lambda: window._batch_worker is None and not window.busy)
    assert confirmed == [[str(Path("b") / "Beatles, The - Help! (1965).mp3")]]
    assert not (window._root / "b" / "Beatles, The - Help! (1965).mp3").exists()
    assert (window._root / "a" / "The Beatles - Help! (1965).mp3").exists()


def test_quick_filter_duplicates(window):
    window.set_quick_filter(QuickFilter.DUPLICATES)
    wait_for(lambda: window.proxy.rowCount() == 2)
    window.set_quick_filter(QuickFilter.ALL)
    assert window.proxy.rowCount() == 6


def test_enter_plays_track(window):
    d = _dialog(window)
    child = d.tree.topLevelItem(0).child(0)
    d.tree.itemActivated.emit(child, 0)
    assert window.player.current_track == child.data(0, TRACK_ID_ROLE)
    window.player.stop()
