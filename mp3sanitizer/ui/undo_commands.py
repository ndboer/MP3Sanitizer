"""Undo-commando's voor ``QUndoStack``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from PySide6.QtGui import QUndoCommand

from mp3sanitizer.core.models import PendingChange


class ChangeTarget(Protocol):
    def apply_changes(self, changes: Sequence[PendingChange], *, forward: bool = True) -> None: ...


class EditCommand(QUndoCommand):
    """Eén of meer veldwijzigingen als één undo-stap (bijv. een bulk-bewerking)."""

    def __init__(self, target: ChangeTarget, changes: Sequence[PendingChange], text: str) -> None:
        super().__init__(text)
        self._target = target
        self._changes = tuple(changes)

    @property
    def changes(self) -> tuple[PendingChange, ...]:
        return self._changes

    def redo(self) -> None:
        self._target.apply_changes(self._changes, forward=True)

    def undo(self) -> None:
        self._target.apply_changes(self._changes, forward=False)
