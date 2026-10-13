"""Zoeken: alle woorden moeten voorkomen (AND), "woordgroep" tussen aanhalingstekens."""

import pytest

from mp3sanitizer.core.normalize import fold, matches_all, search_terms
from mp3sanitizer.core.scanner import track_from_path
from mp3sanitizer.ui.preview_dialog import Level, PreviewDialog, PreviewItem
from mp3sanitizer.ui.proxy_model import TrackFilterProxy
from mp3sanitizer.ui.track_model import Col, TrackTableModel


def test_search_terms():
    assert search_terms("  Queen   1991 ") == ("queen", "1991")
    assert search_terms('"under pressure" bowie') == ("under pressure", "bowie")
    assert search_terms('"under pressure') == ("under pressure",)  # niet afgesloten
    assert search_terms('Beyoncé ""') == ("beyonce",)
    assert search_terms("a a") == ("a",)


def test_matches_all():
    hay = fold("Queen & David Bowie\x00Under Pressure\x001981")
    assert matches_all(search_terms("queen pressure"), hay)
    assert matches_all(search_terms("bowie 81"), hay)  # ook deel van een woord
    assert not matches_all(search_terms("queen innuendo"), hay)
    assert not matches_all(search_terms('"queen pressure"'), hay)  # woordgroep


NAMES = [
    "1981/Queen & David Bowie - Under Pressure (1981).mp3",
    "1991/Queen - Innuendo (1991).mp3",
    "rommel/David Bowie - Heroes (1977).mp3",
]


@pytest.fixture
def proxy(qapp, tmp_path):
    model = TrackTableModel()
    model.append_tracks([track_from_path(i, tmp_path / n, tmp_path) for i, n in enumerate(NAMES)])
    proxy = TrackFilterProxy()
    proxy.setSourceModel(model)
    return proxy


def _titles(proxy):
    return sorted(proxy.index(r, Col.TITLE).data() for r in range(proxy.rowCount()))


@pytest.mark.parametrize(
    ("text", "titles"),
    [
        ("queen", ["Innuendo", "Under Pressure"]),
        ("queen bowie", ["Under Pressure"]),
        ("bowie queen", ["Under Pressure"]),
        ("bowie 1977", ["Heroes"]),
        ("rommel", ["Heroes"]),  # map
        ('"david bowie" heroes', ["Heroes"]),
        ('"bowie david"', []),
        ("queen heroes", []),
    ],
)
def test_main_filter_is_and(proxy, text, titles):
    proxy.set_text_filter(text)
    assert _titles(proxy) == titles


def test_preview_filter_is_and(qapp):
    d = PreviewDialog("t", "d")
    d.set_items(
        [
            PreviewItem(1, "Pad", "Queen - Innuendo.mp3", r"1991\Queen - Innuendo.mp3"),
            PreviewItem(2, "Pad", "ABBA - SOS.mp3", r"1975\ABBA - SOS.mp3", "Botsing", Level.ERROR),
        ]
    )
    d.filter_edit.setText("queen 1991")
    assert d.proxy.rowCount() == 1
    d.filter_edit.setText("queen 1975")
    assert d.proxy.rowCount() == 0
    d.filter_edit.setText('"abba - sos" botsing')
    assert d.proxy.rowCount() == 1
