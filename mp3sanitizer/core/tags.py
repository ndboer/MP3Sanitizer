"""Tags, duur en bitrate lezen (en artiest/titel/jaar schrijven) met mutagen."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import mutagen

from mp3sanitizer.core.models import AudioInfo, Field, TagValues
from mp3sanitizer.core.normalize import loose_equal

log = logging.getLogger(__name__)

_YEAR = re.compile(r"(\d{4})")


def _first(tags: object, key: str) -> str | None:
    try:
        values = tags[key]  # type: ignore[index]
    except (KeyError, TypeError, ValueError):
        return None
    if isinstance(values, list | tuple):
        values = values[0] if values else None
    if values is None:
        return None
    text = str(values).strip()
    return text or None


def _year(text: str | None) -> int | None:
    if not text:
        return None
    match = _YEAR.search(text)
    return int(match.group(1)) if match else None


def read_audio_info(path: Path) -> AudioInfo:
    """Lees duur, bitrate, grootte en de artiest/titel/jaar-tags. Faalt nooit."""
    info = AudioInfo()
    try:
        info.size_bytes = path.stat().st_size
    except OSError as exc:
        info.error = str(exc)
        return info
    try:
        audio = mutagen.File(path, easy=True)
    except Exception as exc:  # mutagen gooit uiteenlopende excepties bij kapotte bestanden
        log.debug("Tags niet leesbaar: %s (%s)", path, exc)
        info.error = str(exc) or type(exc).__name__
        return info
    if audio is None:
        info.error = "Onbekend formaat"
        return info
    stream = getattr(audio, "info", None)
    if stream is not None:
        length = getattr(stream, "length", None)
        info.duration_s = float(length) if length else None
        bitrate = getattr(stream, "bitrate", None)
        info.bitrate_kbps = round(bitrate / 1000) if bitrate else None
    tags = audio.tags
    if tags is not None:
        info.tag_artist = _first(tags, "artist")
        info.tag_title = _first(tags, "title")
        info.tag_year = _year(_first(tags, "date") or _first(tags, "year"))
    return info


def tag_mismatches(
    artist: str, title: str, year: int | None, info: AudioInfo | None
) -> list[Field]:
    """Velden waarvan de tag afwijkt van de bestandsnaam. Ontbrekende tags tellen niet mee."""
    if info is None:
        return []
    result = []
    if info.tag_artist is not None and not loose_equal(info.tag_artist, artist):
        result.append(Field.ARTIST)
    if info.tag_title is not None and not loose_equal(info.tag_title, title):
        result.append(Field.TITLE)
    if info.tag_year is not None and year is not None and info.tag_year != year:
        result.append(Field.YEAR)
    return result


class TagWriteError(Exception):
    pass


def write_tags(path: Path, values: TagValues) -> TagValues:
    """Schrijf artiest, titel en jaar (``date``). Geeft de oude waarden terug (voor undo).

    Een waarde ``None`` verwijdert de tag. Formaten zonder 'easy'-tags (bijv. sommige WAV's)
    geven een ``TagWriteError``.
    """
    try:
        audio = mutagen.File(path, easy=True)
    except Exception as exc:
        raise TagWriteError(f"Kan bestand niet openen: {exc}") from exc
    if audio is None:
        raise TagWriteError("Onbekend formaat")
    if audio.tags is None:
        try:
            audio.add_tags()
        except Exception as exc:
            raise TagWriteError(f"Kan geen tags toevoegen: {exc}") from exc
    tags = audio.tags
    before = TagValues(_first(tags, "artist"), _first(tags, "title"), _first(tags, "date"))
    try:
        for key, value in values.to_dict().items():
            if value is None:
                if key in tags:
                    del tags[key]
            else:
                tags[key] = [value]
        audio.save()
    except Exception as exc:  # mutagen: uiteenlopende excepties per formaat
        raise TagWriteError(f"Tags schrijven mislukt: {exc}") from exc
    return before
