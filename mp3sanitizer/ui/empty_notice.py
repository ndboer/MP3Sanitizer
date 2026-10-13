"""Melding in plaats van een lege tabel of boom ("het filter heeft geen rijen opgeleverd")."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QAbstractItemView, QLabel


class EmptyNotice(QLabel):
    """Bedekt ``view`` (inclusief kolomkoppen) met een melding op een iets donkerdere achtergrond.

    ``message`` geeft de tekst als de view leeg is, of ``None`` als de rijen getoond moeten
    worden. De melding volgt de rijen van het model vanzelf; na wijzigingen die het model niet
    meldt (zoals ``QTreeWidgetItem.setHidden``) roept de eigenaar ``refresh`` aan.
    """

    def __init__(self, view: QAbstractItemView, message: Callable[[], str | None]) -> None:
        super().__init__(view)
        self._view = view
        self._message = message
        self.setObjectName("emptyNotice")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMargin(24)
        self.setAutoFillBackground(True)
        palette = self.palette()
        base = view.palette().color(QPalette.ColorRole.Base)
        palette.setColor(QPalette.ColorRole.Window, base.darker(110))
        palette.setColor(
            QPalette.ColorRole.WindowText, view.palette().color(QPalette.ColorRole.Text)
        )
        self.setPalette(palette)
        font = self.font()
        font.setPointSizeF(font.pointSizeF() * 1.15)
        self.setFont(font)
        self.hide()
        view.installEventFilter(self)
        # Vertraagd verversen: tijdens een filterwijziging is het model nog niet stabiel.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.refresh)
        model = view.model()
        for signal in (
            model.rowsInserted,
            model.rowsRemoved,
            model.modelReset,
            model.layoutChanged,
        ):
            signal.connect(self._timer.start)
        self.refresh()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._view and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._view.rect())
        return False

    def refresh(self) -> None:
        text = self._message()
        if text:
            self.setText(text)
            self.setGeometry(self._view.rect())
            self.show()
            self.raise_()
        else:
            self.hide()


def quoted(text: str) -> str:
    return f"„{text}”"
