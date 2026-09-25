"""Tabelmodel voor de tracks (``QAbstractTableModel``)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from enum import IntEnum
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtGui import QColor

from mp3sanitizer.core.models import AudioInfo, Field, ParseStatus, Track
from mp3sanitizer.core.normalize import DEFAULT_ARTICLES, fold, sort_key
from mp3sanitizer.core.tags import tag_mismatches

TRACK_ROLE = Qt.ItemDataRole.UserRole + 1

ERROR_COLOR = QColor("#d9534f")
WARNING_COLOR = QColor("#e08a00")

type AnyIndex = QModelIndex | QPersistentModelIndex


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

    @property
    def key(self) -> str:
        return self.name.lower()

    @property
    def header(self) -> str:
        return _HEADERS[self]

    @property
    def optional(self) -> bool:
        return self >= Col.DURATION

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
}

_RIGHT_ALIGNED = {Col.YEAR, Col.DURATION, Col.BITRATE, Col.SIZE, Col.TAG_YEAR}
_INFO_COLUMNS = {Col.DURATION, Col.BITRATE, Col.SIZE, Col.TAG_ARTIST, Col.TAG_TITLE, Col.TAG_YEAR}
_TAG_FIELD = {Col.TAG_ARTIST: Field.ARTIST, Col.TAG_TITLE: Field.TITLE, Col.TAG_YEAR: Field.YEAR}
_FIELD_LABEL = {Field.ARTIST: "artiest", Field.TITLE: "titel", Field.YEAR: "jaar"}


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


def status_text(track: Track, mismatches: Sequence[Field]) -> str:
    match track.parse_status:
        case ParseStatus.ERROR:
            text = "Parse-fout"
        case ParseStatus.NO_YEAR:
            text = "Geen jaar"
        case _:
            text = "OK"
    return text + " · tags ≠" if mismatches else text


class TrackTableModel(QAbstractTableModel):
    def __init__(self, articles: Iterable[str] = DEFAULT_ARTICLES, parent=None) -> None:
        super().__init__(parent)
        self._articles = tuple(articles)
        self._tracks: list[Track] = []
        # Gecachete sleutels per track-id, zodat sorteren en filteren snel blijven.
        self._artist_keys: list[str] = []
        self._title_keys: list[str] = []
        self._folder_keys: list[str] = []
        self._search_keys: list[str] = []
        self._mismatches: list[tuple[Field, ...]] = []
        # _order[rij] = track-id; _rows[track-id] = rij
        self._order: list[int] = []
        self._rows: list[int] = []
        self._sort_col: Col | None = None
        self._sort_order = Qt.SortOrder.AscendingOrder

    # --- toegang -------------------------------------------------------------------------
    @property
    def tracks(self) -> Sequence[Track]:
        """Alle tracks in id-volgorde (onafhankelijk van de sortering)."""
        return self._tracks

    def track(self, row: int) -> Track:
        return self._tracks[self._order[row]]

    def row_of(self, track_id: int) -> int:
        return self._rows[track_id]

    def mismatches(self, row: int) -> tuple[Field, ...]:
        return self._mismatches[self._order[row]]

    def search_key(self, row: int) -> str:
        """Gevouwen 'artiest\\0titel\\0bestandsnaam' voor het zoekfilter."""
        return self._search_keys[self._order[row]]

    def parse_error_count(self) -> int:
        return sum(1 for t in self._tracks if t.parse_status is ParseStatus.ERROR)

    # --- mutaties ------------------------------------------------------------------------
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
        ):
            cache.clear()
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
            self._artist_keys.append(sort_key(track.artist, self._articles))
            self._title_keys.append(fold(track.title))
            self._folder_keys.append(fold(track.folder))
            self._search_keys.append(fold(f"{track.artist}\x00{track.title}\x00{track.filename}"))
            self._mismatches.append(())
        self.endInsertRows()
        if resort:
            self.resort()

    def set_infos(self, infos: Iterable[tuple[int, AudioInfo]]) -> None:
        """Werk de lazy ingelezen gegevens bij (op track-id)."""
        rows = []
        for track_id, info in infos:
            if 0 <= track_id < len(self._tracks):
                track = self._tracks[track_id]
                track.info = info
                self._mismatches[track_id] = tuple(
                    tag_mismatches(track.artist, track.title, track.year, info)
                )
                rows.append(self._rows[track_id])
        if rows:
            self.dataChanged.emit(self.index(min(rows), 0), self.index(max(rows), len(Col) - 1))

    # --- sorteren ------------------------------------------------------------------------
    # Het model sorteert zelf (één ``sorted`` op gecachete sleutels). Sorteren in de proxy zou
    # per vergelijking Python-``data()`` aanroepen en is bij 10.000 rijen seconden trager.
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
        mism = self._mismatches

        def info_value(attr: str) -> Callable[[int], tuple[float, str, str]]:
            def key(i: int) -> tuple[float, str, str]:
                info = t[i].info
                value = -1.0 if info is None else float(getattr(info, attr) or 0)
                return (value, artist[i], title[i])

            return key

        def tag_text(i: int, attr: str) -> str:
            info = t[i].info
            return (getattr(info, attr) or "") if info else ""

        match col:
            case Col.STATUS:
                return lambda i: (t[i].parse_status, len(mism[i]), artist[i], title[i])
            case Col.ARTIST:
                # Lege artiest (parse-fout) onderaan in plaats van bovenaan.
                return lambda i: (not artist[i], artist[i], title[i])
            case Col.TITLE:
                return lambda i: (title[i], artist[i])
            case Col.YEAR:
                return lambda i: (t[i].year or 0, artist[i], title[i])
            case Col.FOLDER:
                return lambda i: (folder[i], artist[i], title[i])
            case Col.FILENAME:
                return lambda i: fold(t[i].filename)
            case Col.DURATION:
                return info_value("duration_s")
            case Col.BITRATE:
                return info_value("bitrate_kbps")
            case Col.SIZE:
                return info_value("size_bytes")
            case Col.TAG_YEAR:
                return info_value("tag_year")
            case Col.TAG_ARTIST:
                return lambda i: sort_key(tag_text(i, "tag_artist"), self._articles)
            case Col.TAG_TITLE:
                return lambda i: fold(tag_text(i, "tag_title"))

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
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        tid = self._order[index.row()]
        col = Col(index.column())
        track = self._tracks[tid]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(track, tid, col)
        if role == TRACK_ROLE:
            return track
        if role == Qt.ItemDataRole.TextAlignmentRole and col in _RIGHT_ALIGNED:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(track, tid, col)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(track, tid, col)
        return None

    # --- rollen --------------------------------------------------------------------------
    def _display(self, track: Track, tid: int, col: Col) -> str:
        if col in _INFO_COLUMNS and track.info is None:
            return "…"
        info = track.info
        match col:
            case Col.STATUS:
                return status_text(track, self._mismatches[tid])
            case Col.ARTIST:
                return track.artist
            case Col.TITLE:
                return track.title
            case Col.YEAR:
                return "" if track.year is None else str(track.year)
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
        return ""

    def _foreground(self, track: Track, tid: int, col: Col) -> QColor | None:
        if col == Col.STATUS:
            if track.parse_status is ParseStatus.ERROR:
                return ERROR_COLOR
            if self._mismatches[tid]:
                return WARNING_COLOR
        elif col in _TAG_FIELD and _TAG_FIELD[col] in self._mismatches[tid]:
            return WARNING_COLOR
        return None

    def _tooltip(self, track: Track, tid: int, col: Col) -> str | None:
        if col == Col.STATUS:
            lines = []
            if track.parse_status is ParseStatus.ERROR:
                lines.append("Bestandsnaam volgt niet het patroon 'Artiest - Titel (Jaar)'.")
            mism = self._mismatches[tid]
            if mism and track.info:
                lines.append("Tags wijken af van de bestandsnaam:")
                values = {
                    Field.ARTIST: (track.info.tag_artist, track.artist),
                    Field.TITLE: (track.info.tag_title, track.title),
                    Field.YEAR: (track.info.tag_year, track.year),
                }
                for f in mism:
                    tag, name = values[f]
                    lines.append(f"  {_FIELD_LABEL[f]}: tag '{tag}' ≠ naam '{name}'")
            if track.info and track.info.error:
                lines.append(f"Kon bestand niet lezen: {track.info.error}")
            return "\n".join(lines) or None
        if col in (Col.FOLDER, Col.FILENAME):
            return str(track.path)
        return None
