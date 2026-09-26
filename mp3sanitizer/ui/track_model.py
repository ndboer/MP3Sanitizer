"""Tabelmodel voor de tracks (``QAbstractTableModel``).

Alle weergave, sortering en filtering gebruikt de *effectieve* waarden: de geparste waarde uit
de bestandsnaam, tenzij er een niet-opgeslagen wijziging is (``EditState``). Wijzigingen lopen
via ``push_changes`` en daarmee via de ``QUndoStack``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from enum import IntEnum
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QUndoStack
from PySide6.QtWidgets import QApplication, QStyle

from mp3sanitizer.core.duplicates import DupItem
from mp3sanitizer.core.edits import EditState
from mp3sanitizer.core.models import (
    AudioInfo,
    Field,
    FieldValue,
    ParseStatus,
    PendingChange,
    TagValues,
    Track,
)
from mp3sanitizer.core.normalize import DEFAULT_ARTICLES, fold, natural_key, sort_key
from mp3sanitizer.core.parser import format_stem, parse_filename
from mp3sanitizer.core.rules.base import Context, CorrectionInput, Values
from mp3sanitizer.core.tags import tag_mismatches
from mp3sanitizer.core.validate import Issue, YearError, parse_year_input, text_issues
from mp3sanitizer.ui.undo_commands import EditCommand

TRACK_ROLE = Qt.ItemDataRole.UserRole + 1

ERROR_COLOR = QColor("#d9534f")
WARNING_COLOR = QColor("#e08a00")
# Halfdoorzichtig, zodat het in zowel het lichte als het donkere thema leesbaar blijft.
CHANGED_BACKGROUND = QColor(255, 190, 0, 70)
INVALID_BACKGROUND = QColor(220, 40, 40, 90)
_BOLD = QFont()
_BOLD.setBold(True)
_ICONS: dict[bool, QIcon] = {}


def _media_icon(playing: bool) -> QIcon:
    """Stop-pictogram voor de track die speelt, anders Play (lazy: vereist een QApplication)."""
    if playing not in _ICONS:
        pixmap = (
            QStyle.StandardPixmap.SP_MediaStop if playing else QStyle.StandardPixmap.SP_MediaPlay
        )
        _ICONS[playing] = QApplication.style().standardIcon(pixmap)
    return _ICONS[playing]


type AnyIndex = QModelIndex | QPersistentModelIndex
type Issues = dict[Field, tuple[Issue, ...]]


class Col(IntEnum):
    STATUS = 0
    ARTIST = 1
    TITLE = 2
    YEAR = 3
    FOLDER = 4
    FILENAME = 5
    DURATION = 6
    BITRATE = 7
    SIZE = 8
    TAG_ARTIST = 9
    TAG_TITLE = 10
    TAG_YEAR = 11
    PLAY = 12  # actiekolom; wordt visueel vooraan gezet

    @property
    def key(self) -> str:
        return self.name.lower()

    @property
    def header(self) -> str:
        return _HEADERS[self]

    @property
    def optional(self) -> bool:
        return self in _OPTIONAL

    @property
    def field(self) -> Field | None:
        """Het bewerkbare veld van deze kolom."""
        return _EDITABLE.get(self)

    @classmethod
    def from_key(cls, key: str) -> Col | None:
        try:
            return cls[key.upper()]
        except KeyError:
            return None


_HEADERS = {
    Col.STATUS: "Status",
    Col.ARTIST: "Artiest",
    Col.TITLE: "Titel",
    Col.YEAR: "Jaar",
    Col.FOLDER: "Folder",
    Col.FILENAME: "Bestandsnaam",
    Col.DURATION: "Duur",
    Col.BITRATE: "Bitrate",
    Col.SIZE: "Grootte",
    Col.TAG_ARTIST: "Tag-artiest",
    Col.TAG_TITLE: "Tag-titel",
    Col.TAG_YEAR: "Tag-jaar",
    Col.PLAY: "",
}
_OPTIONAL = {Col.DURATION, Col.BITRATE, Col.SIZE, Col.TAG_ARTIST, Col.TAG_TITLE, Col.TAG_YEAR}

_EDITABLE = {Col.ARTIST: Field.ARTIST, Col.TITLE: Field.TITLE, Col.YEAR: Field.YEAR}
FIELD_COLUMN = {field: col for col, field in _EDITABLE.items()}
FIELD_LABEL = {Field.ARTIST: "Artiest", Field.TITLE: "Titel", Field.YEAR: "Jaar"}
_RIGHT_ALIGNED = {Col.YEAR, Col.DURATION, Col.BITRATE, Col.SIZE, Col.TAG_YEAR}
_INFO_COLUMNS = {Col.DURATION, Col.BITRATE, Col.SIZE, Col.TAG_ARTIST, Col.TAG_TITLE, Col.TAG_YEAR}
_TAG_FIELD = {Col.TAG_ARTIST: Field.ARTIST, Col.TAG_TITLE: Field.TITLE, Col.TAG_YEAR: Field.YEAR}
_EMPTY_KEY = natural_key("")
_NO_ISSUES: Issues = {}


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def format_size(size: int | None) -> str:
    if size is None:
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def format_value(value: FieldValue) -> str:
    return "" if value is None else str(value)


def status_text(
    parse_status: ParseStatus,
    *,
    changed: bool,
    invalid: bool,
    has_year: bool,
    mismatches: Sequence[Field] = (),
    duplicate: bool = False,
) -> str:
    if changed:
        text = "Gewijzigd · ongeldig" if invalid else "Gewijzigd"
    elif parse_status is ParseStatus.ERROR:
        text = "Parse-fout"
    elif invalid:
        text = "Ongeldig"
    elif not has_year:
        text = "Geen jaar"
    else:
        text = "OK"
    if duplicate:
        text += " · duplicaat"
    return text + " · tags ≠" if mismatches else text


class TrackTableModel(QAbstractTableModel):
    editsApplied = Signal()  # na elke toegepaste (of teruggedraaide) wijziging
    editRejected = Signal(str)  # ongeldige invoer, met uitleg

    def __init__(self, articles: Iterable[str] = DEFAULT_ARTICLES, parent=None) -> None:
        super().__init__(parent)
        self._articles = tuple(articles)
        self._tracks: list[Track] = []
        self.edits = EditState(self._tracks)
        self.undo_stack: QUndoStack | None = None
        # Gecachete afgeleide gegevens per track-id, zodat sorteren en filteren snel blijven.
        self._artist_keys: list[tuple[str | int, ...]] = []
        self._title_keys: list[tuple[str | int, ...]] = []
        self._folder_keys: list[str] = []
        self._search_keys: list[str] = []
        self._mismatches: list[tuple[Field, ...]] = []
        self._issues: list[Issues] = []
        self._misplaced: list[bool] = []
        # Verwachte relatieve map voor een jaar (None = niet verplaatsen); zie set_folder_rule.
        self._folder_rule: Callable[[int | None], str | None] | None = None
        self.duplicate_flags: set[int] = set()  # track-ids, gemarkeerd bij een botsing
        self._playing: int | None = None  # track-id die nu speelt
        # Verwijderde tracks blijven in de lijst (ids blijven geldig) maar zijn verborgen.
        self._deleted: set[int] = set()
        # Resultaat van de laatste duplicaatdetectie (voor het snelfilter 'Duplicaten').
        self._duplicates: set[int] = set()
        # _order[rij] = track-id; _rows[track-id] = rij
        self._order: list[int] = []
        self._rows: list[int] = []
        self._sort_col: Col | None = None
        self._sort_order = Qt.SortOrder.AscendingOrder

    # --- toegang (op rij) ----------------------------------------------------------------
    @property
    def tracks(self) -> Sequence[Track]:
        """Alle tracks in id-volgorde (onafhankelijk van de sortering)."""
        return self._tracks

    def track(self, row: int) -> Track:
        return self._tracks[self._order[row]]

    def track_id(self, row: int) -> int:
        return self._order[row]

    def row_of(self, track_id: int) -> int:
        return self._rows[track_id]

    def year(self, row: int) -> int | None:
        return self.edits.year(self._order[row])

    def is_changed(self, row: int) -> bool:
        return self.edits.is_changed(self._order[row])

    def has_issues(self, row: int) -> bool:
        return bool(self._issues[self._order[row]])

    def mismatches(self, row: int) -> tuple[Field, ...]:
        return self._mismatches[self._order[row]]

    def is_misplaced(self, row: int) -> bool:
        return self._misplaced[self._order[row]]

    def search_key(self, row: int) -> str:
        """Gevouwen 'artiest\\0titel\\0bestandsnaam' voor het zoekfilter."""
        return self._search_keys[self._order[row]]

    def is_duplicate(self, row: int) -> bool:
        tid = self._order[row]
        return tid in self._duplicates or tid in self.duplicate_flags

    def set_duplicates(self, track_ids: Iterable[int]) -> None:
        """Zet het detectieresultaat; de aanroeper ververst zelf het filter."""
        self._duplicates = set(track_ids)

    def dup_items(self) -> list[DupItem]:
        """Invoer voor de duplicaatdetectie: effectieve waarden van alle tracks."""
        e = self.edits
        items = []
        for t in self._tracks:
            if t.id in self._deleted:
                continue
            info = t.info
            items.append(
                DupItem(
                    t.id,
                    e.artist(t.id),
                    e.title(t.id),
                    e.year(t.id),
                    t.path,
                    info.duration_s if info else None,
                    info.bitrate_kbps if info else None,
                    info.size_bytes if info else None,
                )
            )
        return items

    def is_deleted(self, row: int) -> bool:
        return self._order[row] in self._deleted

    def is_deleted_id(self, track_id: int) -> bool:
        return track_id in self._deleted

    def live_count(self) -> int:
        """Aantal tracks zonder de verwijderde."""
        return len(self._tracks) - len(self._deleted)

    def parse_error_count(self) -> int:
        return sum(
            1
            for t in self._tracks
            if t.parse_status is ParseStatus.ERROR and t.id not in self._deleted
        )

    def changed_count(self) -> int:
        return len(self.edits)

    def artist_index(self) -> dict[str, list[int]]:
        """Per (effectieve) schrijfwijze de track-ids; zonder verwijderde en lege artiesten."""
        index: dict[str, list[int]] = {}
        for t in self._tracks:
            if t.id in self._deleted:
                continue
            artist = self.edits.artist(t.id)
            if artist.strip():
                index.setdefault(artist, []).append(t.id)
        return index

    def correction_inputs(self, track_ids: Iterable[int]) -> list[CorrectionInput]:
        """Invoer voor de batch-correcties: effectieve waarden + tag-jaar."""
        e = self.edits
        result = []
        for tid in track_ids:
            if tid in self._deleted:
                continue
            info = self._tracks[tid].info
            result.append(
                CorrectionInput(
                    tid,
                    Values(e.artist(tid), e.title(tid), e.year(tid)),
                    Context(tag_year=info.tag_year if info else None),
                )
            )
        return result

    def track_label(self, track_id: int) -> str:
        e = self.edits
        year = e.year(track_id)
        text = f"{e.artist(track_id)} - {e.title(track_id)}"
        return f"{text} ({year})" if year else text

    def target_filename(self, track_id: int) -> str:
        e = self.edits
        track = self._tracks[track_id]
        return format_stem(e.artist(track_id), e.title(track_id), e.year(track_id)) + track.ext

    # --- scannen / inlezen ---------------------------------------------------------------
    def clear(self) -> None:
        self.beginResetModel()
        for cache in (
            self._tracks,
            self._order,
            self._rows,
            self._artist_keys,
            self._title_keys,
            self._folder_keys,
            self._search_keys,
            self._mismatches,
            self._issues,
            self._misplaced,
        ):
            cache.clear()
        self.edits.clear()
        self.duplicate_flags.clear()
        self._deleted.clear()
        self._duplicates.clear()
        self._playing = None
        self.endResetModel()

    def append_tracks(self, tracks: Sequence[Track], *, resort: bool = True) -> None:
        """Voeg tracks toe; de ids moeten aansluiten op het aantal tracks tot dan toe.

        Met ``resort=False`` komen de rijen onderaan; roep daarna zelf ``resort()`` aan.
        """
        if not tracks:
            return
        first = len(self._tracks)
        if [t.id for t in tracks] != list(range(first, first + len(tracks))):
            raise ValueError("track-ids moeten aaneengesloten zijn")
        self.beginInsertRows(QModelIndex(), first, first + len(tracks) - 1)
        for track in tracks:
            self._order.append(track.id)
            self._rows.append(len(self._rows))
            self._tracks.append(track)
            self._artist_keys.append(_EMPTY_KEY)
            self._title_keys.append(_EMPTY_KEY)
            self._folder_keys.append(fold(track.folder))
            self._search_keys.append("")
            self._mismatches.append(())
            self._issues.append(_NO_ISSUES)
            self._misplaced.append(False)
            self._recompute(track.id)
        self.endInsertRows()
        if resort:
            self.resort()

    def set_infos(self, infos: Iterable[tuple[int, AudioInfo]]) -> None:
        """Werk de lazy ingelezen gegevens bij (op track-id)."""
        rows = []
        for track_id, info in infos:
            if 0 <= track_id < len(self._tracks):
                self._tracks[track_id].info = info
                self._recompute_mismatches(track_id)
                rows.append(self._rows[track_id])
        if rows:
            self.dataChanged.emit(self.index(min(rows), 0), self.index(max(rows), len(Col) - 1))

    def _recompute(self, tid: int) -> None:
        e = self.edits
        artist, title = e.artist(tid), e.title(tid)
        self._artist_keys[tid] = natural_key(sort_key(artist, self._articles))
        self._title_keys[tid] = natural_key(fold(title))
        self._search_keys[tid] = fold(f"{artist}\x00{title}\x00{self._tracks[tid].filename}")
        issues = {}
        for field, text in ((Field.ARTIST, artist), (Field.TITLE, title)):
            found = text_issues(text)
            if found:
                issues[field] = found
        self._issues[tid] = issues or _NO_ISSUES
        self._misplaced[tid] = self._is_misplaced(tid)
        self._recompute_mismatches(tid)

    def _is_misplaced(self, tid: int) -> bool:
        if self._folder_rule is None:
            return False
        expected = self._folder_rule(self.edits.year(tid))
        return expected is not None and fold(self._tracks[tid].folder) != fold(expected)

    def set_folder_rule(self, rule: Callable[[int | None], str | None] | None) -> None:
        """Stel in welke jaarmap bij een jaar hoort (voor het filter 'Verkeerde jaarmap')."""
        self._folder_rule = rule
        for tid in range(len(self._tracks)):
            self._misplaced[tid] = self._is_misplaced(tid)
        self.editsApplied.emit()

    # --- na opslaan ----------------------------------------------------------------------
    def apply_saved(self, moved: Iterable[tuple[int, Path]], tagged: dict[int, TagValues]) -> None:
        """Verwerk een uitgevoerde batch: nieuwe paden, en de opgeslagen waarden worden de
        nieuwe originelen (opnieuw geparsed uit de nieuwe bestandsnaam)."""
        touched: set[int] = set()
        for tid, new_path in moved:
            track = self._tracks[tid]
            track.path = new_path
            parsed = parse_filename(new_path.stem)
            track.artist, track.title, track.year = parsed.artist, parsed.title, parsed.year
            track.parse_status = parsed.status
            track.copy_number = parsed.copy_number
            self._folder_keys[tid] = fold(track.folder)
            touched.add(tid)
        for tid, tags in tagged.items():
            info = self._tracks[tid].info
            if info is not None:
                info.tag_artist, info.tag_title = tags.artist, tags.title
                info.tag_year = int(tags.date) if tags.date and tags.date.isdigit() else None
            touched.add(tid)
        for tid in touched:
            self.edits.discard(tid)
            self.duplicate_flags.discard(tid)
            self._recompute(tid)
        self._emit_rows_changed(touched)
        self.editsApplied.emit()

    @property
    def playing_track(self) -> int | None:
        return self._playing

    def set_playing(self, track_id: int | None) -> None:
        """Markeer de track die speelt (Play-kolom en vetgedrukt)."""
        if track_id == self._playing:
            return
        changed = {t for t in (self._playing, track_id) if t is not None}
        self._playing = track_id
        self._emit_rows_changed(t for t in changed if t < len(self._tracks))

    def mark_deleted(self, track_ids: Iterable[int]) -> None:
        """Verberg verwijderde tracks; hun niet-opgeslagen wijzigingen vervallen."""
        ids = set(track_ids) - self._deleted
        if not ids:
            return
        self._deleted |= ids
        for tid in ids:
            self.edits.discard(tid)
            self.duplicate_flags.discard(tid)
        self._emit_rows_changed(ids)
        self.editsApplied.emit()

    def flag_duplicates(self, track_ids: Iterable[int]) -> None:
        ids = set(track_ids) - self.duplicate_flags
        if ids:
            self.duplicate_flags |= ids
            self._emit_rows_changed(ids)
            self.editsApplied.emit()

    def _recompute_mismatches(self, tid: int) -> None:
        e = self.edits
        self._mismatches[tid] = tuple(
            tag_mismatches(e.artist(tid), e.title(tid), e.year(tid), self._tracks[tid].info)
        )

    # --- wijzigingen ---------------------------------------------------------------------
    def push_changes(self, changes: Sequence[PendingChange], text: str) -> bool:
        """Voer wijzigingen uit als één undo-stap. ``False`` als er niets te doen was."""
        changes = [c for c in changes if c.old != c.new]
        if not changes:
            return False
        if self.undo_stack is not None:
            self.undo_stack.push(EditCommand(self, changes, text))
        else:
            self.apply_changes(changes)
        return True

    def apply_changes(self, changes: Sequence[PendingChange], *, forward: bool = True) -> None:
        """Pas wijzigingen direct toe. Normaal alleen aangeroepen door ``EditCommand``."""
        touched = self.edits.apply(changes, forward=forward)
        for tid in touched:
            self._recompute(tid)
        self._emit_rows_changed(touched)
        self.editsApplied.emit()

    def set_field(self, track_ids: Iterable[int], field: Field, value: FieldValue) -> bool:
        """Bulk: zet één veld voor meerdere tracks (één undo-stap)."""
        ids = list(track_ids)
        changes = [c for tid in ids if (c := self.edits.change(tid, field, value, "bulk"))]
        n = len({c.track_id for c in changes})
        return self.push_changes(changes, f"{FIELD_LABEL[field]} invullen ({n} tracks)")

    def swap_artist_title(self, track_ids: Iterable[int]) -> bool:
        changes = self.edits.swap_changes(track_ids)
        n = len(changes) // 2
        return self.push_changes(changes, f"Wissel artiest ⇄ titel ({n} tracks)")

    # Niet "revert" noemen: dat is een virtuele Qt-methode (QAbstractItemModel.revert) die Qt
    # zonder argumenten aanroept als een editor met Esc wordt geannuleerd.
    def revert_tracks(self, track_ids: Iterable[int]) -> bool:
        changes = self.edits.revert_changes(track_ids)
        n = len({c.track_id for c in changes})
        return self.push_changes(changes, f"Terugdraaien ({n} tracks)")

    def _emit_rows_changed(self, track_ids: Iterable[int]) -> None:
        rows = sorted(self._rows[tid] for tid in track_ids)
        if not rows:
            return
        last_col = len(Col) - 1
        if len(rows) > 50:  # veel rijen: één bereik is goedkoper dan veel losse signalen
            self.dataChanged.emit(self.index(rows[0], 0), self.index(rows[-1], last_col))
            return
        for row in rows:
            self.dataChanged.emit(self.index(row, 0), self.index(row, last_col))

    # --- sorteren ------------------------------------------------------------------------
    # Het model sorteert zelf (één ``sorted`` op gecachete sleutels). Sorteren in de proxy zou
    # per vergelijking Python-``data()`` aanroepen en is bij 10.000 rijen seconden trager.
    # Na een bewerking wordt niet automatisch hersorteerd: de rij blijft staan waar hij staat.
    @property
    def sort_column(self) -> Col | None:
        return self._sort_col

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        self._sort_col = Col(column) if 0 <= column < len(Col) else None
        self._sort_order = order
        self.resort()

    def resort(self) -> None:
        if self._sort_col is None:
            return
        new_order = sorted(
            range(len(self._tracks)),
            key=self._sort_key_func(self._sort_col),
            reverse=self._sort_order == Qt.SortOrder.DescendingOrder,
        )
        if new_order == self._order:
            return
        self.layoutAboutToBeChanged.emit()
        old_persistent = self.persistentIndexList()
        ids = [(self._order[i.row()], i.column()) for i in old_persistent]
        self._order = new_order
        for row, tid in enumerate(new_order):
            self._rows[tid] = row
        self.changePersistentIndexList(
            old_persistent, [self.index(self._rows[tid], col) for tid, col in ids]
        )
        self.layoutChanged.emit()

    def _sort_key_func(self, col: Col) -> Callable[[int], Any]:
        t = self._tracks
        artist, title, folder = self._artist_keys, self._title_keys, self._folder_keys
        mism, e = self._mismatches, self.edits

        def info_value(attr: str) -> Callable[[int], tuple[Any, ...]]:
            def key(i: int) -> tuple[Any, ...]:
                info = t[i].info
                value = -1.0 if info is None else float(getattr(info, attr) or 0)
                return (value, artist[i], title[i])

            return key

        def tag_text(i: int, attr: str) -> str:
            info = t[i].info
            return (getattr(info, attr) or "") if info else ""

        match col:
            case Col.STATUS:
                return lambda i: (
                    not e.is_changed(i),
                    t[i].parse_status,
                    len(mism[i]),
                    artist[i],
                    title[i],
                )
            case Col.ARTIST:
                # Lege artiest (parse-fout) onderaan in plaats van bovenaan.
                return lambda i: (artist[i] == _EMPTY_KEY, artist[i], title[i])
            case Col.TITLE:
                return lambda i: (title[i], artist[i])
            case Col.YEAR:
                return lambda i: (e.year(i) or 0, artist[i], title[i])
            case Col.FOLDER:
                return lambda i: (folder[i], artist[i], title[i])
            case Col.FILENAME:
                return lambda i: natural_key(fold(t[i].filename))
            case Col.DURATION:
                return info_value("duration_s")
            case Col.BITRATE:
                return info_value("bitrate_kbps")
            case Col.SIZE:
                return info_value("size_bytes")
            case Col.TAG_YEAR:
                return info_value("tag_year")
            case Col.TAG_ARTIST:
                return lambda i: natural_key(sort_key(tag_text(i, "tag_artist"), self._articles))
            case Col.TAG_TITLE:
                return lambda i: natural_key(fold(tag_text(i, "tag_title")))
            case Col.PLAY:
                return lambda i: (i != self._playing, artist[i], title[i])

    # --- QAbstractTableModel -------------------------------------------------------------
    def rowCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._tracks)

    def columnCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(Col)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(Col):
            if role == Qt.ItemDataRole.DisplayRole:
                return Col(section).header
            if role == Qt.ItemDataRole.TextAlignmentRole and Col(section) in _RIGHT_ALIGNED:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def flags(self, index: AnyIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if Col(index.column()) in _EDITABLE:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def data(self, index: AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        tid = self._order[index.row()]
        col = Col(index.column())
        track = self._tracks[tid]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(track, tid, col)
        if role == Qt.ItemDataRole.EditRole:
            field = col.field
            return format_value(self.edits.value(tid, field)) if field else None
        if role == TRACK_ROLE:
            return track
        if role == Qt.ItemDataRole.TextAlignmentRole and col in _RIGHT_ALIGNED:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.TextAlignmentRole and col == Col.PLAY:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.DecorationRole and col == Col.PLAY:
            return _media_icon(tid == self._playing)
        if role == Qt.ItemDataRole.FontRole and tid == self._playing:
            return _BOLD
        if role == Qt.ItemDataRole.BackgroundRole:
            return self._background(tid, col)
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(track, tid, col)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(track, tid, col)
        return None

    def setData(self, index: AnyIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        field = Col(index.column()).field
        if field is None:
            return False
        tid = self._order[index.row()]
        text = "" if value is None else str(value)
        new: FieldValue
        if field is Field.YEAR:
            try:
                new = parse_year_input(text)
            except YearError as exc:
                self.editRejected.emit(str(exc))
                return False
        else:
            new = " ".join(text.split())  # spaties aan de randen en dubbele spaties weg
            if not new:
                self.editRejected.emit(f"{FIELD_LABEL[field]} mag niet leeg zijn")
                return False
        change = self.edits.change(tid, field, new)
        if change is None:
            return True
        return self.push_changes([change], f"{FIELD_LABEL[field]} wijzigen")

    # --- rollen --------------------------------------------------------------------------
    def _display(self, track: Track, tid: int, col: Col) -> str:
        if col in _INFO_COLUMNS and track.info is None:
            return "…"
        info = track.info
        e = self.edits
        match col:
            case Col.STATUS:
                return status_text(
                    track.parse_status,
                    changed=e.is_changed(tid),
                    invalid=bool(self._issues[tid]),
                    has_year=e.year(tid) is not None,
                    mismatches=self._mismatches[tid],
                    duplicate=tid in self.duplicate_flags,
                )
            case Col.ARTIST | Col.TITLE | Col.YEAR:
                return format_value(e.value(tid, _EDITABLE[col]))
            case Col.FOLDER:
                return track.folder
            case Col.FILENAME:
                return track.filename
            case Col.DURATION:
                return format_duration(info.duration_s) if info else ""
            case Col.BITRATE:
                return f"{info.bitrate_kbps} kbps" if info and info.bitrate_kbps else ""
            case Col.SIZE:
                return format_size(info.size_bytes) if info else ""
            case Col.TAG_ARTIST:
                return (info.tag_artist or "") if info else ""
            case Col.TAG_TITLE:
                return (info.tag_title or "") if info else ""
            case Col.TAG_YEAR:
                return str(info.tag_year) if info and info.tag_year else ""
            case Col.PLAY:
                return ""  # pictogram via DecorationRole
        return ""

    def _background(self, tid: int, col: Col) -> QColor | None:
        field = col.field
        if field is None:
            return None
        if field in self._issues[tid]:
            return INVALID_BACKGROUND
        if self.edits.is_changed(tid, field):
            return CHANGED_BACKGROUND
        return None

    def _foreground(self, track: Track, tid: int, col: Col) -> QColor | None:
        if col == Col.STATUS:
            if self._issues[tid] or (
                track.parse_status is ParseStatus.ERROR and not self.edits.is_changed(tid)
            ):
                return ERROR_COLOR
            if self._mismatches[tid]:
                return WARNING_COLOR
        elif col in _TAG_FIELD and _TAG_FIELD[col] in self._mismatches[tid]:
            return WARNING_COLOR
        return None

    def _tooltip(self, track: Track, tid: int, col: Col) -> str | None:
        e = self.edits
        if col == Col.STATUS:
            lines = []
            if e.is_changed(tid):
                lines.append(f"Nieuwe naam: {self.target_filename(tid)}")
            if track.copy_number is not None:
                lines.append(
                    f"Volgnummer ({track.copy_number}) na het jaar: waarschijnlijk een kopie; "
                    "wordt genegeerd en verdwijnt bij opslaan."
                )
            if tid in self.duplicate_flags:
                lines.append("Gemarkeerd als duplicaat: de doelnaam bestaat al.")
            if self._misplaced[tid]:
                lines.append("Staat niet in de verwachte jaarmap.")
            if track.parse_status is ParseStatus.ERROR:
                lines.append("Bestandsnaam volgt niet het patroon 'Artiest - Titel (Jaar)'.")
            for field, issues in self._issues[tid].items():
                for issue in issues:
                    lines.append(f"{FIELD_LABEL[field]}: {issue.message}")
            mism = self._mismatches[tid]
            if mism and track.info:
                lines.append("Tags wijken af van de bestandsnaam:")
                tags = {
                    Field.ARTIST: track.info.tag_artist,
                    Field.TITLE: track.info.tag_title,
                    Field.YEAR: track.info.tag_year,
                }
                for f in mism:
                    lines.append(
                        f"  {FIELD_LABEL[f].lower()}: tag '{tags[f]}' ≠ naam '{e.value(tid, f)}'"
                    )
            if track.info and track.info.error:
                lines.append(f"Kon bestand niet lezen: {track.info.error}")
            return "\n".join(lines) or None
        field = col.field
        if field is not None:
            lines = [
                f"{FIELD_LABEL[field]}: {issue.message}"
                for issue in self._issues[tid].get(field, ())
            ]
            if e.is_changed(tid, field):
                lines.append(f"Origineel: {format_value(track.original(field)) or '(leeg)'}")
            return "\n".join(lines) or None
        if col in (Col.FOLDER, Col.FILENAME):
            return str(track.path)
        if col == Col.PLAY:
            return "Stoppen (spatie)" if tid == self._playing else "Afspelen (spatie)"
        return None
