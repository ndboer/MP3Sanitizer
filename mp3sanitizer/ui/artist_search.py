"""Artiesten: fuzzy zoeken en in één keer corrigeren, overzicht, clustervoorstellen en MusicBrainz.

Zwaar werk (zoeken, clusteren, MusicBrainz) loopt in ``FunctionWorker``s op de achtergrond.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QObject, Qt, QThreadPool, QTimer, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mp3sanitizer.core.fuzzy import (
    ArtistMatch,
    Cluster,
    cluster_artists,
    search_artists,
)
from mp3sanitizer.core.models import Field
from mp3sanitizer.core.musicbrainz import ArtistCandidate, MusicBrainzClient, MusicBrainzError
from mp3sanitizer.core.normalize import DEFAULT_ARTICLES, natural_key, sort_key
from mp3sanitizer.ui.track_model import ERROR_COLOR, TrackTableModel
from mp3sanitizer.ui.workers import FunctionWorker, Worker

SPELLING_ROLE = Qt.ItemDataRole.UserRole + 20
TRACK_ID_ROLE = Qt.ItemDataRole.UserRole + 21
_CHECKABLE = (
    Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
)


class _ArtistItem(QTreeWidgetItem):
    """Sorteert kolom 0 op de artiest-sorteersleutel ('The Beatles' bij de B)."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 0
        if column == 0:
            return natural_key(sort_key(self.text(0))) < natural_key(sort_key(other.text(0)))
        return super().__lt__(other)


class _Jobs(QObject):
    """Houdt achtergrondtaken vast en negeert resultaten van verouderde aanvragen."""

    def __init__(self, pool: QThreadPool, parent: QObject) -> None:
        super().__init__(parent)
        self._pool = pool
        self._current: dict[str, Worker] = {}
        # signals-object -> (naam, worker, callback); ook bewaard zodat Python ze vasthoudt.
        self._running: dict[QObject, tuple[str, Worker, Callable[[object], None]]] = {}

    def run(self, name: str, worker: FunctionWorker, on_result: Callable[[object], None]) -> None:
        old = self._current.get(name)
        if old is not None:
            old.cancel()
        self._current[name] = worker
        self._running[worker.signals] = (name, worker, on_result)
        # Koppelen aan slots van dit QObject: Qt verbreekt de verbinding als het dialoog
        # (en daarmee dit object) wordt opgeruimd terwijl de worker nog loopt.
        worker.signals.batch.connect(self._on_batch)
        worker.signals.finished.connect(self._on_finished)
        self._pool.start(worker)

    @Slot(object)
    def _on_batch(self, result: object) -> None:
        entry = self._running.get(self.sender())
        if entry is not None:
            name, worker, callback = entry
            if self._current.get(name) is worker:
                callback(result)

    @Slot(bool)
    def _on_finished(self, _cancelled: bool) -> None:
        self._running.pop(self.sender(), None)

    def busy(self, name: str) -> bool:
        worker = self._current.get(name)
        return worker is not None and any(w is worker for _, w, _ in self._running.values())

    def cancel_all(self) -> None:
        for _, worker, _ in self._running.values():
            worker.cancel()


class MusicBrainzDialog(QDialog):
    """Zoekt een artiest op MusicBrainz en laat een kandidaat kiezen (officiële naam)."""

    def __init__(
        self, client: MusicBrainzClient, name: str, pool: QThreadPool, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Opzoeken op MusicBrainz")
        self.resize(820, 380)
        self._client = client
        self._jobs = _Jobs(pool, self)
        self.chosen: ArtistCandidate | None = None

        self.query_edit = QLineEdit(name, self)
        self.search_button = QPushButton("&Zoeken", self)
        self.search_button.clicked.connect(self.search)
        self.query_edit.returnPressed.connect(self.search)
        self.status = QLabel(self)
        self.results = QTreeWidget(self)
        self.results.setRootIsDecorated(False)
        self.results.setHeaderLabels(["Naam", "Sort-name", "Land", "Toelichting", "Score"])
        self.results.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.results.setColumnWidth(0, 220)
        self.results.setColumnWidth(1, 200)
        self.results.itemActivated.connect(lambda *_: self.accept())
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Naam &gebruiken")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuleren")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        top = QHBoxLayout()
        top.addWidget(QLabel("&Artiest:", self, buddy=self.query_edit))
        top.addWidget(self.query_edit, 1)
        top.addWidget(self.search_button)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.status)
        layout.addWidget(self.results, 1)
        layout.addWidget(
            QLabel(
                "Alleen kandidaten met score ≥ 80. De officiële naam wordt "
                "ingevuld, niet de sort-name.",
                self,
            )
        )
        layout.addWidget(self.buttons)
        self._update_ok()
        if name.strip():
            QTimer.singleShot(0, self.search)

    def search(self) -> None:
        name = self.query_edit.text()
        if not name.strip():
            return
        self.status.setStyleSheet("")
        self.status.setText(f"Zoeken naar “{name}”… (maximaal 1 verzoek per seconde)")
        self.results.clear()
        self._update_ok()

        def call(query: str = name) -> object:
            try:
                return self._client.search_artist(query)
            except MusicBrainzError as exc:
                return exc

        self._jobs.run("mb", FunctionWorker(call), self._show)

    def _show(self, result: object) -> None:
        if isinstance(result, MusicBrainzError):
            self.status.setStyleSheet(f"color: {ERROR_COLOR.name()}")
            self.status.setText(str(result))
            return
        candidates: Sequence[ArtistCandidate] = result  # type: ignore[assignment]
        self.status.setText(f"{len(candidates)} kandidaten")
        for c in candidates:
            item = QTreeWidgetItem(
                [c.name, c.sort_name, c.country, c.disambiguation or c.type, str(c.score)]
            )
            item.setData(0, SPELLING_ROLE, c)
            item.setToolTip(0, f"MBID: {c.mbid}")
            self.results.addTopLevelItem(item)
        if candidates:
            self.results.setCurrentItem(self.results.topLevelItem(0))
            self.results.setFocus()
        self._update_ok()

    def _update_ok(self) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.results.topLevelItemCount() > 0
        )

    def accept(self) -> None:
        item = self.results.currentItem()
        if item is None:
            return
        self.chosen = item.data(0, SPELLING_ROLE)
        self._jobs.cancel_all()
        super().accept()

    def reject(self) -> None:
        self._jobs.cancel_all()
        super().reject()


class ArtistDialog(QDialog):
    """Tabblad 'Zoeken' (fuzzy, groepen per schrijfwijze) en 'Overzicht & voorstellen'."""

    def __init__(
        self,
        model: TrackTableModel,
        pool: QThreadPool,
        mb_client_factory: Callable[[], MusicBrainzClient],
        threshold: int = 85,
        articles: Sequence[str] = DEFAULT_ARTICLES,
        query: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Artiesten zoeken en corrigeren")
        self.resize(1100, 680)
        self.model = model
        self._pool = pool
        self._mb_factory = mb_client_factory
        self._articles = tuple(articles)
        self._jobs = _Jobs(pool, self)
        self._index: dict[str, list[int]] = {}

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_search_tab(threshold, query), "&Zoeken")
        self.tabs.addTab(self._build_overview_tab(), "&Overzicht en voorstellen")
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close.button(QDialogButtonBox.StandardButton.Close).setText("Sluiten")
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(close)
        self.refresh()
        self.query_edit.setFocus()

    # --- opbouw --------------------------------------------------------------------------
    def _build_search_tab(self, threshold: int, query: str) -> QWidget:
        tab = QWidget(self)
        self.query_edit = QLineEdit(query, tab)
        self.query_edit.setPlaceholderText(
            "Artiest (fuzzy: hoofdletters, accenten, lidwoorden, & …)"
        )
        self.query_edit.setClearButtonEnabled(True)
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal, tab)
        self.threshold_slider.setRange(50, 100)
        self.threshold_slider.setValue(threshold)
        self.threshold_slider.setMaximumWidth(180)
        self.threshold_label = QLabel(tab)
        self._search_timer = QTimer(self, singleShot=True, interval=250)
        self._search_timer.timeout.connect(self.run_search)
        self.query_edit.textChanged.connect(lambda _: self._search_timer.start())
        self.threshold_slider.valueChanged.connect(self._on_threshold)

        self.results = QTreeWidget(tab)
        self.results.setHeaderLabels(["Schrijfwijze / track", "Tracks", "Score"])
        self.results.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results.itemChanged.connect(lambda *_: self._update_apply_button())

        self.correct_edit = QLineEdit(tab)
        self.correct_edit.setPlaceholderText("Juiste schrijfwijze")
        self.correct_edit.textChanged.connect(lambda _: self._update_apply_button())
        self.mb_button = QPushButton("Opzoeken op &MusicBrainz…", tab)
        self.mb_button.clicked.connect(self.lookup_musicbrainz)
        self.apply_button = QPushButton("&Toepassen", tab)
        self.apply_button.clicked.connect(self.apply_search)
        self.search_status = QLabel(tab)

        top = QHBoxLayout()
        top.addWidget(QLabel("&Zoek:", tab, buddy=self.query_edit))
        top.addWidget(self.query_edit, 1)
        top.addWidget(QLabel("&Drempel:", tab, buddy=self.threshold_slider))
        top.addWidget(self.threshold_slider)
        top.addWidget(self.threshold_label)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("&Juiste schrijfwijze:", tab, buddy=self.correct_edit))
        bottom.addWidget(self.correct_edit, 1)
        bottom.addWidget(self.mb_button)
        bottom.addWidget(self.apply_button)
        layout = QVBoxLayout(tab)
        layout.addLayout(top)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.search_status)
        layout.addLayout(bottom)
        self._on_threshold(threshold, search=False)
        return tab

    def _build_overview_tab(self) -> QWidget:
        tab = QWidget(self)
        self.overview = QTreeWidget(tab)
        self.overview.setRootIsDecorated(False)
        self.overview.setHeaderLabels(["Artiest", "Tracks"])
        self.overview.setSortingEnabled(True)
        self.overview.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.overview.itemActivated.connect(self._search_from_overview)

        self.clusters = QTreeWidget(tab)
        self.clusters.setHeaderLabels(["Voorstel / schrijfwijze", "Tracks"])
        self.clusters.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.clusters.currentItemChanged.connect(self._on_cluster_selected)
        self.clusters.itemChanged.connect(lambda *_: self._update_cluster_button())
        self.cluster_status = QLabel(tab)
        self.cluster_edit = QLineEdit(tab)
        self.cluster_edit.setPlaceholderText("Schrijfwijze voor dit cluster")
        self.cluster_apply = QPushButton("Toepassen op &cluster", tab)
        self.cluster_apply.clicked.connect(self.apply_cluster)

        left = QWidget(tab)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Alle artiesten (Enter: zoeken op deze artiest):", left))
        lv.addWidget(self.overview, 1)
        right = QWidget(tab)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("Waarschijnlijk dezelfde artiest:", right))
        rv.addWidget(self.clusters, 1)
        rv.addWidget(self.cluster_status)
        row = QHBoxLayout()
        row.addWidget(self.cluster_edit, 1)
        row.addWidget(self.cluster_apply)
        rv.addLayout(row)
        splitter = QSplitter(tab)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([400, 650])
        layout = QVBoxLayout(tab)
        layout.addWidget(splitter)
        return tab

    # --- gegevens ------------------------------------------------------------------------
    def refresh(self) -> None:
        """Lees de (effectieve) artiesten opnieuw uit het model en werk alles bij."""
        self._index = self.model.artist_index()
        counts = {a: len(ids) for a, ids in self._index.items()}
        self.overview.setSortingEnabled(False)
        self.overview.clear()
        for artist, n in counts.items():
            item = _ArtistItem([artist, ""])
            item.setData(1, Qt.ItemDataRole.DisplayRole, n)
            self.overview.addTopLevelItem(item)
        self.overview.setSortingEnabled(True)
        self.overview.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.run_search()
        self.run_clusters(counts)

    def counts(self) -> dict[str, int]:
        return {a: len(ids) for a, ids in self._index.items()}

    # --- zoeken --------------------------------------------------------------------------
    def _on_threshold(self, value: int, search: bool = True) -> None:
        self.threshold_label.setText(str(value))
        if search:
            self._search_timer.start()

    def run_search(self) -> None:
        query = self.query_edit.text()
        if not query.strip():
            self.results.clear()
            self.search_status.setText("Typ een artiest om te zoeken.")
            self._update_apply_button()
            return
        worker = FunctionWorker(
            search_artists, query, self.counts(), self.threshold_slider.value(), self._articles
        )
        self._jobs.run("search", worker, self._show_search)

    @Slot(object)
    def _show_search(self, result: object) -> None:
        matches: list[ArtistMatch] = result  # type: ignore[assignment]
        self.results.blockSignals(True)
        self.results.clear()
        total = 0
        for m in matches:
            group = QTreeWidgetItem([m.spelling, str(m.count), f"{m.score:.0f}"])
            group.setFlags(_CHECKABLE | Qt.ItemFlag.ItemIsAutoTristate)
            group.setCheckState(0, Qt.CheckState.Checked)
            group.setData(0, SPELLING_ROLE, m.spelling)
            group.setText(0, f"{m.spelling} ({m.count})")  # bijv. "Beatles, The (3)"
            for tid in self._index.get(m.spelling, []):
                child = QTreeWidgetItem([self.model.track_label(tid), "", ""])
                child.setFlags(_CHECKABLE)
                child.setCheckState(0, Qt.CheckState.Checked)
                child.setData(0, TRACK_ID_ROLE, tid)
                child.setToolTip(0, str(self.model.tracks[tid].path))
                group.addChild(child)
            self.results.addTopLevelItem(group)
            total += m.count
        self.results.blockSignals(False)
        self.search_status.setText(
            f"{len(matches)} schrijfwijzen, {total} tracks" if matches else "Geen resultaten."
        )
        if matches and not self.correct_edit.isModified():
            self.correct_edit.setText(matches[0].spelling)  # meestgebruikte beste match
        self._update_apply_button()

    def checked_track_ids(self) -> list[int]:
        ids = []
        for i in range(self.results.topLevelItemCount()):
            group = self.results.topLevelItem(i)
            for j in range(group.childCount()):
                child = group.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    ids.append(child.data(0, TRACK_ID_ROLE))
        return ids

    def _update_apply_button(self) -> None:
        n = len(self.checked_track_ids())
        self.apply_button.setText(f"&Toepassen op {n} tracks")
        self.apply_button.setEnabled(n > 0 and bool(self.correct_edit.text().strip()))

    def apply_search(self) -> None:
        value = " ".join(self.correct_edit.text().split())
        ids = self.checked_track_ids()
        if value and ids and self.model.set_field(ids, Field.ARTIST, value):
            self.search_status.setText(f"{len(ids)} tracks aangepast naar “{value}”.")
        self.correct_edit.setModified(False)
        self.refresh()

    def lookup_musicbrainz(self) -> None:
        name = self.correct_edit.text().strip() or self.query_edit.text().strip()
        dialog = MusicBrainzDialog(self._mb_factory(), name, self._pool, self)
        if dialog.exec() and dialog.chosen is not None:
            self.correct_edit.setText(dialog.chosen.name)
            self.correct_edit.setModified(True)
            self._update_apply_button()

    def _search_from_overview(self, item: QTreeWidgetItem) -> None:
        self.query_edit.setText(item.text(0))
        self.correct_edit.setModified(False)
        self.tabs.setCurrentIndex(0)
        self.query_edit.setFocus()

    # --- clusters ------------------------------------------------------------------------
    def run_clusters(self, counts: dict[str, int]) -> None:
        self.cluster_status.setText("Voorstellen berekenen…")
        worker = FunctionWorker(
            cluster_artists,
            counts,
            self.threshold_slider.value(),
            self._articles,
            pass_cancel=True,
        )
        self._jobs.run("clusters", worker, self._show_clusters)

    @Slot(object)
    def _show_clusters(self, result: object) -> None:
        clusters: list[Cluster] = result  # type: ignore[assignment]
        self.clusters.blockSignals(True)
        self.clusters.clear()
        for c in clusters:
            top = QTreeWidgetItem([c.suggestion, str(c.total)])
            top.setFlags(_CHECKABLE | Qt.ItemFlag.ItemIsAutoTristate)
            top.setData(0, SPELLING_ROLE, c.suggestion)
            for spelling, n in c.members:
                child = QTreeWidgetItem([spelling, str(n)])
                child.setFlags(_CHECKABLE)
                child.setCheckState(0, Qt.CheckState.Checked)
                child.setData(0, SPELLING_ROLE, spelling)
                top.addChild(child)
            self.clusters.addTopLevelItem(top)
        self.clusters.blockSignals(False)
        self.cluster_status.setText(
            f"{len(clusters)} voorstellen" if clusters else "Geen voorstellen gevonden."
        )
        if clusters:
            self.clusters.setCurrentItem(self.clusters.topLevelItem(0))
        self._update_cluster_button()

    def _on_cluster_selected(self, current: QTreeWidgetItem | None, _prev: object) -> None:
        if current is None:
            return
        top = current.parent() or current
        self.cluster_edit.setText(top.data(0, SPELLING_ROLE))
        self._update_cluster_button()

    def _current_cluster(self) -> QTreeWidgetItem | None:
        item = self.clusters.currentItem()
        return (item.parent() or item) if item else None

    def cluster_track_ids(self) -> list[int]:
        top = self._current_cluster()
        if top is None:
            return []
        ids: list[int] = []
        for j in range(top.childCount()):
            child = top.child(j)
            if child.checkState(0) == Qt.CheckState.Checked:
                ids.extend(self._index.get(child.data(0, SPELLING_ROLE), []))
        return ids

    def _update_cluster_button(self) -> None:
        n = len(self.cluster_track_ids())
        self.cluster_apply.setText(f"Toepassen op &cluster ({n} tracks)")
        self.cluster_apply.setEnabled(n > 0 and bool(self.cluster_edit.text().strip()))

    def apply_cluster(self) -> None:
        value = " ".join(self.cluster_edit.text().split())
        ids = self.cluster_track_ids()
        if value and ids:
            self.model.set_field(ids, Field.ARTIST, value)
        self.refresh()

    def done(self, result: int) -> None:
        self._jobs.cancel_all()
        super().done(result)
