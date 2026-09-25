"""Gedeeld preview-dialoog: per regel een checkbox, oud → nieuw met gemarkeerde verschillen.

Gebruikt door Opslaan (hernoemen/verplaatsen) en later door de batch-correcties.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from mp3sanitizer.core.diff import Seg, Segments, diff_segments
from mp3sanitizer.ui.track_model import ERROR_COLOR, WARNING_COLOR

REMOVED_BACKGROUND = QColor(220, 40, 40, 90)
ADDED_BACKGROUND = QColor(40, 170, 60, 90)
SEGMENTS_ROLE = Qt.ItemDataRole.UserRole + 10

type AnyIndex = QModelIndex | QPersistentModelIndex


class Level(StrEnum):
    OK = "ok"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"  # niet uitvoerbaar


@dataclass(slots=True)
class PreviewItem:
    key: Hashable
    label: str  # bijv. "Pad", "Artiest", "Titel"
    old: str
    new: str
    note: str = ""
    level: Level = Level.OK
    checkable: bool = True
    checked: bool = True


class PCol(IntEnum):
    CHECK = 0
    LABEL = 1
    OLD = 2
    NEW = 3
    NOTE = 4


_HEADERS = {
    PCol.CHECK: "",
    PCol.LABEL: "Veld",
    PCol.OLD: "Oud",
    PCol.NEW: "Nieuw",
    PCol.NOTE: "Opmerking",
}


class PreviewModel(QAbstractTableModel):
    checkedChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[PreviewItem] = []
        self._segments: dict[int, tuple[Segments, Segments]] = {}

    @property
    def items(self) -> Sequence[PreviewItem]:
        return self._items

    def set_items(self, items: Iterable[PreviewItem]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self._segments.clear()
        self.endResetModel()
        self.checkedChanged.emit()

    def checked_count(self) -> int:
        return sum(1 for i in self._items if i.checkable and i.checked)

    def set_checked(self, rows: Iterable[int], checked: bool) -> None:
        changed = []
        for row in rows:
            item = self._items[row]
            if item.checkable and item.checked != checked:
                item.checked = checked
                changed.append(row)
        if changed:
            self.dataChanged.emit(
                self.index(min(changed), PCol.CHECK), self.index(max(changed), PCol.CHECK)
            )
            self.checkedChanged.emit()

    def segments(self, row: int) -> tuple[Segments, Segments]:
        if row not in self._segments:
            item = self._items[row]
            self._segments[row] = diff_segments(item.old, item.new)
        return self._segments[row]

    # --- QAbstractTableModel -------------------------------------------------------------
    def rowCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(PCol)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _HEADERS[PCol(section)]
        return None

    def flags(self, index: AnyIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == PCol.CHECK and self._items[index.row()].checkable:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(self, index: AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        item = self._items[index.row()]
        col = PCol(index.column())
        if role == Qt.ItemDataRole.CheckStateRole and col == PCol.CHECK:
            if not item.checkable:
                return None
            return Qt.CheckState.Checked if item.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            match col:
                case PCol.CHECK:
                    return "✕" if not item.checkable else ""
                case PCol.LABEL:
                    return item.label
                case PCol.OLD:
                    return item.old
                case PCol.NEW:
                    return item.new
                case PCol.NOTE:
                    return item.note
        if role == Qt.ItemDataRole.ToolTipRole:
            if col in (PCol.OLD, PCol.NEW):
                return f"Oud:   {item.old}\nNieuw: {item.new}"
            if item.note:
                return item.note
        if role == Qt.ItemDataRole.ForegroundRole and col in (PCol.NOTE, PCol.CHECK):
            if item.level is Level.ERROR:
                return ERROR_COLOR
            if item.level is Level.WARNING:
                return WARNING_COLOR
        if role == SEGMENTS_ROLE and col in (PCol.OLD, PCol.NEW):
            old, new = self.segments(index.row())
            return old if col == PCol.OLD else new
        return None

    def setData(self, index: AnyIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == PCol.CHECK:
            checked = Qt.CheckState(value) == Qt.CheckState.Checked
            self.set_checked([index.row()], checked)
            return True
        return False


class PreviewFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._text = ""
        self._only_notes = False

    def set_text(self, text: str) -> None:
        self._text = text.casefold()
        self.invalidate()

    def set_only_notes(self, value: bool) -> None:
        self._only_notes = value
        self.invalidate()

    def filterAcceptsRow(self, source_row: int, source_parent: AnyIndex) -> bool:
        model = self.sourceModel()
        assert isinstance(model, PreviewModel)
        item = model.items[source_row]
        if self._only_notes and item.level is Level.OK:
            return False
        if self._text:
            hay = f"{item.label}\x00{item.old}\x00{item.new}\x00{item.note}".casefold()
            return self._text in hay
        return True


class DiffDelegate(QStyledItemDelegate):
    """Markeert verwijderde (rood) en toegevoegde (groen) delen van oud/nieuw.

    De stijl tekent de cel inclusief tekst zelf, zodat kleuren bij selectie en in licht/donker
    thema altijd kloppen; de markering komt er halfdoorzichtig overheen.
    """

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: AnyIndex) -> None:
        super().paint(painter, option, index)
        segments = index.data(SEGMENTS_ROLE)
        if not segments or all(kind is Seg.SAME for _, kind in segments):
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        # Zelfde marge als QCommonStyle bij het tekenen van itemtekst.
        margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, widget) + 1
        text_rect = text_rect.adjusted(margin, 0, -margin, 0)
        metrics = QFontMetrics(opt.font)
        painter.save()
        painter.setClipRect(text_rect)
        x = text_rect.left()
        height = metrics.height()
        top = text_rect.top() + (text_rect.height() - height) // 2
        for text, kind in segments:
            width = metrics.horizontalAdvance(text)
            if kind is not Seg.SAME:
                color = REMOVED_BACKGROUND if kind is Seg.REMOVED else ADDED_BACKGROUND
                painter.fillRect(QRect(x, top, max(width, 2), height), color)
            x += width
            if x > text_rect.right():
                break
        painter.restore()


class PreviewDialog(QDialog):
    """Basisdialoog. Subklassen vullen ``options_layout`` en roepen ``set_items`` aan."""

    def __init__(
        self,
        title: str,
        description: str,
        parent: QWidget | None = None,
        accept_text: str = "Uitvoeren",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1150, 650)
        self.model = PreviewModel(self)
        self.proxy = PreviewFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.description = QLabel(description, self)
        self.description.setWordWrap(True)

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter in de preview…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self.proxy.set_text)
        self.only_notes = QCheckBox("Alleen regels met &opmerkingen", self)
        self.only_notes.toggled.connect(self.proxy.set_only_notes)
        top = QHBoxLayout()
        top.addWidget(QLabel("&Filter:", self, buddy=self.filter_edit))
        top.addWidget(self.filter_edit, 1)
        top.addWidget(self.only_notes)

        self.table = QTableView(self)
        self.table.setModel(self.proxy)
        self.table.setItemDelegate(DiffDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(self.table.fontMetrics().height() + 8)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(PCol.CHECK, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(PCol.OLD, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(PCol.NEW, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(PCol.CHECK, 28)
        self.table.setColumnWidth(PCol.LABEL, 70)
        self.table.setColumnWidth(PCol.NOTE, 260)

        # Spatie via een eventfilter: de tabel claimt spatie anders zelf (typen-om-te-zoeken)
        # en zou dan alleen de huidige regel omschakelen.
        self.table.installEventFilter(self)

        self.select_all_button = QPushButton("&Alles selecteren", self)
        self.select_all_button.clicked.connect(lambda: self._check_visible(True))
        self.select_none_button = QPushButton("&Niets selecteren", self)
        self.select_none_button.clicked.connect(lambda: self._check_visible(False))
        self.count_label = QLabel(self)
        selection_row = QHBoxLayout()
        selection_row.addWidget(self.select_all_button)
        selection_row.addWidget(self.select_none_button)
        selection_row.addWidget(QLabel("(spatie: geselecteerde regels aan/uit)", self))
        selection_row.addStretch(1)
        selection_row.addWidget(self.count_label)

        self.options_layout = QVBoxLayout()

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(accept_text)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuleren")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.description)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addLayout(selection_row)
        layout.addLayout(self.options_layout)
        layout.addWidget(self.buttons)

        self.model.checkedChanged.connect(self._update_count)
        self._update_count()
        self.table.setFocus()

    # --- API -----------------------------------------------------------------------------
    def set_items(self, items: Iterable[PreviewItem]) -> None:
        """Vervang de regels; eerder uitgevinkte sleutels blijven uitgevinkt."""
        previous = {i.key: i.checked for i in self.model.items if i.checkable}
        new_items = list(items)
        for item in new_items:
            if item.checkable and item.key in previous:
                item.checked = previous[item.key]
        self.model.set_items(new_items)
        if self.proxy.rowCount():
            self.table.setCurrentIndex(self.proxy.index(0, PCol.CHECK))

    def checked_keys(self) -> list[Hashable]:
        return [i.key for i in self.model.items if i.checkable and i.checked]

    def summary_text(self) -> str:
        """Extra tekst naast de teller; subklassen kunnen dit uitbreiden."""
        return ""

    # --- intern --------------------------------------------------------------------------
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.table
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Space
            and not event.modifiers()
        ):
            self.toggle_selected()
            return True
        return super().eventFilter(watched, event)

    def toggle_selected(self) -> None:
        rows = sorted(
            {self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()}
        )
        if not rows and self.table.currentIndex().isValid():
            rows = [self.proxy.mapToSource(self.table.currentIndex()).row()]
        if not rows:
            return
        # Alles aan tenzij alles al aan staat (zoals in de meeste bestandsbeheerders).
        items = self.model.items
        all_checked = all(items[r].checked for r in rows if items[r].checkable)
        self.model.set_checked(rows, not all_checked)

    def _check_visible(self, checked: bool) -> None:
        rows = [
            self.proxy.mapToSource(self.proxy.index(r, 0)).row()
            for r in range(self.proxy.rowCount())
        ]
        self.model.set_checked(rows, checked)

    def _update_count(self) -> None:
        total = len(self.model.items)
        checked = self.model.checked_count()
        blocked = sum(1 for i in self.model.items if not i.checkable)
        text = f"{checked} van {total} geselecteerd"
        if blocked:
            text += f" · {blocked} niet uitvoerbaar"
        extra = self.summary_text()
        if extra:
            text += f" · {extra}"
        self.count_label.setText(text)
        self.ok_button.setEnabled(checked > 0)
