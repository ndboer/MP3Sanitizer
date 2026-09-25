"""Rename-planner: bepaalt per track het doelpad en lost botsingen op. Raakt niets aan op schijf.

Botsingen worden nooit automatisch overschreven. Afhankelijk van de gekozen ``Collision``:
overslaan, een suffix " (2)" toevoegen of de track als duplicaat markeren.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from mp3sanitizer.core.models import Collision, PlanWarning, RenamePlan, TagValues
from mp3sanitizer.core.parser import format_stem
from mp3sanitizer.core.validate import Issue, stem_issues, text_issues

MAX_PATH = 259  # Windows MAX_PATH (260) min de afsluitende nul


class FolderTemplate(StrEnum):
    NONE = "none"  # niet verplaatsen
    YEAR = "year"  # 1985\
    DECADE = "decade"  # 1980-1989\ of 80s\


class DecadeStyle(StrEnum):
    RANGE = "range"
    SHORT = "short"


def folder_for_year(
    year: int | None,
    template: FolderTemplate,
    style: DecadeStyle = DecadeStyle.RANGE,
    unknown: str = "_Onbekend",
) -> str | None:
    """Relatieve doelmap voor een jaar, of ``None`` als er niet verplaatst wordt."""
    if template is FolderTemplate.NONE:
        return None
    if year is None:
        return unknown
    if template is FolderTemplate.YEAR:
        return str(year)
    decade = year // 10 * 10
    if style is DecadeStyle.RANGE:
        return f"{decade}-{decade + 9}"
    # '80s' voor de twintigste eeuw; vanaf 2000 voluit ('2000s'), anders is '00s' dubbelzinnig.
    return f"{decade % 100:02d}s" if decade < 2000 else f"{decade}s"


@dataclass(frozen=True, slots=True)
class PlanInput:
    track_id: int
    src: Path
    artist: str
    title: str
    year: int | None
    changed: bool  # heeft niet-opgeslagen wijzigingen
    tag_mismatch: bool = False


@dataclass(frozen=True, slots=True)
class PlanOptions:
    root: Path
    folder_template: FolderTemplate = FolderTemplate.NONE
    decade_style: DecadeStyle = DecadeStyle.RANGE
    unknown_folder: str = "_Onbekend"
    collision: Collision = Collision.SKIP
    write_tags: bool = False
    include_unchanged: bool = False  # ook niet-bewerkte tracks normaliseren/verplaatsen


def path_key(path: Path | str) -> str:
    """Vergelijkingssleutel voor paden; hoofdletterongevoelig zoals NTFS."""
    return os.path.normcase(os.fspath(path)).casefold()


def same_path(a: Path, b: Path) -> bool:
    """Exact dezelfde schrijfwijze. (``WindowsPath ==`` negeert hoofdletters!)"""
    return os.fspath(a) == os.fspath(b)


def target_stem(inp: PlanInput) -> str:
    return format_stem(inp.artist, inp.title, inp.year)


def target_path(inp: PlanInput, opts: PlanOptions) -> Path:
    name = target_stem(inp) + inp.src.suffix
    folder = folder_for_year(inp.year, opts.folder_template, opts.decade_style, opts.unknown_folder)
    directory = inp.src.parent if folder is None else opts.root / folder
    return directory / name


def is_misplaced(folder: str, year: int | None, opts: PlanOptions) -> bool:
    """Staat een track (relatieve map ``folder``) in de verkeerde jaarmap?"""
    expected = folder_for_year(year, opts.folder_template, opts.decade_style, opts.unknown_folder)
    return expected is not None and path_key(folder) != path_key(expected)


_NOTES = {
    PlanWarning.EXISTS: "Doelbestand bestaat al",
    PlanWarning.DUPLICATE_TARGET: "Een andere track krijgt dezelfde naam",
    PlanWarning.SUFFIXED: "Suffix toegevoegd vanwege botsing",
    PlanWarning.CASE_ONLY: "Alleen hoofdletters wijzigen (via tijdelijke naam)",
    PlanWarning.PATH_TOO_LONG: f"Pad langer dan {MAX_PATH} tekens",
    PlanWarning.INVALID_NAME: "Ongeldige naam",
    PlanWarning.TAGS_ONLY: "Alleen tags bijwerken",
}
_COLLISION_NOTES = {
    Collision.SKIP: "overgeslagen",
    Collision.MARK_DUPLICATE: "gemarkeerd als duplicaat",
    Collision.SUFFIX: "",
}


@dataclass(slots=True)
class _Candidate:
    inp: PlanInput
    dst: Path
    tags: TagValues | None
    invalid: tuple[str, ...]  # redenen waarom de naam ongeldig is


def _tags_for(inp: PlanInput) -> TagValues:
    return TagValues(inp.artist, inp.title, None if inp.year is None else str(inp.year))


def _invalid_reasons(inp: PlanInput, opts: PlanOptions) -> tuple[str, ...]:
    reasons = []
    if Issue.EMPTY in text_issues(inp.artist):
        reasons.append("artiest ontbreekt")
    if Issue.EMPTY in text_issues(inp.title):
        reasons.append("titel ontbreekt")
    # Controleer de naam als tekst: in een Path zou 'AC/DC' een submap worden.
    issues = set(stem_issues(target_stem(inp)))
    folder = folder_for_year(inp.year, opts.folder_template, opts.decade_style, opts.unknown_folder)
    if folder is not None:
        issues.update(stem_issues(folder))
    issues.discard(Issue.EMPTY)  # al gemeld als ontbrekend veld
    reasons += [i.message.lower() for i in sorted(issues)]
    return tuple(reasons)


def plan_renames(
    inputs: Iterable[PlanInput],
    opts: PlanOptions,
    exists: Callable[[Path], bool] = os.path.exists,
) -> list[RenamePlan]:
    """Maak een plan voor alle tracks die hernoemd, verplaatst of getagd moeten worden."""
    candidates: list[_Candidate] = []
    for inp in inputs:
        if not inp.changed and not opts.include_unchanged:
            continue
        dst = target_path(inp, opts)
        tags = _tags_for(inp) if opts.write_tags else None
        if same_path(dst, inp.src) and not (tags is not None and (inp.changed or inp.tag_mismatch)):
            continue
        candidates.append(_Candidate(inp, dst, tags, _invalid_reasons(inp, opts)))

    # Bestanden die blijven staan (ongeldig, alleen tags, of een overgeslagen botsing) houden hun
    # plek bezet. Een botsing kan een plan blokkeren, waardoor weer een ander plan kan botsen;
    # herhaal tot het resultaat stabiel is.
    staying = {path_key(c.inp.src) for c in candidates if c.invalid or same_path(c.dst, c.inp.src)}
    while True:
        plans, new_staying = _resolve(candidates, opts, exists, staying)
        if new_staying == staying:
            return plans
        staying = new_staying


def _resolve(
    candidates: Sequence[_Candidate],
    opts: PlanOptions,
    exists: Callable[[Path], bool],
    staying: set[str],
) -> tuple[list[RenamePlan], set[str]]:
    moving = {path_key(c.inp.src) for c in candidates if path_key(c.inp.src) not in staying}
    claimed: set[str] = set()  # doelen van eerdere (uitvoerbare) plannen
    new_staying = set(staying)
    plans: list[RenamePlan] = []

    def occupied(path: Path) -> PlanWarning | None:
        key = path_key(path)
        if key in claimed:
            return PlanWarning.DUPLICATE_TARGET
        if key in staying or (key not in moving and exists(path)):
            return PlanWarning.EXISTS
        return None

    for c in candidates:
        src, dst = c.inp.src, c.dst
        warnings: list[PlanWarning] = []
        notes: list[str] = []
        blocked = False
        collision: Collision | None = None
        tags_only = same_path(dst, src)

        if c.invalid:
            blocked = True
            warnings.append(PlanWarning.INVALID_NAME)
            notes.append(f"{_NOTES[PlanWarning.INVALID_NAME]}: {', '.join(c.invalid)}")
        case_only = not tags_only and path_key(src) == path_key(dst)

        if not blocked and not tags_only:
            if case_only:  # het bestand zelf 'bestaat' al; alleen andere plannen tellen
                in_use = path_key(dst) in claimed
                conflict = PlanWarning.DUPLICATE_TARGET if in_use else None
            else:
                conflict = occupied(dst)
            if conflict is not None:
                warnings.append(conflict)
                collision = opts.collision
                if collision is Collision.SUFFIX:
                    n = 2
                    candidate = dst.with_name(f"{dst.stem} ({n}){dst.suffix}")
                    while occupied(candidate) is not None:
                        n += 1
                        candidate = dst.with_name(f"{dst.stem} ({n}){dst.suffix}")
                    dst = candidate
                    warnings.append(PlanWarning.SUFFIXED)
                    notes.append(f"{_NOTES[conflict]}; suffix ({n}) toegevoegd")
                else:
                    blocked = True
                    notes.append(f"{_NOTES[conflict]}; {_COLLISION_NOTES[collision]}")
                    new_staying.add(path_key(src))

        if tags_only:
            warnings.append(PlanWarning.TAGS_ONLY)
            notes.append(_NOTES[PlanWarning.TAGS_ONLY])
        if case_only:
            warnings.append(PlanWarning.CASE_ONLY)
            notes.append(_NOTES[PlanWarning.CASE_ONLY])
        if len(os.fspath(dst)) > MAX_PATH:
            warnings.append(PlanWarning.PATH_TOO_LONG)
            notes.append(f"{_NOTES[PlanWarning.PATH_TOO_LONG]} ({len(os.fspath(dst))})")
        if not blocked and not tags_only:
            claimed.add(path_key(dst))

        plans.append(
            RenamePlan(
                track_id=c.inp.track_id,
                src=src,
                dst=dst,
                case_only=case_only,
                warnings=tuple(warnings),
                collision=collision,
                tags=c.tags,
                blocked=blocked,
                changed=c.inp.changed,
                note="; ".join(notes),
            )
        )
    return plans, new_staying
