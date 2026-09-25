"""Schema-migraties voor alle JSON-bestanden die de app schrijft.

Per soort bestand een dict ``{oude_versie: functie}``; ``storage.load_document`` roept ze stap
voor stap aan (1 → 2 → 3 …) na een back-up ``<naam>.v<oud>.bak``. Een migratie krijgt de
gegevens van versie ``n`` en geeft die van versie ``n + 1`` terug; ``schema_version`` wordt door
``load_document`` bijgewerkt.

Nieuwe migratie toevoegen:

1. verhoog de ``*_SCHEMA_VERSION`` van het bestand;
2. schrijf ``migrate_<soort>_<n>_to_<n+1>`` hieronder en registreer die;
3. voeg een fixture van de oude versie toe in ``tests/fixtures/`` met een test.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mp3sanitizer.core.storage import Migration


def migrate_journal_1_to_2(data: dict[str, Any]) -> dict[str, Any]:
    """Schema 2 legt de appversie per journaalregel vast (was alleen per batch)."""
    version = data.get("app_version", "onbekend")
    entries = []
    for entry in data.get("entries", []):
        if isinstance(entry, dict):
            entry = {**entry}
            entry.setdefault("app_version", version)
        entries.append(entry)
    return {**data, "entries": entries}


JOURNAL: Mapping[int, Migration] = {1: migrate_journal_1_to_2}
SETTINGS: Mapping[int, Migration] = {}
RULES: Mapping[int, Migration] = {}
PROJECT: Mapping[int, Migration] = {}
MUSICBRAINZ_CACHE: Mapping[int, Migration] = {}
