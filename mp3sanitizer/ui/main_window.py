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
    QWidget,
)

from mp3sanitizer import __version__
from mp3sanitizer.core.models import Field
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.ui.bulk_edit_dialog import BulkEditDialog
from mp3sanitizer.ui.delegates import TrackEditDelegate
from mp3sanitizer.ui.proxy_model import QuickFilter, TrackFilterProxy
from mp3sanitizer.ui.track_model import FIELD_COLUMN, Col, TrackTableModel
from mp3sanitizer.ui.workers import ScanWorker, TagWorker, Worker, WorkerSignals

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
}


class MainWindow(QMainWindow):
    def __init__(self, store: SettingsStore, pool: QThreadPool | None = None) -> None:
        super().__init__()
        self._store = store
        self._settings = store.settings
        self._pool = pool or QThreadPool.globalInstance()
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
        self.setCentralWidget(self.table)

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

    def _save_view_state(self) -> None:
        s = self._settings
        s.window_geometry = bytes(self.saveGeometry().toBase64().data()).decode("ascii")
        s.header_state = bytes(self.table.horizontalHeader().saveState().toBase64().data()).decode(
            "ascii"
        )
        s.visible_columns = [c.key for c in Col if not self.table.isColumnHidden(c)]

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
        return super().eventFilter(watched, event)

    # --- statusbalk ----------------------------------------------------------------------
    @Slot()
    def _schedule_stats(self) -> None:
        self._stats_timer.start()

    def _update_stats(self) -> None:
        total = self.model.rowCount()
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

    # --- bewerken ------------------------------------------------------------------------
    def _add_row_actions(self, menu: QMenu) -> None:
        menu.addAction(self.act_edit)
        menu.addAction(self.act_bulk)
        menu.addAction(self.act_swap)
        menu.addAction(self.act_revert)

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
    def choose_folder(self) -> None:
        if not self.confirm_discard("Een andere map openen"):
            return
        start = str(self._root) if self._root else (self._settings.last_root or "")
        folder = QFileDialog.getExistingDirectory(self, "Kies de hoofdmap", start)
        if folder:
            self.start_scan(Path(folder))

    def reload(self) -> None:
        if self._root is not None and self.confirm_discard("Herladen"):
            self.start_scan(self._root)

    def start_scan(self, root: Path) -> None:
        self.cancel_tasks()
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
