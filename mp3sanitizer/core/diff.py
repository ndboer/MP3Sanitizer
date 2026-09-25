"""Tekstverschillen voor het markeren van wijzigingen in previews (``difflib``)."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from enum import StrEnum


class Seg(StrEnum):
    SAME = "same"
    REMOVED = "removed"  # alleen in de oude tekst
    ADDED = "added"  # alleen in de nieuwe tekst


type Segments = list[tuple[str, Seg]]


_TOKEN = re.compile(r"\w+|\W")


def diff_segments(old: str, new: str) -> tuple[Segments, Segments]:
    """Splits ``old`` en ``new`` in stukken die gelijk, verwijderd of toegevoegd zijn.

    Er wordt per woord vergeleken (leestekens en spaties apart), zodat 'take' → 'Take' als heel
    woord wordt gemarkeerd in plaats van als losse letters. ``autojunk`` staat uit: bij korte
    strings zoals bestandsnamen geeft dat betere resultaten.
    """
    a, b = _TOKEN.findall(old), _TOKEN.findall(new)
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    old_segs: Segments = []
    new_segs: Segments = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            _append(old_segs, "".join(a[i1:i2]), Seg.SAME)
            _append(new_segs, "".join(b[j1:j2]), Seg.SAME)
        else:  # replace, delete, insert
            _append(old_segs, "".join(a[i1:i2]), Seg.REMOVED)
            _append(new_segs, "".join(b[j1:j2]), Seg.ADDED)
    return old_segs, new_segs


def _append(segs: Segments, text: str, kind: Seg) -> None:
    if not text:
        return
    if segs and segs[-1][1] is kind:
        segs[-1] = (segs[-1][0] + text, kind)
    else:
        segs.append((text, kind))
