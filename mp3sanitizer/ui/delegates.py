"""Item-delegates voor het bewerken in de tabel."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QLineEdit, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from mp3sanitizer.core.models import Field
from mp3sanitizer.ui.track_model import Col


class TrackEditDelegate(QStyledItemDelegate):
    """Eenvoudige regel-editor; voor het jaar alleen maximaal vier cijfers."""

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
        return editor

    def setEditorData(self, editor: QWidget, index: QModelIndex | QPersistentModelIndex) -> None:
        if isinstance(editor, QLineEdit):
            editor.setText(index.data(Qt.ItemDataRole.EditRole) or "")
            editor.selectAll()
        else:  # pragma: no cover
            super().setEditorData(editor, index)
