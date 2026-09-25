"""Smoketests voor het tabelmodel, de proxy en het scannen via het hoofdvenster."""

import time
from pathlib import Path

from PySide6.QtCore import QPersistentModelIndex, Qt, QThreadPool

from mp3sanitizer.core.models import AudioInfo
from mp3sanitizer.core.scanner import track_from_path
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.ui.proxy_model import QuickFilter, TrackFilterProxy
from mp3sanitizer.ui.track_model import (
    Col,
    TrackTableModel,
    format_duration,
    format_size,
)

NAMES = [
    "The Beatles - Help! (1965).mp3",
    "ABBA - Waterloo (1974).mp3",
    "Beatles, The - Yesterday.mp3",
    "Queen - Innuendo (1991).mp3",
    "rommel zonder patroon.mp3",
]


def _model(tmp_path: Path) -> tuple[TrackTableModel, TrackFilterProxy]:
    model = TrackTableModel()
    model.append_tracks([track_from_path(i, tmp_path / n, tmp_path) for i, n in enumerate(NAMES)])
    proxy = TrackFilterProxy()
    proxy.setSourceModel(model)
    return model, proxy


def _column(proxy, col: Col) -> list[str]:
    return [proxy.index(r, col).data() for r in range(proxy.rowCount())]


def test_sort_by_artist_uses_sort_key(qapp, tmp_path):
    _, proxy = _model(tmp_path)
    proxy.sort(Col.ARTIST, Qt.SortOrder.AscendingOrder)
    assert _column(proxy, Col.ARTIST) == ["ABBA", "The Beatles", "Beatles, The", "Queen", ""]


def test_sort_by_year_numeric(qapp, tmp_path):
    _, proxy = _model(tmp_path)
    proxy.sort(Col.YEAR, Qt.SortOrder.DescendingOrder)
    assert _column(proxy, Col.YEAR)[:3] == ["1991", "1974", "1965"]


def test_quick_filters_and_search(qapp, tmp_path):
    model, proxy = _model(tmp_path)
    assert proxy.rowCount() == 5
    proxy.set_quick_filter(QuickFilter.PARSE_ERRORS)
    assert _column(proxy, Col.FILENAME) == ["rommel zonder patroon.mp3"]
    assert _column(proxy, Col.STATUS) == ["Parse-fout"]
    proxy.set_quick_filter(QuickFilter.NO_YEAR)
    assert proxy.rowCount() == 2
    proxy.set_quick_filter(QuickFilter.TAG_MISMATCH)
    assert proxy.rowCount() == 0
    model.set_infos([(3, AudioInfo(tag_artist="Queen", tag_title="Innuendo", tag_year=1990))])
    assert proxy.rowCount() == 0  # geen dynamisch filter: pas na refresh()
    proxy.refresh()
    assert proxy.rowCount() == 1
    assert "tags ≠" in proxy.index(0, Col.STATUS).data()
    proxy.set_quick_filter(QuickFilter.ALL)
    proxy.set_text_filter("BEATLES")
    assert proxy.rowCount() == 2
    assert model.parse_error_count() == 1


def test_sorted_model_maps_ids_to_rows(qapp, tmp_path):
    model, proxy = _model(tmp_path)
    proxy.sort(Col.YEAR, Qt.SortOrder.DescendingOrder)
    queen_row = model.row_of(3)
    assert queen_row == 0
    assert model.track(queen_row).artist == "Queen"
    model.set_infos([(3, AudioInfo(duration_s=60))])
    assert model.index(queen_row, Col.DURATION).data() == "1:00"
    # na een nieuwe sortering blijft de selectie (persistent index) op dezelfde track
    persistent = QPersistentModelIndex(model.index(queen_row, Col.ARTIST))
    proxy.sort(Col.ARTIST, Qt.SortOrder.AscendingOrder)
    assert persistent.data() == "Queen"
    assert persistent.row() == model.row_of(3) == 3


def test_info_columns_lazy(qapp, tmp_path):
    model, _ = _model(tmp_path)
    assert model.index(0, Col.DURATION).data() == "…"
    model.set_infos([(0, AudioInfo(duration_s=185.4, bitrate_kbps=320, size_bytes=7_500_000))])
    assert model.index(0, Col.DURATION).data() == "3:05"
    assert model.index(0, Col.BITRATE).data() == "320 kbps"
    assert model.index(0, Col.SIZE).data() == "7.2 MB"


def test_formatters():
    assert format_duration(None) == ""
    assert format_duration(3725) == "1:02:05"
    assert format_size(2048) == "2 KB"
    assert format_size(100) == "100 B"


def test_main_window_scans_folder(qapp, tmp_path):
    from mp3sanitizer.ui.main_window import MainWindow

    music = tmp_path / "muziek"
    for i, name in enumerate(NAMES):
        path = music / str(1960 + i) / name
        path.parent.mkdir(parents=True)
        path.write_bytes(b"geen audio")
    store = SettingsStore.load(tmp_path / "config")
    pool = QThreadPool()
    window = MainWindow(store, pool)
    window.start_scan(music)

    deadline = time.monotonic() + 10
    while window.busy and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()

    assert not window.busy
    assert window.model.rowCount() == len(NAMES)
    assert all(t.info is not None for t in window.model.tracks)
    assert "Mp3Sanitizer" in window.windowTitle()
    window._update_stats()
    assert "Totaal: 5" in window.stats_label.text()
    assert "Parse-fouten: 1" in window.stats_label.text()

    window.close()
    assert store.settings.last_root == str(music)
    assert (tmp_path / "config" / "settings.json").exists()
