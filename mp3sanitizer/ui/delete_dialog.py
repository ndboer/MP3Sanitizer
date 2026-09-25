"""Bevestiging voor verwijderen: aantal en lijst; permanent alleen met extra bevestiging."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from mp3sanitizer.ui.track_model import ERROR_COLOR


class DeleteDialog(QDialog):
    def __init__(self, paths: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Verwijderen")
        self.resize(720, 420)
        self._count = len(paths)
        self.heading = QLabel(self)
        self.heading.setWordWrap(True)
        self.list = QListWidget(self)
        self.list.addItems(list(paths))
        self.permanent = QCheckBox("&Permanent verwijderen (niet naar de Prullenbak)", self)
        self.permanent.toggled.connect(self._update)
        self.warning = QLabel(
            "Permanent verwijderde bestanden zijn niet terug te halen, ook niet via "
            "'Laatste batch terugdraaien'.",
            self,
        )
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(f"color: {ERROR_COLOR.name()}")

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.cancel_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.cancel_button.setText("Annuleren")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.permanent)
        layout.addWidget(self.warning)
        layout.addWidget(self.buttons)
        self._update()

    @property
    def is_permanent(self) -> bool:
        return self.permanent.isChecked()

    def _update(self, *_: object) -> None:
        n = self._count
        if self.is_permanent:
            self.heading.setText(f"<b>{n} bestanden permanent verwijderen?</b>")
            self.ok_button.setText("Permanent verwijderen…")
            # Bij permanent: Enter kiest Annuleren, zodat het nooit per ongeluk gebeurt.
            self.cancel_button.setDefault(True)
        else:
            self.heading.setText(f"<b>{n} bestanden naar de Prullenbak verplaatsen?</b>")
            self.ok_button.setText("Naar Prullenbak")
            self.ok_button.setDefault(True)
        self.warning.setVisible(self.is_permanent)

    def confirm_permanent(self) -> bool:
        """Extra bevestiging; los te vervangen in tests."""
        answer = QMessageBox.warning(
            self,
            "Permanent verwijderen",
            f"Weet je het zeker? {self._count} bestanden worden definitief verwijderd. "
            "Dit kan niet ongedaan worden gemaakt.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def accept(self) -> None:
        if self.is_permanent and not self.confirm_permanent():
            return
        super().accept()
