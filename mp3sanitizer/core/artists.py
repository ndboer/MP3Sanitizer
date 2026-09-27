"""Artiestvelden met samenwerkingen: splitsen in losse artiesten en één artiest vervangen.

Een artiestveld kan meerdere artiesten bevatten, bijvoorbeeld ``Queen & David Bowie`` of
``Eminem ft. Dido``. Bij het corrigeren van een schrijfwijze moet alleen die ene artiest worden
vervangen; de andere artiesten en de scheidingstekens blijven staan.

Scheidingstekens: ``&``, ``,``, ``+``, ``;``, ``x``, ``vs.``/``versus``, ``feat.``/``ft.``/
``featuring``, ``with``, ``met``, ``and``, ``en``. Uitzonderingen:

- ``Beatles, The`` is één artiest (een lidwoord achter een komma hoort bij de naam);
- ``AC/DC`` wordt niet gesplitst (``/`` is geen scheidingsteken).

Bij namen als ``Simon & Garfunkel`` of ``Earth, Wind & Fire`` levert splitsen losse delen op;
daarom kijken zoeken en voorstellen zowel naar het hele veld als naar de delen.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from mp3sanitizer.core.normalize import DEFAULT_ARTICLES

_SEPARATOR = re.compile(
    r"\s*(?:[&,+;]|\b(?:x|vs\.?|versus|feat\.?|ft\.?|featuring|with|met|and|en)\b\.?)\s*",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ArtistPart:
    name: str
    start: int  # positie in het oorspronkelijke veld
    end: int


def split_artists(text: str, articles: Iterable[str] = DEFAULT_ARTICLES) -> list[ArtistPart]:
    """Splits een artiestveld in losse artiesten (met hun positie in de tekst)."""
    article_set = {a.casefold() for a in articles}
    parts: list[ArtistPart] = []
    pos = 0
    separators = list(_SEPARATOR.finditer(text))
    for sep in [*separators, None]:
        end = sep.start() if sep else len(text)
        raw = text[pos:end]
        name = raw.strip()
        if name:
            start = pos + (len(raw) - len(raw.lstrip()))
            end_name = start + len(name)
            prev = parts[-1] if parts else None
            if (
                prev is not None
                and name.casefold() in article_set
                and text[prev.end : start].strip() == ","
            ):
                # "Beatles, The": het lidwoord hoort bij de vorige naam
                parts[-1] = ArtistPart(text[prev.start : end_name], prev.start, end_name)
            else:
                parts.append(ArtistPart(name, start, end_name))
        if sep is not None:
            pos = sep.end()
    return parts


def artist_names(text: str, articles: Iterable[str] = DEFAULT_ARTICLES) -> list[str]:
    return [p.name for p in split_artists(text, articles)]


def is_collaboration(text: str, articles: Iterable[str] = DEFAULT_ARTICLES) -> bool:
    return len(split_artists(text, articles)) > 1


def replace_artist(
    text: str, old: str, new: str, articles: Iterable[str] = DEFAULT_ARTICLES
) -> str | None:
    """Vervang artiest ``old`` door ``new`` in het veld ``text``.

    - Is het hele veld gelijk aan ``old``, dan wordt het ``new``.
    - Anders wordt elk deel dat exact ``old`` is vervangen; de rest blijft staan.
    - ``None`` als ``old`` niet in het veld voorkomt.
    """
    if text.strip() == old.strip():
        return new
    parts = [p for p in split_artists(text, articles) if p.name == old.strip()]
    if not parts:
        return None
    for part in reversed(parts):  # van achter naar voren, zodat posities kloppen
        text = text[: part.start] + new + text[part.end :]
    return text
