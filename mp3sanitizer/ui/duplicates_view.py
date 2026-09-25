"""Duplicatenvenster: groepen met bitrate/duur/grootte/map en 'beste automatisch behouden'.

Aangevinkte tracks worden voorgesteld voor verwijderen; het verwijderen zelf loopt via de
gewone bevestiging (Prullenbak) in het hoofdvenster.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QThreadPool
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mp3sanitizer.core.duplicates import DupItem, DupOptions, best_item, find_duplicates
from mp3sanitizer.core.settings import Settings
from mp3sanitizer.ui.track_model import TrackTableModel, format_duration, format_size
from mp3sanitizer.ui.workers import FunctionWorker, JobRunner

TRACK_ID_ROLE = Qt.ItemDataRole.UserRole + 30
KEEP_TEXT = "★ behouden"
_CHECKABLE = (
    Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
)


def _relative_folder(path: Path, root: Path | None) -> str:
    folder = os.fspath(path.parent)
    if root is not None:
        base = os.fspath(root).rstrip("\\/") + os.sep
        if folder.startswith(base):
            return folder[len(base) :]
        if folder == os.fspath(root):
            return ""
    return folder


class DuplicatesDialog(QDialog):
    def __init__(
        self,
        model: TrackTableModel,
        settings: Settings,
        pool: QThreadPool,
        root: Path | None = None,
        play: Callable[[int], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Duplicaten")
        self.resize(1150, 650)
        self.model = model
        self._settings = settings
        self._root = root
        self._play = play
        self._jobs = JobRunner(pool, self)
        self.groups: list[list[DupItem]] = []
        self.to_delete: list[int] = []

        self.strict = QRadioButton("&Strikt (exact na normalisatie)", self)
        self.fuzzy = QRadioButton("F&uzzy, drempel:", self)
        self.threshold = QSpinBox(self)
        self.threshold.setRange(70, 100)
        self.threshold.setValue(settings.dup_threshold)
        (self.fuzzy if settings.dup_fuzzy else self.strict).setChecked(True)
        self.ignore_year = QCheckBox("&Jaar negeren", self)
        self.ignore_year.setChecked(settings.dup_ignore_year)
        self.ignore_versions = QCheckBox("&Versies negeren (Remix, Live, Radio Edit, …)", self)
        self.ignore_versions.setChecked(settings.dup_ignore_versions)
        self.use_duration = QCheckBox("Duur ±2 s &als extra criterium", self)
        self.use_duration.setChecked(settings.dup_use_duration)
        self.search_button = QPushButton("&Zoeken", self)
        self.search_button.clicked.connect(self.search)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["Bestand", "Map", "Bitrate", "Duur", "Grootte", "Jaar", ""])
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(1, 200)
        for col in (2, 3, 4, 5, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemChanged.connect(lambda *_: self._update_summary())
        self.tree.itemActivated.connect(self._on_activated)
        self.tree.installEventFilter(self)

        self.status = QLabel(self)
        self.auto_button = QPushButton("&Beste automatisch behouden", self)
        self.auto_button.setToolTip(
            "Per groep: hoogste bitrate, dan langste duur, dan kortste pad behouden; "
            "de rest aanvinken voor verwijderen."
        )
        self.auto_button.clicked.connect(self.auto_select)
        self.play_button = QPushButton("Af&spelen", self)
        self.play_button.clicked.connect(self.play_current)
        self.play_button.setVisible(play is not None)
        self.delete_button = QPushButton(self)
        self.delete_button.clicked.connect(self.request_delete)
        self.close_button = QPushButton("Sluiten", self)
        self.close_button.clicked.connect(self.reject)

        options = QHBoxLayout()
        options.addWidget(self.strict)
        options.addWidget(self.fuzzy)
        options.addWidget(self.threshold)
        options.addSpacing(12)
        options.addWidget(self.ignore_year)
        options.addWidget(self.ignore_versions)
        options.addWidget(self.use_duration)
        options.addStretch(1)
        options.addWidget(self.search_button)
        buttons = QHBoxLayout()
        buttons.addWidget(self.auto_button)
        buttons.addWidget(self.play_button)
        buttons.addStretch(1)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addLayout(options)
        layout.addWidget(self.tree, 1)
        layout.addWidget(
            QLabel(
                "Aangevinkt = verwijderen (naar de Prullenbak, na bevestiging). "
                "Spatie schakelt, Enter speelt af.",
                self,
            )
        )
        layout.addWidget(self.status)
        layout.addLayout(buttons)
        self._update_summary()
        self.search()

    # --- zoeken --------------------------------------------------------------------------
    def options(self) -> DupOptions:
        return DupOptions(
            fuzzy=self.fuzzy.isChecked(),
            threshold=self.threshold.value(),
            ignore_year=self.ignore_year.isChecked(),
            ignore_versions=self.ignore_versions.isChecked(),
            use_duration=self.use_duration.isChecked(),
            articles=tuple(self._settings.articles),
        )

    def search(self) -> None:
        self.status.setText("Zoeken naar duplicaten…")
        self.search_button.setEnabled(False)
        worker = FunctionWorker(
            find_duplicates, self.model.dup_items(), self.options(), pass_cancel=True
        )
        self._jobs.run("dups", worker, self._show)

    def _show(self, result: object) -> None:
        self.search_button.setEnabled(True)
        self.groups = result  # type: ignore[assignment]
        self.model.set_duplicates(i.track_id for g in self.groups for i in g)
        self.tree.blockSignals(True)
        self.tree.clear()
        for group in self.groups:
            first = group[0]
            top = QTreeWidgetItem([f"{first.artist} - {first.title}  ({len(group)})"])
            top.setFirstColumnSpanned(True)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            for item in group:
                child = QTreeWidgetItem(
                    [
                        item.path.name,
                        _relative_folder(item.path, self._root),
                        f"{item.bitrate_kbps} kbps" if item.bitrate_kbps else "",
                        format_duration(item.duration_s),
                        format_size(item.size_bytes),
                        str(item.year or ""),
                        "",
                    ]
                )
                child.setFlags(_CHECKABLE)
                child.setData(0, TRACK_ID_ROLE, item.track_id)
                child.setToolTip(0, str(item.path))
                for col in (2, 3, 4, 5):
                    child.setTextAlignment(col, Qt.AlignmentFlag.AlignRight)
                top.addChild(child)
            self.tree.addTopLevelItem(top)
        self.tree.expandAll()
        self.tree.blockSignals(False)
        self.auto_select()
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0).child(0))
        self.tree.setFocus()

    # --- selectie ------------------------------------------------------------------------
    def _children(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield i, top.child(j)

    def auto_select(self) -> None:
        """Per groep de beste behouden, de rest aanvinken."""
        self.tree.blockSignals(True)
        for i, child in self._children():
            best = best_item(self.groups[i])
            keep = child.data(0, TRACK_ID_ROLE) == best.track_id
            child.setCheckState(0, Qt.CheckState.Unchecked if keep else Qt.CheckState.Checked)
            child.setText(6, KEEP_TEXT if keep else "")
        self.tree.blockSignals(False)
        self._update_summary()

    def checked_ids(self) -> list[int]:
        return [
            c.data(0, TRACK_ID_ROLE)
            for _, c in self._children()
            if c.checkState(0) == Qt.CheckState.Checked
        ]

    def _update_summary(self) -> None:
        n = len(self.checked_ids())
        tracks = sum(len(g) for g in self.groups)
        self.status.setText(
            f"{len(self.groups)} groepen, {tracks} tracks, {n} aangevinkt voor verwijderen"
            if self.groups
            else "Geen duplicaten gevonden."
        )
        # Waarschuw als ergens alle tracks van een groep zijn aangevinkt.
        all_gone = [
            i
            for i in range(self.tree.topLevelItemCount())
            if all(
                self.tree.topLevelItem(i).child(j).checkState(0) == Qt.CheckState.Checked
                for j in range(self.tree.topLevelItem(i).childCount())
            )
        ]
        if all_gone:
            self.status.setText(
                self.status.text() + f" — let op: in {len(all_gone)} groep(en) blijft niets over"
            )
        self.delete_button.setText(f"Aangevinkte &verwijderen ({n})…")
        self.delete_button.setEnabled(n > 0)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.tree
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Space
            and not event.modifiers()
        ):
            items = [i for i in self.tree.selectedItems() if i.data(0, TRACK_ID_ROLE) is not None]
            if not items and self.tree.currentItem() is not None:
                items = [self.tree.currentItem()]
            items = [i for i in items if i.data(0, TRACK_ID_ROLE) is not None]
            if items:
                target = (
                    Qt.CheckState.Unchecked
                    if all(i.checkState(0) == Qt.CheckState.Checked for i in items)
                    else Qt.CheckState.Checked
                )
                for i in items:
                    i.setCheckState(0, target)
            return True
        return super().eventFilter(watched, event)

    # --- acties --------------------------------------------------------------------------
    def _on_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        tid = item.data(0, TRACK_ID_ROLE)
        if tid is not None and self._play is not None:
            self._play(tid)

    def play_current(self) -> None:
        item = self.tree.currentItem()
        if item is not None:
            self._on_activated(item, 0)

    def request_delete(self) -> None:
        self.to_delete = self.checked_ids()
        if self.to_delete:
            self.accept()

    def store_settings(self) -> None:
        s = self._settings
        s.dup_fuzzy = self.fuzzy.isChecked()
        s.dup_threshold = self.threshold.value()
        s.dup_ignore_year = self.ignore_year.isChecked()
        s.dup_ignore_versions = self.ignore_versions.isChecked()
        s.dup_use_duration = self.use_duration.isChecked()

    def done(self, result: int) -> None:
        self._jobs.cancel_all()
        self.store_settings()
        super().done(result)
