"""Een track (artiest + titel) opzoeken op MusicBrainz en de officiële schrijfwijze overnemen."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mp3sanitizer.core.musicbrainz import MusicBrainzClient, MusicBrainzError, RecordingCandidate
from mp3sanitizer.ui.track_model import ERROR_COLOR
from mp3sanitizer.ui.workers import FunctionWorker, JobRunner

CANDIDATE_ROLE = Qt.ItemDataRole.UserRole + 30


def _duration(seconds: int | None) -> str:
    return "" if seconds is None else f"{seconds // 60}:{seconds % 60:02d}"


class RecordingDialog(QDialog):
    """Zoekt op artiest + titel; titel, artiest en/of jaar van de gekozen opname overnemen."""

    def __init__(
        self,
        client: MusicBrainzClient,
        artist: str,
        title: str,
        pool: QThreadPool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Track opzoeken op MusicBrainz")
        self.resize(960, 440)
        self._client = client
        self._jobs = JobRunner(pool, self)
        self.chosen: RecordingCandidate | None = None

        self.artist_edit = QLineEdit(artist, self)
        self.title_edit = QLineEdit(title, self)
        self.search_button = QPushButton("&Zoeken", self)
        self.search_button.clicked.connect(self.search)
        for edit in (self.artist_edit, self.title_edit):
            edit.returnPressed.connect(self.search)
        self.status = QLabel(self)
        self.results = QTreeWidget(self)
        self.results.setRootIsDecorated(False)
        self.results.setHeaderLabels(
            ["Titel", "Artiest", "Jaar", "Duur", "Release", "Toelichting", "Score"]
        )
        self.results.header().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.results.setColumnWidth(0, 240)
        self.results.setColumnWidth(1, 200)
        self.results.setColumnWidth(2, 50)
        self.results.setColumnWidth(3, 50)
        self.results.setColumnWidth(4, 180)
        self.results.itemActivated.connect(lambda *_: self.accept())
        self.results.currentItemChanged.connect(lambda *_: self._update_ok())

        self.take_title = QCheckBox("&Titel", self)
        self.take_artist = QCheckBox("A&rtiest", self)
        self.take_year = QCheckBox("&Jaar (eerste release)", self)
        self.take_title.setChecked(True)
        for box in (self.take_title, self.take_artist, self.take_year):
            box.toggled.connect(self._update_ok)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("&Overnemen")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuleren")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        form = QGridLayout()
        form.addWidget(QLabel("&Artiest:", self, buddy=self.artist_edit), 0, 0)
        form.addWidget(self.artist_edit, 0, 1)
        form.addWidget(QLabel("T&itel:", self, buddy=self.title_edit), 1, 0)
        form.addWidget(self.title_edit, 1, 1)
        form.addWidget(self.search_button, 1, 2)
        take = QHBoxLayout()
        take.addWidget(QLabel("Overnemen:", self))
        for box in (self.take_title, self.take_artist, self.take_year):
            take.addWidget(box)
        take.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status)
        layout.addWidget(self.results, 1)
        layout.addWidget(
            QLabel(
                "Alleen opnamen met score ≥ 80. Vergelijk de duur om de juiste versie te kiezen; "
                "het jaar is dat van de eerste release van deze opname.",
                self,
            )
        )
        layout.addLayout(take)
        layout.addWidget(self.buttons)
        self._update_ok()
        if title.strip():
            QTimer.singleShot(0, self.search)

    def search(self) -> None:
        artist, title = self.artist_edit.text(), self.title_edit.text()
        if not title.strip():
            return
        self.status.setStyleSheet("")
        self.status.setText(f"Zoeken naar “{artist} - {title}”… (maximaal 1 verzoek per seconde)")
        self.results.clear()
        self._update_ok()

        def call(a: str = artist, t: str = title) -> object:
            try:
                return self._client.search_recording(a, t)
            except MusicBrainzError as exc:
                return exc

        self._jobs.run("mb", FunctionWorker(call), self._show)

    def _show(self, result: object) -> None:
        if isinstance(result, MusicBrainzError):
            self.status.setStyleSheet(f"color: {ERROR_COLOR.name()}")
            self.status.setText(str(result))
            return
        candidates: Sequence[RecordingCandidate] = result  # type: ignore[assignment]
        self.status.setText(f"{len(candidates)} opnamen" if candidates else "Geen resultaten.")
        for c in candidates:
            item = QTreeWidgetItem(
                [
                    c.title,
                    c.artist,
                    "" if c.year is None else str(c.year),
                    _duration(c.length_s),
                    c.release,
                    c.disambiguation,
                    str(c.score),
                ]
            )
            item.setData(0, CANDIDATE_ROLE, c)
            item.setToolTip(0, f"MBID: {c.mbid}")
            self.results.addTopLevelItem(item)
        if candidates:
            self.results.setCurrentItem(self.results.topLevelItem(0))
            self.results.setFocus()
        self._update_ok()

    def _update_ok(self) -> None:
        item = self.results.currentItem()
        c: RecordingCandidate | None = item.data(0, CANDIDATE_ROLE) if item else None
        self.take_year.setEnabled(c is None or c.year is not None)
        self.take_artist.setEnabled(c is None or bool(c.artist))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            c is not None and bool(self.values())
        )

    def values(self) -> dict[str, str | int]:
        """De over te nemen velden ('title', 'artist', 'year') van de gekozen opname."""
        item = self.results.currentItem()
        c: RecordingCandidate | None = item.data(0, CANDIDATE_ROLE) if item else None
        if c is None:
            return {}
        values: dict[str, str | int] = {}
        if self.take_title.isChecked() and c.title:
            values["title"] = c.title
        if self.take_artist.isChecked() and self.take_artist.isEnabled() and c.artist:
            values["artist"] = c.artist
        if self.take_year.isChecked() and self.take_year.isEnabled() and c.year is not None:
            values["year"] = c.year
        return values

    def accept(self) -> None:
        item = self.results.currentItem()
        if item is None or not self.values():
            return
        self.chosen = item.data(0, CANDIDATE_ROLE)
        self._jobs.cancel_all()
        super().accept()

    def reject(self) -> None:
        self._jobs.cancel_all()
        super().reject()
