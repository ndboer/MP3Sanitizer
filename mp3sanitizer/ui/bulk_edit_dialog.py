"""Dialoog om één veld voor meerdere geselecteerde tracks in één keer in te vullen."""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from mp3sanitizer.core.models import Field, FieldValue
from mp3sanitizer.core.validate import Issue, YearError, parse_year_input, text_issues
from mp3sanitizer.ui.track_model import ERROR_COLOR, FIELD_LABEL


class BulkEditDialog(QDialog):
    def __init__(
        self,
        count: int,
        parent: QWidget | None = None,
        field: Field = Field.ARTIST,
        initial: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bulk bewerken")
        self._value: FieldValue = None
        self._year_validator = QRegularExpressionValidator(QRegularExpression(r"\d{0,4}"), self)

        self.field_combo = QComboBox(self)
        for f in Field:
            self.field_combo.addItem(FIELD_LABEL[f], f.value)
        self.value_edit = QLineEdit(initial, self)
        self.value_edit.setMinimumWidth(360)
        self.error_label = QLabel(self)
        self.error_label.setStyleSheet(f"color: {ERROR_COLOR.name()}")
        self.error_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("&Veld:", self.field_combo)
        form.addRow("&Nieuwe waarde:", self.value_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Toepassen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Toepassen op <b>{count}</b> geselecteerde tracks.", self))
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)

        self.field_combo.currentIndexChanged.connect(self._on_field_changed)
        self.value_edit.textChanged.connect(lambda _: self.error_label.clear())
        self.field_combo.setCurrentIndex(self.field_combo.findData(field.value))
        self._on_field_changed()
        self.value_edit.setFocus()
        self.value_edit.selectAll()

    @property
    def field(self) -> Field:
        return Field(self.field_combo.currentData())

    @property
    def value(self) -> FieldValue:
        """Geldig na ``accept()``."""
        return self._value

    def _on_field_changed(self, *_: object) -> None:
        is_year = self.field is Field.YEAR
        self.value_edit.setValidator(self._year_validator if is_year else None)
        self.value_edit.setPlaceholderText("leeg = jaar verwijderen" if is_year else "")
        self.error_label.clear()

    def accept(self) -> None:
        text = self.value_edit.text()
        if self.field is Field.YEAR:
            try:
                self._value = parse_year_input(text)
            except YearError as exc:
                self.error_label.setText(str(exc))
                return
        else:
            value = " ".join(text.split())
            if Issue.EMPTY in text_issues(value):
                self.error_label.setText(f"{FIELD_LABEL[self.field]} mag niet leeg zijn.")
                return
            # Ongeldige tekens zijn toegestaan; ze worden in de tabel gemarkeerd en blokkeren
            # later het opslaan.
            self._value = value
        super().accept()
