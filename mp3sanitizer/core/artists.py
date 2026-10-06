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

from rapidfuzz import fuzz

from mp3sanitizer.core.normalize import DEFAULT_ARTICLES, match_key

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


WHOLE_FIELD_RATIO = 90


def covers_whole_field(text: str, new: str, articles: Iterable[str] = DEFAULT_ARTICLES) -> bool:
    """Is ``new`` een schrijfwijze van het hele veld ``text`` (niet van één deel ervan)?"""
    articles = tuple(articles)
    a, b = match_key(text, articles), match_key(new, articles)
    return bool(a) and fuzz.ratio(a, b) >= WHOLE_FIELD_RATIO


def replace_artist(
    text: str, old: str, new: str, articles: Iterable[str] = DEFAULT_ARTICLES
) -> str | None:
    """Vervang artiest ``old`` door ``new`` in het veld ``text``.

    - Is het hele veld gelijk aan ``old``, dan wordt het ``new``.
    - Dekt ``new`` het hele veld al ("adam and the ants" → "Adam and the Ants", terwijl alleen
      het deel "adam" gezocht werd), dan wordt ook het hele veld ``new``. Anders zou het
      'samenwerkingsdeel' vervangen worden: "Adam and the Ants and the ants".
    - Anders wordt elk deel dat exact ``old`` is vervangen; de rest blijft staan. Dekt ``new``
      meerdere aangrenzende delen ("Billy Cotton" + "His Band" in "Billy Cotton & His Band,
      Alan Breeze"), dan wordt dat hele stuk vervangen en blijft "Alan Breeze" staan.
    - ``None`` als ``old`` niet in het veld voorkomt.
    """
    articles = tuple(articles)
    if text.strip() == old.strip() or covers_whole_field(text, new, articles):
        return new
    all_parts = split_artists(text, articles)
    spans: list[tuple[int, int]] = []
    for k, part in enumerate(all_parts):
        if part.name != old.strip():
            continue
        start, end = part.start, part.end
        # Het langste aaneengesloten stuk rond dit deel dat ``new`` al volledig beschrijft.
        best = 0
        for i in range(k + 1):
            for j in range(k, len(all_parts)):
                span = text[all_parts[i].start : all_parts[j].end]
                if j - i > best and covers_whole_field(span, new, articles):
                    best, start, end = j - i, all_parts[i].start, all_parts[j].end
        if not spans or start >= spans[-1][1]:
            spans.append((start, end))
    if not spans:
        return None
    for start, end in reversed(spans):  # van achter naar voren, zodat posities kloppen
        text = text[:start] + new + text[end:]
    return text
