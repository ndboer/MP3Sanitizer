"""Sorteer- en filterproxy met snelfilters en een tekstzoekfilter."""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSortFilterProxyModel, Qt

from mp3sanitizer.core.models import ParseStatus
from mp3sanitizer.core.normalize import fold
from mp3sanitizer.ui.track_model import TrackTableModel


class QuickFilter(StrEnum):
    ALL = "all"
    CHANGED = "changed"
    PARSE_ERRORS = "parse_errors"
    NO_YEAR = "no_year"
    TAG_MISMATCH = "tag_mismatch"
    INVALID = "invalid"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def depends_on_info(self) -> bool:
        """Of het resultaat verandert als lazy ingelezen tags binnenkomen."""
        return self is QuickFilter.TAG_MISMATCH


_LABELS = {
    QuickFilter.ALL: "Alles",
    QuickFilter.CHANGED: "Gewijzigd (niet opgeslagen)",
    QuickFilter.PARSE_ERRORS: "Alleen parse-fouten",
    QuickFilter.NO_YEAR: "Zonder jaar",
    QuickFilter.TAG_MISMATCH: "Tag-mismatch",
    QuickFilter.INVALID: "Ongeldige namen",
}


class TrackFilterProxy(QSortFilterProxyModel):
    """Filtert alleen; het sorteren doet het bronmodel.

    ``dynamicSortFilter`` staat uit: anders filtert Qt bij elke ``dataChanged`` (bijv. elke
    batch ingelezen tags) alle rijen opnieuw. Wie data wijzigt waar een filter van afhangt,
    roept ``refresh()`` aan (het hoofdvenster doet dat na elke bewerking).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDynamicSortFilter(False)
        self._quick = QuickFilter.ALL
        self._text = ""

    def refresh(self) -> None:
        self._begin_filter_change()
        self._end_filter_change()

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        # Het bronmodel sorteert (veel sneller); de proxy behoudt die volgorde en filtert alleen.
        source = self.sourceModel()
        if source is not None:
            source.sort(column, order)

    @property
    def quick_filter(self) -> QuickFilter:
        return self._quick

    def set_quick_filter(self, value: QuickFilter) -> None:
        if value != self._quick:
            self._begin_filter_change()
            self._quick = value
            self._end_filter_change()

    def set_text_filter(self, text: str) -> None:
        text = fold(text)
        if text != self._text:
            self._begin_filter_change()
            self._text = text
            self._end_filter_change()

    def _begin_filter_change(self) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt 6.9+
            self.beginFilterChange()

    def _end_filter_change(self) -> None:
        if hasattr(self, "endFilterChange"):
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:  # pragma: no cover - oudere Qt
            self.invalidateFilter()

    def filterAcceptsRow(
        self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex
    ) -> bool:
        model = self.sourceModel()
        assert isinstance(model, TrackTableModel)
        track = model.track(source_row)
        match self._quick:
            case QuickFilter.PARSE_ERRORS:
                if track.parse_status is not ParseStatus.ERROR:
                    return False
            case QuickFilter.CHANGED:
                if not model.is_changed(source_row):
                    return False
            case QuickFilter.NO_YEAR:
                if model.year(source_row) is not None:
                    return False
            case QuickFilter.TAG_MISMATCH:
                if not model.mismatches(source_row):
                    return False
            case QuickFilter.INVALID:
                if not model.has_issues(source_row):
                    return False
        return not self._text or self._text in model.search_key(source_row)
