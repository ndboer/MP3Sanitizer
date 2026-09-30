"""Item-delegates voor het bewerken in de tabel."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QLineEdit,
    QMenu,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from mp3sanitizer.core.models import Field
from mp3sanitizer.ui.track_model import Col


class TrackEditDelegate(QStyledItemDelegate):
    """Eenvoudige regel-editor; voor het jaar alleen maximaal vier cijfers."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Vult het rechtsklikmenu van de editor aan met (menu, geselecteerde tekst).
        self.menu_hook: Callable[[QMenu, str], None] | None = None

    def createEditor(
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        editor = QLineEdit(parent)
        editor.setFrame(False)
        if Col(index.column()).field is Field.YEAR:
            editor.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,4}"), editor))
            editor.setPlaceholderText("jjjj")
        editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        editor.customContextMenuRequested.connect(lambda pos: self._editor_menu(editor, pos))
        return editor

    def _editor_menu(self, editor: QLineEdit, pos) -> None:
        menu = editor.createStandardContextMenu()
        if self.menu_hook is not None:
            menu.addSeparator()
            self.menu_hook(menu, editor.selectedText())
        menu.exec(editor.mapToGlobal(pos))
        menu.deleteLater()

    def setEditorData(self, editor: QWidget, index: QModelIndex | QPersistentModelIndex) -> None:
        if isinstance(editor, QLineEdit):
            editor.setText(index.data(Qt.ItemDataRole.EditRole) or "")
            editor.selectAll()
        else:  # pragma: no cover
            super().setEditorData(editor, index)
