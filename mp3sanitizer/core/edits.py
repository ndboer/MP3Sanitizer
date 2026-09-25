"""Niet-opgeslagen wijzigingen: overrides bovenop de geparste waarden van elke track."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from mp3sanitizer.core.models import Field, FieldValue, PendingChange, Track


class EditState:
    """Houdt per track de afwijkende veldwaarden bij.

    Een override die gelijk wordt aan de originele waarde verdwijnt vanzelf, zodat
    'gewijzigd' altijd betekent: verschilt van wat er op schijf staat.
    """

    def __init__(self, tracks: Sequence[Track]) -> None:
        self._tracks = tracks
        self._overrides: dict[int, dict[Field, FieldValue]] = {}

    # --- lezen ---------------------------------------------------------------------------
    def value(self, track_id: int, field: Field) -> FieldValue:
        fields = self._overrides.get(track_id)
        if fields is not None and field in fields:
            return fields[field]
        return self._tracks[track_id].original(field)

    def artist(self, track_id: int) -> str:
        return str(self.value(track_id, Field.ARTIST))

    def title(self, track_id: int) -> str:
        return str(self.value(track_id, Field.TITLE))

    def year(self, track_id: int) -> int | None:
        value = self.value(track_id, Field.YEAR)
        return value if isinstance(value, int) else None

    def is_changed(self, track_id: int, field: Field | None = None) -> bool:
        fields = self._overrides.get(track_id)
        if not fields:
            return False
        return field is None or field in fields

    def changed_fields(self, track_id: int) -> tuple[Field, ...]:
        fields = self._overrides.get(track_id, {})
        return tuple(f for f in Field if f in fields)

    @property
    def changed_ids(self) -> set[int]:
        return set(self._overrides)

    def __len__(self) -> int:
        """Aantal gewijzigde tracks."""
        return len(self._overrides)

    # --- wijzigingen maken ---------------------------------------------------------------
    def change(
        self, track_id: int, field: Field, new: FieldValue, source: str = "manual"
    ) -> PendingChange | None:
        """Maak een wijziging (zonder toe te passen); ``None`` als er niets verandert."""
        old = self.value(track_id, field)
        if old == new:
            return None
        return PendingChange(track_id, field, old, new, source)

    def swap_changes(self, track_ids: Iterable[int]) -> list[PendingChange]:
        changes = []
        for tid in track_ids:
            artist, title = self.artist(tid), self.title(tid)
            if artist != title:
                changes.append(PendingChange(tid, Field.ARTIST, artist, title, "swap"))
                changes.append(PendingChange(tid, Field.TITLE, title, artist, "swap"))
        return changes

    def revert_changes(self, track_ids: Iterable[int]) -> list[PendingChange]:
        changes = []
        for tid in track_ids:
            track = self._tracks[tid]
            for field, value in self._overrides.get(tid, {}).items():
                changes.append(PendingChange(tid, field, value, track.original(field), "revert"))
        return changes

    # --- toepassen -----------------------------------------------------------------------
    def apply(self, changes: Iterable[PendingChange], *, forward: bool = True) -> set[int]:
        """Pas wijzigingen toe (``forward``) of draai ze terug. Geeft de geraakte track-ids."""
        ordered = list(changes) if forward else list(reversed(list(changes)))
        touched = set()
        for c in ordered:
            self._set(c.track_id, c.field, c.new if forward else c.old)
            touched.add(c.track_id)
        return touched

    def clear(self) -> None:
        self._overrides.clear()

    def _set(self, track_id: int, field: Field, value: FieldValue) -> None:
        if value == self._tracks[track_id].original(field):
            fields = self._overrides.get(track_id)
            if fields is not None:
                fields.pop(field, None)
                if not fields:
                    del self._overrides[track_id]
        else:
            self._overrides.setdefault(track_id, {})[field] = value
