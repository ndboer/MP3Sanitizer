"""Hoofdvenster."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QObject, Qt, QThreadPool, QTimer, Slot
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QKeyEvent,
    QKeySequence,
    QUndoStack,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from mp3sanitizer import __version__
from mp3sanitizer.core.deleter import DeleteItem, DeleteResult, Trash
from mp3sanitizer.core.executor import ExecResult
from mp3sanitizer.core.journal import Journal, JournalStore
from mp3sanitizer.core.models import Field, ParseStatus, RenamePlan
from mp3sanitizer.core.paths import data_dir
from mp3sanitizer.core.planner import DecadeStyle, FolderTemplate, PlanInput, folder_for_year
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.ui.bulk_edit_dialog import BulkEditDialog
from mp3sanitizer.ui.delegates import TrackEditDelegate
from mp3sanitizer.ui.delete_dialog import DeleteDialog
from mp3sanitizer.ui.player import SEEK_STEP_MS, MiniPlayer, Player, next_in_selection
from mp3sanitizer.ui.proxy_model import QuickFilter, TrackFilterProxy
from mp3sanitizer.ui.save_dialog import SavePreviewDialog, relative
from mp3sanitizer.ui.track_model import FIELD_COLUMN, Col, TrackTableModel
from mp3sanitizer.ui.workers import (
    DeleteWorker,
    SaveWorker,
    ScanWorker,
    TagWorker,
    UndoWorker,
    Worker,
    WorkerSignals,
)

log = logging.getLogger(__name__)

APP_TITLE = "Mp3Sanitizer"

_DEFAULT_WIDTHS = {
    Col.STATUS: 150,
    Col.ARTIST: 220,
    Col.TITLE: 300,
    Col.YEAR: 55,
    Col.FOLDER: 140,
    Col.FILENAME: 360,
    Col.DURATION: 60,
    Col.BITRATE: 75,
    Col.SIZE: 75,
    Col.TAG_ARTIST: 180,
    Col.TAG_TITLE: 220,
    Col.TAG_YEAR: 65,
    Col.PLAY: 30,
}


class MainWindow(QMainWindow):
    def __init__(
        self,
        store: SettingsStore,
        pool: QThreadPool | None = None,
        journal_store: JournalStore | None = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._settings = store.settings
        self._pool = pool or QThreadPool.globalInstance()
        self.journals = journal_store or JournalStore(data_dir() / "journal")
        self._batch_worker: SaveWorker | UndoWorker | DeleteWorker | None = None
        # None = echte Prullenbak (send2trash); tests vervangen dit.
        self.trash_function: Trash | None = None
        self.last_report = ""
        self._reload_after_batch = False
        self._root: Path | None = None
        # Actieve workers per signals-object; oude workers blijven bewaard tot ze klaar zijn.
        self._workers: dict[WorkerSignals, Worker] = {}
        self._scan_worker: ScanWorker | None = None
        self._tag_worker: TagWorker | None = None

        self.undo_stack = QUndoStack(self)
        self.model = TrackTableModel(self._settings.articles, self)
        self.model.undo_stack = self.undo_stack
        self.proxy = TrackFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView(self)
        self._setup_table()
        self.player = Player(self)
        self.mini_player = MiniPlayer(self.player, self)
        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.table, 1)
        central_layout.addWidget(self.mini_player)
        self.setCentralWidget(central)

        self._stats_timer = QTimer(self, singleShot=True, interval=100)
        self._stats_timer.timeout.connect(self._update_stats)
        self._search_timer = QTimer(self, singleShot=True, interval=200)
        self._search_timer.timeout.connect(self._apply_search)
        # Na een bewerking de filters opnieuw toepassen, maar pas als de editor gesloten is.
        self._refilter_timer = QTimer(self, singleShot=True, interval=0)
        self._refilter_timer.timeout.connect(self._refilter)

        self._build_actions()
        self._build_toolbar()
        self._build_menus()
        self._build_statusbar()
        self._restore_view_state()
        self._connect_model_signals()
        self._update_title()
        self._update_stats()
        self._set_busy(False)
        self._apply_folder_rule()

        if self._settings.last_root and Path(self._settings.last_root).is_dir():
            QTimer.singleShot(0, lambda: self.start_scan(Path(self._settings.last_root or "")))

    # --- opbouw --------------------------------------------------------------------------
    def _setup_table(self) -> None:
        t = self.table
        t.setModel(self.proxy)
        t.setItemDelegate(TrackEditDelegate(t))
        t.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t.customContextMenuRequested.connect(self._show_row_menu)
        t.setSortingEnabled(True)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        t.setAlternatingRowColors(True)
        t.setWordWrap(False)
        t.setTextElideMode(Qt.TextElideMode.ElideRight)
        t.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        vh = t.verticalHeader()
        vh.setVisible(False)
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vh.setDefaultSectionSize(t.fontMetrics().height() + 8)
        hh = t.horizontalHeader()
        hh.setSectionsMovable(True)
        hh.setHighlightSections(False)
        hh.setStretchLastSection(True)
        hh.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hh.customContextMenuRequested.connect(
            lambda pos: self._columns_menu.exec(hh.mapToGlobal(pos))
        )
        for col, width in _DEFAULT_WIDTHS.items():
            t.setColumnWidth(col, width)
        t.sortByColumn(Col.ARTIST, Qt.SortOrder.AscendingOrder)
        t.clicked.connect(self._on_table_clicked)

    def _build_actions(self) -> None:
        self.act_open = QAction("Map &openen…", self, shortcut=QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self.choose_folder)
        self.act_reload = QAction("&Herlaad", self, shortcut=QKeySequence("F5"))
        self.act_reload.setToolTip("Map opnieuw inlezen en externe wijzigingen oppikken (F5)")
        self.act_reload.triggered.connect(self.reload)
        self.act_cancel = QAction("Taak &annuleren", self, shortcut=QKeySequence("Esc"))
        self.act_cancel.triggered.connect(self.cancel_tasks)
        self.act_quit = QAction("&Afsluiten", self, shortcut=QKeySequence("Alt+F4"))
        self.act_quit.triggered.connect(self.close)
        self.act_find = QAction("&Zoeken", self, shortcut=QKeySequence.StandardKey.Find)
        self.act_find.triggered.connect(self._focus_search)

        self.act_undo = self.undo_stack.createUndoAction(self, "&Ongedaan maken")
        self.act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self.act_redo = self.undo_stack.createRedoAction(self, "Opnieuw &uitvoeren")
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.act_edit = QAction("&Bewerken", self, shortcut=QKeySequence("F2"))
        self.act_edit.setToolTip("Huidige cel bewerken (F2 of dubbelklik)")
        self.act_edit.triggered.connect(self.edit_current)
        self.act_bulk = QAction("Bul&k bewerken…", self, shortcut=QKeySequence("Ctrl+B"))
        self.act_bulk.setToolTip("Eén veld voor alle geselecteerde tracks invullen (Ctrl+B)")
        self.act_bulk.triggered.connect(self.bulk_edit)
        self.act_swap = QAction("&Wissel artiest ⇄ titel", self, shortcut=QKeySequence("Ctrl+W"))
        self.act_swap.triggered.connect(self.swap_selected)
        self.act_revert = QAction("&Terugdraaien", self, shortcut=QKeySequence("Ctrl+R"))
        self.act_revert.setToolTip("Wijzigingen van de geselecteerde tracks terugdraaien (Ctrl+R)")
        self.act_revert.triggered.connect(self.revert_selected)
        self.act_revert_all = QAction("Alle wijzigingen &verwerpen", self)
        self.act_revert_all.triggered.connect(self.revert_all)
        self.act_save = QAction("&Opslaan…", self, shortcut=QKeySequence.StandardKey.Save)
        self.act_save.setToolTip("Hernoemen/verplaatsen via een preview (Ctrl+S)")
        self.act_save.triggered.connect(self.save_changes)
        self.act_undo_batch = QAction("Laatste batch &terugdraaien…", self)
        self.act_undo_batch.triggered.connect(self.undo_last_batch)
        self.act_delete = QAction("&Verwijderen…", self, shortcut=QKeySequence.StandardKey.Delete)
        self.act_delete.setToolTip("Geselecteerde bestanden naar de Prullenbak (Del)")
        # Alleen als de tabel zelf de focus heeft: in een editor wist Del gewoon tekens.
        self.act_delete.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.act_delete.triggered.connect(self.delete_selected)
        self.table.addAction(self.act_delete)
        self.act_play = QAction("&Afspelen / stoppen", self)
        self.act_play.setShortcut(QKeySequence("Space"))
        # De spatiebalk zelf loopt via eventFilter; de sneltoets hier is alleen ter info
        # in het menu en werkt nergens anders.
        self.act_play.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.act_play.triggered.connect(lambda: self.toggle_play())
        self.act_stop = QAction("S&toppen", self, shortcut=QKeySequence("Ctrl+."))
        self.act_stop.triggered.connect(self.stop_playback)
        self.act_seek_back = QAction("5 s &terug", self, shortcut=QKeySequence("Alt+Left"))
        self.act_seek_back.triggered.connect(lambda: self.player.seek_relative(-SEEK_STEP_MS))
        self.act_seek_fwd = QAction("5 s &vooruit", self, shortcut=QKeySequence("Alt+Right"))
        self.act_seek_fwd.triggered.connect(lambda: self.player.seek_relative(SEEK_STEP_MS))
        for act in (self.act_stop, self.act_seek_back, self.act_seek_fwd):
            self.addAction(act)
        for act in (self.act_edit, self.act_bulk, self.act_swap, self.act_revert):
            # Alleen actief als de tabel (of een editor daarin) de focus heeft, zodat
            # bijv. Ctrl+W niet vanuit het zoekveld een wissel uitvoert.
            act.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.table.addAction(act)

        self.filter_group = QActionGroup(self)
        self.filter_actions: dict[QuickFilter, QAction] = {}
        for i, qf in enumerate(QuickFilter, start=1):
            act = QAction(qf.label, self, checkable=True, shortcut=QKeySequence(f"Ctrl+{i}"))
            act.setData(qf.value)
            act.triggered.connect(lambda _=False, f=qf: self.set_quick_filter(f))
            self.filter_group.addAction(act)
            self.filter_actions[qf] = act
        self.filter_actions[QuickFilter.ALL].setChecked(True)

        self.column_actions: dict[Col, QAction] = {}
        for col in Col:
            if not col.optional:
                continue
            act = QAction(col.header, self, checkable=True)
            act.toggled.connect(lambda on, c=col: self._set_column_visible(c, on))
            self.column_actions[col] = act

    def _build_toolbar(self) -> None:
        tb = QToolBar("Werkbalk", self)
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        tb.addAction(self.act_open)
        tb.addAction(self.act_reload)
        tb.addSeparator()
        tb.addWidget(QLabel(" Filter: "))
        self.filter_combo = QComboBox(self)
        for qf in QuickFilter:
            self.filter_combo.addItem(qf.label, qf.value)
        self.filter_combo.setToolTip(f"Snelfilter (Ctrl+1 … Ctrl+{len(QuickFilter)})")
        self.filter_combo.currentIndexChanged.connect(
            lambda i: self.set_quick_filter(QuickFilter(self.filter_combo.itemData(i)))
        )
        tb.addWidget(self.filter_combo)
        tb.addSeparator()
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Zoeken in artiest, titel, bestandsnaam (Ctrl+F)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(240)
        self.search_edit.textChanged.connect(lambda _: self._search_timer.start())
        self.search_edit.installEventFilter(self)
        tb.addWidget(self.search_edit)
        self.addToolBar(tb)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m_file = mb.addMenu("&Bestand")
        m_file.addAction(self.act_open)
        m_file.addAction(self.act_reload)
        m_file.addSeparator()
        m_file.addAction(self.act_save)
        m_file.addAction(self.act_undo_batch)
        m_file.addSeparator()
        m_file.addAction(self.act_cancel)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

        m_edit = mb.addMenu("Be&werken")
        m_edit.addAction(self.act_undo)
        m_edit.addAction(self.act_redo)
        m_edit.addSeparator()
        self._add_row_actions(m_edit)
        m_edit.addSeparator()
        m_edit.addAction(self.act_revert_all)

        m_play = mb.addMenu("&Afspelen")
        m_play.addAction(self.act_play)
        m_play.addAction(self.act_stop)
        m_play.addAction(self.act_seek_back)
        m_play.addAction(self.act_seek_fwd)

        m_view = mb.addMenu("Beel&d")
        m_view.addAction(self.act_find)
        m_filter = m_view.addMenu("&Filter")
        m_filter.addActions(list(self.filter_actions.values()))
        self._columns_menu = QMenu("&Kolommen", self)
        self._columns_menu.addActions(list(self.column_actions.values()))
        m_view.addMenu(self._columns_menu)

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.stats_label = QLabel(self)
        sb.addWidget(self.stats_label, 1)
        # Eigen meldingenlabel: QStatusBar.showMessage zou de tellers links verbergen.
        self.message_label = QLabel(self)
        sb.addPermanentWidget(self.message_label)
        self._message_timer = QTimer(self, singleShot=True)
        self._message_timer.timeout.connect(self.message_label.clear)
        self.task_label = QLabel(self)
        sb.addPermanentWidget(self.task_label)
        self.progress = QProgressBar(self)
        self.progress.setMaximumWidth(220)
        self.progress.setTextVisible(True)
        sb.addPermanentWidget(self.progress)
        self.cancel_button = QPushButton("Annuleren", self)
        self.cancel_button.setToolTip("Lopende taak annuleren (Esc)")
        self.cancel_button.clicked.connect(self.cancel_tasks)
        sb.addPermanentWidget(self.cancel_button)

    def _connect_model_signals(self) -> None:
        for signal in (
            self.proxy.rowsInserted,
            self.proxy.rowsRemoved,
            self.proxy.modelReset,
            self.proxy.layoutChanged,
        ):
            signal.connect(self._schedule_stats)
        self.table.selectionModel().selectionChanged.connect(self._schedule_stats)
        self.model.editsApplied.connect(self._refilter_timer.start)
        self.model.editRejected.connect(lambda msg: self._flash(msg, 8000))
        self._setup_player()
        # Spatie = afspelen; via een eventfilter omdat de tabel spatie anders zelf claimt.
        # Pas hier installeren: de filter gebruikt ook het zoekveld.
        self.table.installEventFilter(self)

    # --- weergave-instellingen -----------------------------------------------------------
    def _restore_view_state(self) -> None:
        s = self._settings
        if s.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(s.window_geometry.encode("ascii")))
        else:
            self.resize(1400, 800)
        if s.header_state:
            self.table.horizontalHeader().restoreState(
                QByteArray.fromBase64(s.header_state.encode("ascii"))
            )
        visible = set(s.visible_columns)
        for col in Col:
            if col.optional:
                act = self.column_actions[col]
                act.setChecked(col.key in visible)
                self.table.setColumnHidden(col, col.key not in visible)
            else:
                self.table.setColumnHidden(col, False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(Col.PLAY, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(Col.PLAY, _DEFAULT_WIDTHS[Col.PLAY])
        hh.moveSection(hh.visualIndex(Col.PLAY), 0)

    def _save_view_state(self) -> None:
        s = self._settings
        s.window_geometry = bytes(self.saveGeometry().toBase64().data()).decode("ascii")
        s.header_state = bytes(self.table.horizontalHeader().saveState().toBase64().data()).decode(
            "ascii"
        )
        s.visible_columns = [c.key for c in Col if not self.table.isColumnHidden(c)]
        s.volume = self.mini_player.volume_slider.value()
        s.autoplay_next = self.mini_player.autoplay.isChecked()

    def _set_column_visible(self, col: Col, visible: bool) -> None:
        self.table.setColumnHidden(col, not visible)
        if visible and self.table.columnWidth(col) < 20:
            self.table.setColumnWidth(col, _DEFAULT_WIDTHS[col])
        self._settings.visible_columns = [c.key for c in Col if not self.table.isColumnHidden(c)]

    def _update_title(self) -> None:
        title = f"{APP_TITLE} {__version__}"
        if self._root is not None:
            title += f" — {self._root}"
        self.setWindowTitle(title)

    # --- filters -------------------------------------------------------------------------
    def set_quick_filter(self, value: QuickFilter) -> None:
        self.proxy.set_quick_filter(value)
        self.filter_actions[value].setChecked(True)
        index = self.filter_combo.findData(value.value)
        if index != self.filter_combo.currentIndex():
            self.filter_combo.setCurrentIndex(index)
        self._schedule_stats()

    def _apply_search(self) -> None:
        self.proxy.set_text_filter(self.search_edit.text())
        self._schedule_stats()

    def _focus_search(self) -> None:
        self.search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_edit.selectAll()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # Esc in het zoekveld: leegmaken en terug naar de tabel (in plaats van 'annuleren').
        if (
            watched is self.search_edit
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
        ):
            event.accept()  # ShortcutOverride accepteren: Esc gaat naar het zoekveld
            if event.type() == QEvent.Type.KeyPress:
                self.search_edit.clear()
                self.table.setFocus(Qt.FocusReason.ShortcutFocusReason)
                return True
        if (
            watched is self.table
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Space
            and not event.modifiers()
            and self.table.state() != QAbstractItemView.State.EditingState
        ):
            self.toggle_play()
            return True
        return super().eventFilter(watched, event)

    # --- statusbalk ----------------------------------------------------------------------
    @Slot()
    def _schedule_stats(self) -> None:
        self._stats_timer.start()

    def _update_stats(self) -> None:
        total = self.model.live_count()
        visible = self.proxy.rowCount()
        selected = len(self.table.selectionModel().selectedRows())
        errors = self.model.parse_error_count()
        parts = [f"Totaal: {total}"]
        if visible != total:
            parts.append(f"Zichtbaar: {visible}")
        parts += [
            f"Geselecteerd: {selected}",
            f"Gewijzigd: {self.model.changed_count()}",
            f"Parse-fouten: {errors}",
        ]
        self.stats_label.setText("   ".join(parts))

    def _flash(self, text: str, msecs: int = 5000) -> None:
        self.message_label.setText(text)
        self._message_timer.start(msecs)

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.task_label.setText(text)
        self.task_label.setVisible(busy)
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)
        self.act_cancel.setEnabled(busy)

    # --- verwijderen ---------------------------------------------------------------------
    def delete_selected(self) -> None:
        if self._root is None or not self._ensure_idle():
            return
        ids = [i for i in self.selected_track_ids() if not self.model.is_deleted_id(i)]
        if not ids:
            return
        root = self._root
        paths = [relative(self.model.tracks[i].path, root) for i in ids]
        dialog = DeleteDialog(paths, self)
        if not dialog.exec():
            return
        self.start_delete(ids, dialog.is_permanent)

    def start_delete(self, track_ids: list[int], permanent: bool) -> None:
        assert self._root is not None
        if self.player.current_track in track_ids:
            self.stop_playback()
        items = [DeleteItem(i, self.model.tracks[i].path) for i in track_ids]
        worker = DeleteWorker(
            items, self.journals, self._root, __version__, permanent, self.trash_function
        )
        verb = "Permanent verwijderen" if permanent else "Naar Prullenbak"
        self._start_batch(worker, f"{verb} ({len(items)})…", len(items))

    # --- bewerken ------------------------------------------------------------------------
    # --- afspelen ------------------------------------------------------------------------
    def _setup_player(self) -> None:
        self.player.trackChanged.connect(
            lambda tid: self.model.set_playing(tid if isinstance(tid, int) else None)
        )
        self.player.finished.connect(self._on_track_finished)
        self.player.error.connect(lambda msg: self._flash(f"Kan niet afspelen: {msg}", 8000))
        self.mini_player.volume_slider.setValue(self._settings.volume)
        self.player.set_volume(self._settings.volume)
        self.mini_player.autoplay.setChecked(self._settings.autoplay_next)

    def selected_ids_in_view_order(self) -> list[int]:
        rows = sorted(i.row() for i in self.table.selectionModel().selectedRows())
        return [
            self.model.track_id(self.proxy.mapToSource(self.proxy.index(r, 0)).row()) for r in rows
        ]

    def play_track(self, track_id: int) -> None:
        track = self.model.tracks[track_id]
        e = self.model.edits
        artist, title = e.artist(track_id), e.title(track_id)
        label = f"{artist} - {title}" if artist else track.filename
        self.player.play(track_id, track.path, label)

    def toggle_play(self, track_id: int | None = None) -> None:
        """Speel de huidige rij af, of stop als die al speelt (spatiebalk)."""
        if track_id is None:
            index = self.table.currentIndex()
            if not index.isValid():
                ids = self.selected_ids_in_view_order()
                if not ids:
                    return
                track_id = ids[0]
            else:
                track_id = self.model.track_id(self.proxy.mapToSource(index).row())
        if self.player.current_track == track_id:
            self.player.stop()
        else:
            self.play_track(track_id)

    def _on_table_clicked(self, index) -> None:
        if index.isValid() and index.column() == Col.PLAY:
            self.toggle_play(self.model.track_id(self.proxy.mapToSource(index).row()))

    @Slot(int)
    def _on_track_finished(self, track_id: int) -> None:
        if not self.mini_player.autoplay.isChecked():
            return
        following = next_in_selection(self.selected_ids_in_view_order(), track_id)
        if following is not None:
            self.play_track(following)
            row = self.proxy.mapFromSource(self.model.index(self.model.row_of(following), 0))
            if row.isValid():
                self.table.scrollTo(row)

    def stop_playback(self) -> None:
        """Vóór bestandsoperaties: Windows kan een geopend bestand niet hernoemen."""
        self.player.stop()

    def _add_row_actions(self, menu: QMenu) -> None:
        menu.addAction(self.act_edit)
        menu.addAction(self.act_bulk)
        menu.addAction(self.act_swap)
        menu.addAction(self.act_revert)
        menu.addSeparator()
        menu.addAction(self.act_play)
        menu.addSeparator()
        menu.addAction(self.act_delete)

    def _show_row_menu(self, pos) -> None:
        if not self.table.indexAt(pos).isValid():
            return
        menu = QMenu(self)
        self._add_row_actions(menu)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def selected_track_ids(self) -> list[int]:
        """Track-ids van de geselecteerde rijen; zonder selectie de huidige rij."""
        indexes = self.table.selectionModel().selectedRows()
        if not indexes and self.table.currentIndex().isValid():
            indexes = [self.table.currentIndex()]
        return [self.model.track_id(self.proxy.mapToSource(i).row()) for i in indexes]

    def edit_current(self) -> None:
        index = self.table.currentIndex()
        if not index.isValid():
            return
        if Col(index.column()).field is None:  # F2 op bijv. Bestandsnaam: bewerk de artiest
            index = index.siblingAtColumn(Col.ARTIST)
            self.table.setCurrentIndex(index)
        self.table.edit(index)

    def bulk_edit(self) -> None:
        ids = self.selected_track_ids()
        if not ids:
            return
        current = self.table.currentIndex()
        field = (Col(current.column()).field if current.isValid() else None) or Field.ARTIST
        initial = current.siblingAtColumn(FIELD_COLUMN[field]).data() if current.isValid() else ""
        dialog = BulkEditDialog(len(ids), self, field=field, initial=initial or "")
        if dialog.exec() and self.model.set_field(ids, dialog.field, dialog.value):
            self._flash(self.undo_stack.undoText())

    def swap_selected(self) -> None:
        if self.model.swap_artist_title(self.selected_track_ids()):
            self._flash(self.undo_stack.undoText())

    def revert_selected(self) -> None:
        if self.model.revert(self.selected_track_ids()):
            self._flash(self.undo_stack.undoText())
        else:
            self._flash("Geen wijzigingen om terug te draaien")

    def revert_all(self) -> None:
        if self.model.revert(sorted(self.model.edits.changed_ids)):
            self._flash(self.undo_stack.undoText() + " — ongedaan maken met Ctrl+Z")

    @Slot()
    def _refilter(self) -> None:
        self.proxy.refresh()
        self._schedule_stats()

    def confirm_discard(self, action: str) -> bool:
        """Vraag bevestiging als er niet-opgeslagen wijzigingen zijn. ``True`` = doorgaan."""
        n = self.model.changed_count()
        if n == 0:
            return True
        answer = QMessageBox.warning(
            self,
            APP_TITLE,
            f"Er zijn {n} tracks met niet-opgeslagen wijzigingen.\n\n"
            f"{action} en deze wijzigingen verwerpen?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    # --- scannen -------------------------------------------------------------------------
    def _batch_running(self) -> bool:
        if self._batch_worker is not None:
            self._flash("Er wordt nog opgeslagen of teruggedraaid; even geduld", 6000)
            return True
        return False

    def choose_folder(self) -> None:
        if self._batch_running():
            return
        if not self.confirm_discard("Een andere map openen"):
            return
        start = str(self._root) if self._root else (self._settings.last_root or "")
        folder = QFileDialog.getExistingDirectory(self, "Kies de hoofdmap", start)
        if folder:
            self.start_scan(Path(folder))

    def reload(self) -> None:
        if self._batch_running():
            return
        if self._root is not None and self.confirm_discard("Herladen"):
            self.start_scan(self._root)

    def start_scan(self, root: Path) -> None:
        self.cancel_tasks()
        self.stop_playback()
        self._root = root
        self._settings.last_root = str(root)
        self._update_title()
        self.undo_stack.clear()  # de commando's verwijzen naar track-ids van de oude scan
        self.model.clear()
        worker = ScanWorker(root, self._settings.extensions)
        worker.signals.batch.connect(self._on_scan_batch)
        worker.signals.progress.connect(self._on_scan_progress)
        worker.signals.finished.connect(self._on_scan_finished)
        self._scan_worker = worker
        self.progress.setRange(0, 0)  # onbepaald
        self._set_busy(True, "Scannen…")
        self._start(worker)

    def _start(self, worker: Worker) -> None:
        self._workers[worker.signals] = worker
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(self._forget_worker)
        self._pool.start(worker)

    def _is_current(self, worker: Worker | None) -> bool:
        return worker is not None and self.sender() is worker.signals

    @Slot(object)
    def _on_scan_batch(self, tracks: object) -> None:
        if self._is_current(self._scan_worker):
            # Tijdens het scannen niet steeds hersorteren; dat gebeurt eenmalig aan het eind.
            self.model.append_tracks(tracks, resort=False)  # type: ignore[arg-type]

    @Slot(int, int)
    def _on_scan_progress(self, done: int, _total: int) -> None:
        if self._is_current(self._scan_worker):
            self.task_label.setText(f"Scannen… {done} bestanden")

    @Slot(bool)
    def _on_scan_finished(self, cancelled: bool) -> None:
        if not self._is_current(self._scan_worker):
            return
        self._scan_worker = None
        self.model.resort()
        count = self.model.rowCount()
        if cancelled:
            self._set_busy(False)
            self._flash(f"Scan geannuleerd na {count} bestanden", 5000)
            return
        self._flash(f"{count} bestanden gevonden", 5000)
        if count == 0:
            self._set_busy(False)
            return
        worker = TagWorker([(t.id, t.path) for t in self.model.tracks])
        worker.signals.batch.connect(self._on_tag_batch)
        worker.signals.progress.connect(self._on_tag_progress)
        worker.signals.finished.connect(self._on_tag_finished)
        self._tag_worker = worker
        self.progress.setRange(0, count)
        self.progress.setValue(0)
        self._set_busy(True, "Tags inlezen…")
        self._start(worker)

    @Slot(object)
    def _on_tag_batch(self, infos: object) -> None:
        if self._is_current(self._tag_worker):
            self.model.set_infos(infos)  # type: ignore[arg-type]
            if self.proxy.quick_filter.depends_on_info:
                self.proxy.refresh()
                self._schedule_stats()

    @Slot(int, int)
    def _on_tag_progress(self, done: int, total: int) -> None:
        if self._is_current(self._tag_worker):
            self.progress.setRange(0, total)
            self.progress.setValue(done)

    @Slot(bool)
    def _on_tag_finished(self, cancelled: bool) -> None:
        if not self._is_current(self._tag_worker):
            return
        self._tag_worker = None
        self._set_busy(False)
        sort_col = self.model.sort_column
        if sort_col is not None and sort_col.optional:  # duur/bitrate/tags zijn nu bekend
            self.model.resort()
        if cancelled:
            self._flash("Inlezen van tags geannuleerd", 5000)
        self._schedule_stats()

    # --- opslaan ------------------------------------------------------------------------
    def _apply_folder_rule(self) -> None:
        s = self._settings
        template = FolderTemplate(s.folder_template)
        if template is FolderTemplate.NONE:
            self.model.set_folder_rule(None)
            return
        style, unknown = DecadeStyle(s.decade_style), s.unknown_year_folder
        self.model.set_folder_rule(lambda year: folder_for_year(year, template, style, unknown))

    def plan_inputs(self) -> list[PlanInput]:
        """Invoer voor de planner: alle tracks met een bruikbare naam of een wijziging."""
        m, e = self.model, self.model.edits
        inputs = []
        for t in m.tracks:
            changed = e.is_changed(t.id)
            if m.is_deleted_id(t.id) or (t.parse_status is ParseStatus.ERROR and not changed):
                continue
            inputs.append(
                PlanInput(
                    t.id,
                    t.path,
                    e.artist(t.id),
                    e.title(t.id),
                    e.year(t.id),
                    changed,
                    bool(m.mismatches(m.row_of(t.id))),
                )
            )
        return inputs

    def _ensure_idle(self) -> bool:
        if self.busy:
            self._flash("Wacht tot de lopende taak klaar is, of annuleer die (Esc)", 6000)
            return False
        return True

    def save_changes(self) -> None:
        if self._root is None or not self._ensure_idle():
            return
        dialog = SavePreviewDialog(self.plan_inputs(), self._root, self._settings, self)
        if not dialog.exec():
            return
        dialog.store_settings(self._settings)
        self._apply_folder_rule()
        self.model.flag_duplicates(dialog.duplicate_ids())
        self.start_save(dialog.selected_plans(), dialog.cleanup.isChecked())

    def start_save(self, plans: list[RenamePlan], cleanup_empty_dirs: bool) -> None:
        assert self._root is not None
        if not plans:
            return
        self.stop_playback()
        worker = SaveWorker(plans, self.journals, self._root, __version__, cleanup_empty_dirs)
        self._start_batch(worker, f"Opslaan ({len(plans)})…", len(plans))

    def undo_last_batch(self) -> None:
        if not self._ensure_idle():
            return
        target = self.journals.latest_undoable()
        if target is None:
            QMessageBox.information(self, APP_TITLE, "Er is geen batch om terug te draaien.")
            return
        answer = QMessageBox.question(
            self,
            APP_TITLE,
            f"Batch van {target.created.replace('T', ' ')} terugdraaien?\n\n"
            f"{target.ok_count} bewerkingen, uitgevoerd met Mp3Sanitizer {target.app_version}.\n"
            "De bestanden krijgen hun oude naam en map terug; bijgewerkte tags worden hersteld.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.confirm_discard("Na het terugdraaien wordt de map opnieuw ingelezen. Doorgaan"):
            return
        self.start_undo(target)

    def start_undo(self, target: Journal) -> None:
        self.stop_playback()
        worker = UndoWorker(target, self.journals, __version__)
        self._start_batch(worker, "Terugdraaien…", target.ok_count)

    def _start_batch(
        self, worker: SaveWorker | UndoWorker | DeleteWorker, text: str, total: int
    ) -> None:
        worker.signals.progress.connect(self._on_batch_progress)
        worker.signals.batch.connect(self._on_batch_result)
        worker.signals.finished.connect(self._on_batch_finished)
        self._batch_worker = worker
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(0)
        self._set_busy(True, text)
        self._start(worker)

    @Slot(int, int)
    def _on_batch_progress(self, done: int, total: int) -> None:
        if self._is_current(self._batch_worker):
            self.progress.setRange(0, max(total, 1))
            self.progress.setValue(done)

    @Slot(object)
    def _on_batch_result(self, payload: object) -> None:
        worker = self._batch_worker
        if not self._is_current(worker):
            return
        result, journal = payload  # type: ignore[misc]
        if isinstance(worker, DeleteWorker):
            self.model.mark_deleted(result.deleted)
            self.report_delete(result, worker.permanent)
        elif isinstance(worker, SaveWorker):
            self.model.apply_saved([(m.track_id, m.dst) for m in result.moved], result.tagged)
            self.undo_stack.clear()  # de commando's verwijzen naar de oude originele waarden
            self.report_batch(result, journal, "Opgeslagen")
        else:
            self.report_batch(result, journal, "Teruggedraaid")
            self._reload_after_batch = True  # pas herladen als de worker helemaal klaar is

    @Slot(bool)
    def _on_batch_finished(self, _cancelled: bool) -> None:
        if self._is_current(self._batch_worker):
            self._batch_worker = None
            self._set_busy(False)
            if self._reload_after_batch and self._root is not None:
                self._reload_after_batch = False
                self.start_scan(self._root)

    def report_delete(self, result: DeleteResult, permanent: bool) -> None:
        where = "permanent verwijderd" if permanent else "naar de Prullenbak verplaatst"
        summary = f"{len(result.deleted)} bestanden {where}"
        if result.cancelled:
            summary += " (geannuleerd)"
        self.last_report = summary
        log.info(summary)
        if not result.failures:
            self._flash(summary, 8000)
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(APP_TITLE)
        box.setText(
            f"{summary}.\n\n{len(result.failures)} bestanden konden niet worden verwijderd."
        )
        box.setDetailedText("\n".join(f"{p}: {m}" for _, p, m in result.failures))
        box.exec()

    def report_batch(self, result: ExecResult, journal: Journal, verb: str) -> None:
        moved, tagged, failed = len(result.moved), len(result.tagged), len(result.failures)
        parts = [f"{verb}: {moved} bestanden hernoemd/verplaatst"]
        if tagged:
            parts.append(f"{tagged} getagd")
        if result.removed_dirs:
            parts.append(f"{len(result.removed_dirs)} lege mappen opgeruimd")
        if result.cancelled:
            parts.append("geannuleerd")
        summary = ", ".join(parts)
        self.last_report = summary
        log.info("%s (batch %s, %d fouten)", summary, journal.batch_id, failed)
        if not failed:
            self._flash(summary, 8000)
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(APP_TITLE)
        box.setText(f"{summary}.\n\n{failed} bestanden konden niet worden verwerkt.")
        box.setInformativeText(f"Journaal: {self.journals.log_path(journal.batch_id)}")
        box.setDetailedText("\n".join(f"{f.path}: {f.message}" for f in result.failures))
        box.exec()

    @Slot(str)
    def _on_worker_error(self, message: str) -> None:
        self._flash(f"Fout: {message}", 10000)

    @Slot(bool)
    def _forget_worker(self, _cancelled: bool) -> None:
        signals = self.sender()
        if isinstance(signals, WorkerSignals):
            self._workers.pop(signals, None)

    def cancel_tasks(self) -> None:
        for worker in list(self._workers.values()):
            worker.cancel()
        if self._scan_worker or self._tag_worker:
            self._flash("Annuleren…", 2000)
        self._scan_worker = None
        self._tag_worker = None
        self._set_busy(False)

    @property
    def busy(self) -> bool:
        return bool(self._workers)

    # --- afsluiten -----------------------------------------------------------------------
    def show_load_messages(self, parent: QWidget | None = None) -> None:
        msg = self._store.load_result.message
        if msg:
            QMessageBox.warning(parent or self, "Instellingen", msg)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._batch_worker is not None:
            QMessageBox.information(
                self, APP_TITLE, "Er loopt nog een batch. Wacht tot die klaar is of annuleer (Esc)."
            )
            event.ignore()
            return
        if not self.confirm_discard("Afsluiten"):
            event.ignore()
            return
        self.cancel_tasks()
        self._pool.waitForDone(3000)
        self._save_view_state()
        try:
            self._store.save()
        except OSError:
            log.exception("Instellingen opslaan mislukt")
        super().closeEvent(event)
