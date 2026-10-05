"""Artiestencontrole: alle artiesten (per beginletter) via MusicBrainz nagaan en voorstellen
goedkeuren, aanpassen of negeren.

Het opzoeken gebeurt per track (artiest + titel) op de achtergrond, met maximaal één verzoek per
seconde; eerder opgezochte tracks komen uit de cache. Goedgekeurde en genegeerde artiesten worden
in de instellingen onthouden en de volgende keer overgeslagen.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt, QThreadPool, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mp3sanitizer.core.artist_review import (
    LETTERS,
    ArtistEntry,
    ArtistProposal,
    RecordingSearch,
    Status,
    TrackRef,
    collect,
    letter_counts,
    run_review,
)
from mp3sanitizer.core.normalize import DEFAULT_ARTICLES, fold
from mp3sanitizer.core.settings import Settings
from mp3sanitizer.ui.track_model import ERROR_COLOR, TrackTableModel
from mp3sanitizer.ui.workers import Worker

PROPOSAL_ROLE = Qt.ItemDataRole.UserRole + 40
TRACK_ID_ROLE = Qt.ItemDataRole.UserRole + 41
APPROVED, IGNORED = "approved", "ignored"
_CHECKED_BY_DEFAULT = {Status.OK, Status.PROPOSAL}
_FILTERS: list[tuple[str, set[Status]]] = [
    ("Te beoordelen", {Status.PROPOSAL, Status.SPLIT, Status.DOUBT, Status.NOT_FOUND}),
    ("Alles", set(Status)),
    *[(s.label, {s}) for s in Status],
]


class Col:
    ARTIST, PROPOSAL, STATUS, TRACKS, YEARS = range(5)


class ReviewWorker(Worker):
    """Draait ``run_review``; ``batch`` levert per artiest een ``ArtistProposal``."""

    def __init__(
        self, client: RecordingSearch, entries: Sequence[ArtistEntry], articles: Sequence[str]
    ) -> None:
        super().__init__()
        self.client = client
        self.entries = entries
        self.articles = articles

    def work(self) -> None:
        error = run_review(
            self.client,
            self.entries,
            self.articles,
            on_result=self.signals.batch.emit,
            progress=self.signals.progress.emit,
            cancelled=lambda: self.cancelled,
        )
        if error:
            self.signals.error.emit(error)


def _years(entry: ArtistEntry) -> str:
    span = entry.years
    if span is None:
        return ""
    return str(span[0]) if span[0] == span[1] else f"{span[0]}–{span[1]}"


class ArtistReviewDialog(QDialog):
    def __init__(
        self,
        model: TrackTableModel,
        pool: QThreadPool,
        mb_client_factory: Callable[[], RecordingSearch],
        settings: Settings,
        parent: QWidget | None = None,
        play: Callable[[int], None] | None = None,
        show_track: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Artiesten controleren (MusicBrainz)")
        self.resize(1200, 720)
        self.model = model
        self._pool = pool
        self._client_factory = mb_client_factory
        self._settings = settings
        self._articles = tuple(settings.articles or DEFAULT_ARTICLES)
        self._play = play
        self._show_track = show_track
        self._worker: ReviewWorker | None = None
        self._items: dict[str, QTreeWidgetItem] = {}  # artiestnaam → item

        # --- beginletters ---------------------------------------------------------------
        self.letter_buttons: dict[str, QToolButton] = {}
        letters = QGridLayout()
        letters.setSpacing(2)
        for i, letter in enumerate(LETTERS):
            button = QToolButton(self)
            button.setCheckable(True)
            button.setMinimumWidth(34)
            button.toggled.connect(self._update_selection_label)
            self.letter_buttons[letter] = button
            letters.addWidget(button, 0, i)
        self.include_reviewed = QCheckBox("Ook eerder &beoordeelde artiesten", self)
        self.include_reviewed.toggled.connect(self.refresh_letters)
        self.selection_label = QLabel(self)
        self.start_button = QPushButton("&Controleren", self)
        self.start_button.clicked.connect(self.start)
        self.cancel_button = QPushButton("&Stoppen", self)
        self.cancel_button.clicked.connect(self.stop)
        self.cancel_button.setEnabled(False)
        self.progress = QProgressBar(self)
        self.progress.setVisible(False)
        self.status = QLabel(self)

        # --- resultaten -----------------------------------------------------------------
        self.filter_combo = QComboBox(self)
        for label, _ in _FILTERS:
            self.filter_combo.addItem(label)
        self.filter_combo.currentIndexChanged.connect(self.apply_filter)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["Artiest / track", "Voorstel", "Status", "Tracks", "Jaren"])
        header = self.tree.header()
        header.setSectionResizeMode(Col.ARTIST, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(Col.PROPOSAL, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(Col.STATUS, 140)
        self.tree.setColumnWidth(Col.TRACKS, 60)
        self.tree.setColumnWidth(Col.YEARS, 90)
        self.tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self.tree.itemDoubleClicked.connect(self._edit_proposal)
        self.tree.itemActivated.connect(self._on_activated)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemChanged.connect(self._on_item_changed)

        self.apply_button = QPushButton("&Toepassen op aangevinkte", self)
        self.apply_button.setToolTip(
            "Voorstellen doorvoeren (één undo-stap) en de artiesten als goedgekeurd onthouden"
        )
        self.apply_button.clicked.connect(self.apply_checked)
        self.ignore_button = QPushButton("&Negeren", self)
        self.ignore_button.setToolTip(
            "Aangevinkte artiesten ongewijzigd laten en de volgende keer overslaan"
        )
        self.ignore_button.clicked.connect(self.ignore_checked)
        self.result_label = QLabel(self)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close.button(QDialogButtonBox.StandardButton.Close).setText("Sluiten")
        close.rejected.connect(self.reject)

        top = QHBoxLayout()
        top.addWidget(self.include_reviewed)
        top.addStretch(1)
        top.addWidget(self.selection_label)
        top.addWidget(self.start_button)
        top.addWidget(self.cancel_button)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("&Toon:", self, buddy=self.filter_combo))
        filter_row.addWidget(self.filter_combo)
        filter_row.addStretch(1)
        filter_row.addWidget(self.result_label)
        actions = QHBoxLayout()
        actions.addWidget(
            QLabel("Dubbelklik op een voorstel om het aan te passen; rechtsklik voor meer.", self)
        )
        actions.addStretch(1)
        actions.addWidget(self.ignore_button)
        actions.addWidget(self.apply_button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Kies één of meer beginletters:", self))
        layout.addLayout(letters)
        layout.addLayout(top)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addLayout(filter_row)
        layout.addWidget(self.tree, 1)
        layout.addLayout(actions)
        layout.addWidget(close)
        self.refresh_letters()
        self._update_buttons()

    # --- letters --------------------------------------------------------------------------
    def track_refs(self) -> list[TrackRef]:
        m, e = self.model, self.model.edits
        return [
            TrackRef(t.id, e.artist(t.id), e.title(t.id), e.year(t.id))
            for t in m.tracks
            if not m.is_deleted_id(t.id) and e.artist(t.id).strip()
        ]

    def _skip(self) -> set[str]:
        return set() if self.include_reviewed.isChecked() else set(self._settings.artist_review)

    def refresh_letters(self) -> None:
        refs = self.track_refs()
        remaining = letter_counts(refs, self._articles, skip=self._skip())
        total = letter_counts(refs, self._articles)
        for letter, button in self.letter_buttons.items():
            artists, tracks = remaining[letter]
            done = total[letter][0] > 0 and artists == 0
            button.setText(f"{letter}✓" if done else letter)
            button.setEnabled(artists > 0)
            if not artists:
                button.setChecked(False)
            button.setToolTip(
                "Alles al beoordeeld"
                if done
                else f"{artists} artiesten, {tracks} tracks"
                if artists
                else "Geen artiesten"
            )
        self._counts = remaining
        self._update_selection_label()

    def selected_letters(self) -> list[str]:
        return [letter for letter, b in self.letter_buttons.items() if b.isChecked()]

    def _update_selection_label(self, *_args: object) -> None:
        letters = self.selected_letters()
        artists = sum(self._counts[letter][0] for letter in letters)
        tracks = sum(self._counts[letter][1] for letter in letters)
        if not letters:
            self.selection_label.setText("Geen letters gekozen")
        else:
            minutes = max(1, round(tracks / 60))
            self.selection_label.setText(
                f"{artists} artiesten, {tracks} tracks · hooguit ~{minutes} min "
                "(opgezochte tracks komen uit de cache)"
            )
        self.start_button.setEnabled(bool(letters) and self._worker is None)

    # --- controleren ----------------------------------------------------------------------
    def start(self) -> None:
        letters = self.selected_letters()
        entries = collect(self.track_refs(), self._articles, letters, self._skip())
        if not entries or self._worker is not None:
            return
        self.tree.clear()
        self._items.clear()
        total = len({t.track_id for e in entries for t in e.tracks})
        self.progress.setRange(0, total)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.status.setStyleSheet("")
        self.status.setText(f"Controleren: {len(entries)} artiesten ({', '.join(letters)})…")
        worker = ReviewWorker(self._client_factory(), entries, self._articles)
        worker.signals.batch.connect(self._on_result)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.error.connect(self._on_error)
        worker.signals.finished.connect(self._on_finished)
        self._worker = worker
        self.cancel_button.setEnabled(True)
        self._update_selection_label()
        for button in self.letter_buttons.values():
            button.setEnabled(False)
        self._pool.start(worker)

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status.setText("Stoppen…")

    @Slot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setValue(done)
        self.status.setText(f"{done} van {total} tracks opgezocht")

    @Slot(str)
    def _on_error(self, message: str) -> None:
        self.status.setStyleSheet(f"color: {ERROR_COLOR.name()}")
        self.status.setText(f"Gestopt: {message}")

    @Slot(bool)
    def _on_finished(self, cancelled: bool) -> None:
        self._worker = None
        self.cancel_button.setEnabled(False)
        self.progress.setVisible(False)
        if cancelled:
            self.status.setText("Gestopt; de resultaten tot nu toe staan hieronder.")
        elif not self.status.text().startswith("Gestopt"):
            self.status.setText("Klaar.")
        self.refresh_letters()

    @Slot(object)
    def _on_result(self, proposal: object) -> None:
        assert isinstance(proposal, ArtistProposal)
        self.add_proposal(proposal)

    def add_proposal(self, p: ArtistProposal) -> QTreeWidgetItem:
        entry = p.entry
        top = QTreeWidgetItem(
            [entry.name, p.proposal, p.status.label, str(len(entry.tracks)), _years(entry)]
        )
        top.setData(Col.ARTIST, PROPOSAL_ROLE, p)
        top.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsAutoTristate
        )
        if p.candidates:
            top.setToolTip(
                Col.PROPOSAL,
                "\n".join(
                    f"{c.name} ({len(c.track_ids)} tracks) · MBID {c.mbid}" for c in p.candidates
                ),
            )
        checked = (
            Qt.CheckState.Checked if p.status in _CHECKED_BY_DEFAULT else Qt.CheckState.Unchecked
        )
        for ref in entry.tracks:
            ev = p.evidence.get(ref.track_id)
            found = f"→ {ev.recording} ({ev.year or '?'})" if ev and ev.mbid else "niet gevonden"
            child = QTreeWidgetItem(
                [
                    self.model.track_label(ref.track_id),
                    p.track_proposal(ref.track_id),
                    found,
                    "",
                    "" if ref.year is None else str(ref.year),
                ]
            )
            child.setData(Col.ARTIST, TRACK_ID_ROLE, ref.track_id)
            child.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            child.setCheckState(Col.ARTIST, checked)
            child.setToolTip(Col.ARTIST, f"{self.model.tracks[ref.track_id].path}\nEnter: afspelen")
            top.addChild(child)
        if p.status is Status.NOT_FOUND:
            top.setForeground(Col.STATUS, ERROR_COLOR)
        self.tree.addTopLevelItem(top)
        self._items[entry.name] = top
        self._apply_filter_to(top)
        self._update_buttons()
        return top

    # --- filter en knoppen ----------------------------------------------------------------
    def apply_filter(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            self._apply_filter_to(self.tree.topLevelItem(i))
        self._update_buttons()

    def _apply_filter_to(self, item: QTreeWidgetItem) -> None:
        statuses = _FILTERS[self.filter_combo.currentIndex()][1]
        p: ArtistProposal = item.data(Col.ARTIST, PROPOSAL_ROLE)
        item.setHidden(p.status not in statuses)

    def _visible_tops(self) -> list[QTreeWidgetItem]:
        items = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [item for item in items if not item.isHidden()]

    def _checked_tops(self) -> list[QTreeWidgetItem]:
        return [
            item
            for item in self._visible_tops()
            if item.checkState(Col.ARTIST) != Qt.CheckState.Unchecked
        ]

    def _update_buttons(self) -> None:
        checked = len(self._checked_tops())
        self.apply_button.setEnabled(checked > 0)
        self.ignore_button.setEnabled(checked > 0)
        counts: dict[str, int] = defaultdict(int)
        for i in range(self.tree.topLevelItemCount()):
            p: ArtistProposal = self.tree.topLevelItem(i).data(Col.ARTIST, PROPOSAL_ROLE)
            counts[p.status.label] += 1
        self.result_label.setText(
            " · ".join(f"{label}: {n}" for label, n in counts.items()) or "Nog geen resultaten"
        )

    # --- toepassen en negeren -------------------------------------------------------------
    def apply_checked(self) -> None:
        """Voer de voorstellen van aangevinkte artiesten/tracks door als één undo-stap."""
        renames: dict[str, list[tuple[int, str]]] = defaultdict(list)
        done: list[QTreeWidgetItem] = []
        for top in self._checked_tops():
            p: ArtistProposal = top.data(Col.ARTIST, PROPOSAL_ROLE)
            for j in range(top.childCount()):
                child = top.child(j)
                if child.checkState(Col.ARTIST) != Qt.CheckState.Checked:
                    continue
                new = " ".join(child.text(Col.PROPOSAL).split())
                if new and new != p.entry.name:
                    renames[new].append((child.data(Col.ARTIST, TRACK_ID_ROLE), p.entry.name))
            done.append(top)
        stack = self.model.undo_stack
        if stack is not None and len(renames) > 1:
            stack.beginMacro(f"Artiestencontrole ({len(done)} artiesten)")
        try:
            for new, pairs in renames.items():
                self.model.rename_artist(pairs, new)
        finally:
            if stack is not None and len(renames) > 1:
                stack.endMacro()
        changed = sum(len(pairs) for pairs in renames.values())
        self._remember(done, APPROVED)
        self.status.setStyleSheet("")
        self.status.setText(
            f"{len(done)} artiesten goedgekeurd, {changed} tracks aangepast (Ctrl+Z in het "
            "hoofdvenster maakt dit ongedaan)."
        )

    def ignore_checked(self) -> None:
        items = self._checked_tops()
        self._remember(items, IGNORED)
        self.status.setStyleSheet("")
        self.status.setText(f"{len(items)} artiesten genegeerd; ze worden voortaan overgeslagen.")

    def _remember(self, items: list[QTreeWidgetItem], verdict: str) -> None:
        for item in items:
            p: ArtistProposal = item.data(Col.ARTIST, PROPOSAL_ROLE)
            self._settings.artist_review[fold(p.entry.name)] = verdict
            if verdict == APPROVED:  # de nieuwe schrijfwijze is daarmee ook beoordeeld
                self._settings.artist_review[fold(item.text(Col.PROPOSAL))] = verdict
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
            self._items.pop(p.entry.name, None)
        self._update_buttons()
        if self._worker is None:
            self.refresh_letters()

    # --- voorstel aanpassen, afspelen en tonen --------------------------------------------
    def _edit_proposal(self, item: QTreeWidgetItem, column: int) -> None:
        if column == Col.PROPOSAL:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.tree.editItem(item, Col.PROPOSAL)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        # Een aangepast voorstel op artiestniveau geldt voor al zijn tracks.
        if column == Col.PROPOSAL and item.parent() is None:
            name = item.text(Col.PROPOSAL)
            if any(item.child(j).text(Col.PROPOSAL) != name for j in range(item.childCount())):
                self.set_proposal(item, name)
        self._update_buttons()

    def set_proposal(self, item: QTreeWidgetItem, name: str) -> None:
        """Zet het voorstel van een artiest (en van al zijn tracks)."""
        item.setText(Col.PROPOSAL, name)
        for j in range(item.childCount()):
            item.child(j).setText(Col.PROPOSAL, name)

    def _on_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        tid = item.data(Col.ARTIST, TRACK_ID_ROLE)
        if tid is not None and self._play is not None:
            self._play(tid)

    def _context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        tid = item.data(Col.ARTIST, TRACK_ID_ROLE)
        top = item.parent() or item
        p: ArtistProposal = top.data(Col.ARTIST, PROPOSAL_ROLE)
        target = item if tid is not None else top
        for c in p.candidates:
            action = menu.addAction(f"Voorstel: {c.name} ({len(c.track_ids)} tracks)")
            if tid is not None:
                action.triggered.connect(lambda _=False, n=c.name: target.setText(Col.PROPOSAL, n))
            else:
                action.triggered.connect(lambda _=False, n=c.name: self.set_proposal(top, n))
        keep = menu.addAction("Huidige schrijfwijze behouden")
        if tid is not None:
            keep.triggered.connect(lambda: target.setText(Col.PROPOSAL, p.entry.name))
        else:
            keep.triggered.connect(lambda: self.set_proposal(top, p.entry.name))
        menu.addAction("Voorstel &bewerken…").triggered.connect(
            lambda: self._edit_proposal(target, Col.PROPOSAL)
        )
        if tid is not None:
            menu.addSeparator()
            play = menu.addAction("&Afspelen")
            play.setEnabled(self._play is not None)
            play.triggered.connect(lambda: self._play(tid) if self._play else None)
            show = menu.addAction("&Toon in hoofdvenster")
            show.setEnabled(self._show_track is not None)
            show.triggered.connect(lambda: self._show_track(tid) if self._show_track else None)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # --- afsluiten ------------------------------------------------------------------------
    def reject(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        super().reject()
