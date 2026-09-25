"""Lezen en schrijven van JSON-bestanden met een ``schema_version``.

- Ontbreekt het bestand: status ``MISSING``, de aanroeper gebruikt standaardwaarden.
- Corrupt of onleesbaar: het bestand wordt bewaard als ``<naam>.corrupt``, status ``CORRUPT``.
- Nieuwer schema dan de app kent: status ``NEWER``; de aanroeper mag het bestand niet overschrijven.
- Ouder schema: ``migrate`` wordt stap voor stap aangeroepen, na een back-up ``<naam>.v<oud>.bak``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEMA_KEY = "schema_version"

Migration = Callable[[dict[str, Any]], dict[str, Any]]


class LoadStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    MIGRATED = "migrated"
    CORRUPT = "corrupt"
    NEWER = "newer"


@dataclass(slots=True)
class LoadResult:
    status: LoadStatus
    data: dict[str, Any] = field(default_factory=dict)
    file_version: int | None = None
    message: str | None = None

    @property
    def writable(self) -> bool:
        return self.status is not LoadStatus.NEWER


def _quarantine(path: Path) -> Path:
    target = path.with_name(path.name + ".corrupt")
    try:
        os.replace(path, target)
    except OSError as exc:
        log.error("Kan corrupt bestand niet apart zetten: %s (%s)", path, exc)
    return target


def load_document(
    path: Path,
    current_version: int,
    migrations: Mapping[int, Migration] | None = None,
) -> LoadResult:
    """Laad een JSON-document. ``migrations[n]`` zet schema ``n`` om naar ``n + 1``."""
    if not path.exists():
        return LoadResult(LoadStatus.MISSING)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("verwacht een JSON-object")
        version = data.get(SCHEMA_KEY, 1)
        if not isinstance(version, int) or version < 1:
            raise ValueError(f"ongeldige {SCHEMA_KEY}: {version!r}")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        target = _quarantine(path)
        msg = f"{path.name} is onleesbaar ({exc}); standaardwaarden gebruikt. Kopie: {target.name}"
        log.warning(msg)
        return LoadResult(LoadStatus.CORRUPT, message=msg)

    if version > current_version:
        msg = (
            f"{path.name} is gemaakt met een nieuwere versie van Mp3Sanitizer "
            f"(schema {version}, deze versie kent t/m {current_version}). "
            "Het bestand wordt niet overschreven."
        )
        log.warning(msg)
        return LoadResult(LoadStatus.NEWER, data=data, file_version=version, message=msg)

    if version == current_version:
        return LoadResult(LoadStatus.OK, data=data, file_version=version)

    backup = path.with_name(f"{path.name}.v{version}.bak")
    shutil.copy2(path, backup)
    migrations = migrations or {}
    migrated = dict(data)
    for step in range(version, current_version):
        migrate = migrations.get(step)
        if migrate is None:
            raise LookupError(f"geen migratie van schema {step} naar {step + 1} voor {path.name}")
        migrated = migrate(migrated)
        migrated[SCHEMA_KEY] = step + 1
    log.info("%s gemigreerd van schema %d naar %d", path.name, version, current_version)
    return LoadResult(LoadStatus.MIGRATED, data=migrated, file_version=version)


def save_document(path: Path, data: Mapping[str, Any], version: int) -> None:
    """Schrijf atomair (via een tijdelijk bestand) met ``schema_version`` vooraan."""
    payload = {SCHEMA_KEY: version, **{k: v for k, v in data.items() if k != SCHEMA_KEY}}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
