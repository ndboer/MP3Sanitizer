"""Applicatie-instellingen (``settings.json`` in de config-map)."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from mp3sanitizer.core.normalize import DEFAULT_ARTICLES
from mp3sanitizer.core.scanner import DEFAULT_EXTENSIONS
from mp3sanitizer.core.storage import LoadResult, load_document, save_document

log = logging.getLogger(__name__)

SETTINGS_SCHEMA_VERSION = 1
SETTINGS_FILENAME = "settings.json"

DEFAULT_VISIBLE_COLUMNS: tuple[str, ...] = (
    "status",
    "artist",
    "title",
    "year",
    "folder",
    "filename",
)


@dataclass(slots=True)
class Settings:
    extensions: list[str] = field(default_factory=lambda: list(DEFAULT_EXTENSIONS))
    articles: list[str] = field(default_factory=lambda: list(DEFAULT_ARTICLES))
    last_root: str | None = None
    visible_columns: list[str] = field(default_factory=lambda: list(DEFAULT_VISIBLE_COLUMNS))
    window_geometry: str | None = None  # base64 van QWidget.saveGeometry()
    header_state: str | None = None  # base64 van QHeaderView.saveState()
    # Opslaan (zie core.planner)
    folder_template: str = "none"  # "none" | "year" | "decade"
    decade_style: str = "range"  # "range" (1980-1989) | "short" (80s)
    unknown_year_folder: str = "_Onbekend"
    collision_policy: str = "skip"  # "skip" | "suffix" | "mark_duplicate"
    write_tags: bool = False
    cleanup_empty_dirs: bool = True
    # Afspelen
    volume: int = 80  # procent
    autoplay_next: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        """Onbekende sleutels worden genegeerd; waarden van het verkeerde type vallen terug."""
        default = cls()
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            expected = getattr(default, f.name)
            if isinstance(expected, bool):
                ok = isinstance(value, bool)
            elif isinstance(expected, int):
                ok = isinstance(value, int) and not isinstance(value, bool)
            elif isinstance(expected, list):
                ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
            elif isinstance(expected, str):
                ok = isinstance(value, str)
            else:  # optionele tekst
                ok = value is None or isinstance(value, str)
            if ok:
                kwargs[f.name] = value
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SettingsStore:
    """Houdt bij waar de instellingen staan en of ze mogen worden overschreven."""

    path: Path
    settings: Settings
    load_result: LoadResult

    @classmethod
    def load(cls, config_dir: Path) -> SettingsStore:
        path = config_dir / SETTINGS_FILENAME
        result = load_document(path, SETTINGS_SCHEMA_VERSION)
        settings = Settings.from_dict(result.data) if result.data else Settings()
        return cls(path, settings, result)

    def save(self) -> bool:
        if not self.load_result.writable:
            log.info("Instellingen niet opgeslagen: bestand is van een nieuwere versie")
            return False
        save_document(self.path, self.settings.to_dict(), SETTINGS_SCHEMA_VERSION)
        return True
