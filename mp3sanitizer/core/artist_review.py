"""Artiestencontrole in batch: elke track opzoeken op MusicBrainz en per artiest een voorstel doen.

Per track wordt de opname (artiest + titel) gezocht; de beste opname wordt gekozen op titel en
jaar. Elke artiest uit het artiestveld (ook in samenwerkingen) wordt gekoppeld aan een
artist-credit (MBID + officiële naam). Per artiest wint de MBID met de meeste tracks. Komen
verschillende MBID's met dezelfde naam voor, dan zijn het waarschijnlijk verschillende artiesten
met dezelfde naam ("Nirvana" uit 1968 en uit 1991): dan krijgt elke track een eigen voorstel.
"""

from __future__ import annotations

import string
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from mp3sanitizer.core.artists import artist_names, replace_artist
from mp3sanitizer.core.fuzzy import combined_score
from mp3sanitizer.core.musicbrainz import MusicBrainzError, RecordingCandidate
from mp3sanitizer.core.normalize import (
    DEFAULT_ARTICLES,
    fold,
    match_key,
    sort_key,
    strip_diacritics,
)

OTHER_LETTER = "#"  # cijfers en overige tekens
LETTERS = (*string.ascii_uppercase, OTHER_LETTER)
MIN_TITLE_SCORE = 80  # minimale gelijkenis van de titel met de opname
MIN_CREDIT_SCORE = 70  # minimale gelijkenis van de artiest met de artist-credit
MAJORITY = 0.6  # aandeel tracks dat het voorstel moet steunen; anders 'twijfel'
MAX_CONSECUTIVE_ERRORS = 5  # daarna stopt de controle (geen verbinding)


class RecordingSearch(Protocol):
    def search_recording(self, artist: str, title: str) -> list[RecordingCandidate]: ...


class Status(StrEnum):
    OK = "ok"  # al juist geschreven
    PROPOSAL = "proposal"  # andere schrijfwijze voorgesteld
    SPLIT = "split"  # meerdere artiesten met dezelfde naam: voorstel per track
    DOUBT = "doubt"  # tracks wijzen naar verschillende artiesten
    NOT_FOUND = "not_found"

    @property
    def label(self) -> str:
        return _STATUS_LABELS[self]


_STATUS_LABELS = {
    Status.OK: "Juist",
    Status.PROPOSAL: "Voorstel",
    Status.SPLIT: "Meerdere artiesten",
    Status.DOUBT: "Twijfel",
    Status.NOT_FOUND: "Niet gevonden",
}


@dataclass(frozen=True, slots=True)
class TrackRef:
    track_id: int
    artist: str  # volledig artiestveld, bijv. "Queen & David Bowie"
    title: str
    year: int | None


@dataclass(slots=True)
class ArtistEntry:
    name: str  # schrijfwijze zoals in de collectie
    tracks: list[TrackRef] = field(default_factory=list)

    @property
    def key(self) -> str:
        return fold(self.name)

    @property
    def years(self) -> tuple[int, int] | None:
        years = [t.year for t in self.tracks if t.year is not None]
        return (min(years), max(years)) if years else None


@dataclass(frozen=True, slots=True)
class Evidence:
    """Wat MusicBrainz over één artiest in één track zegt."""

    track_id: int
    mbid: str | None = None
    name: str | None = None  # officiële naam van de artist-credit
    recording: str = ""  # titel van de gevonden opname
    year: int | None = None  # jaar van de eerste release van die opname


@dataclass(slots=True)
class Candidate:
    """Een MusicBrainz-artiest waar één of meer tracks naar wijzen."""

    mbid: str
    name: str
    track_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class ArtistProposal:
    entry: ArtistEntry
    status: Status
    proposal: str  # voorgestelde schrijfwijze (bij 'meerdere artiesten': die van de meeste tracks)
    candidates: list[Candidate] = field(default_factory=list)
    evidence: dict[int, Evidence] = field(default_factory=dict)  # per track-id

    def track_proposal(self, track_id: int) -> str:
        """Voorstel voor één track: bij 'meerdere artiesten' de naam van die track zelf."""
        ev = self.evidence.get(track_id)
        if self.status is Status.SPLIT and ev is not None and ev.name:
            return ev.name
        return self.proposal


# --- verzamelen --------------------------------------------------------------------------


def letter_of(name: str, articles: Iterable[str] = DEFAULT_ARTICLES) -> str:
    """Beginletter volgens de sorteersleutel: 'The Beatles' valt onder B, '2Pac' onder #."""
    key = strip_diacritics(sort_key(name, articles)).lstrip("'\"([.")
    first = key[:1].upper()
    return first if first in string.ascii_uppercase else OTHER_LETTER


def collect(
    tracks: Iterable[TrackRef],
    articles: Iterable[str] = DEFAULT_ARTICLES,
    letters: Iterable[str] | None = None,
    skip: Iterable[str] = (),
) -> list[ArtistEntry]:
    """Per losse artiest (ook uit samenwerkingen) de tracks, gesorteerd zoals in de app.

    ``letters`` beperkt tot artiesten met die beginletters; ``skip`` bevat gevouwen namen van
    artiesten die al beoordeeld zijn.
    """
    articles = tuple(articles)
    wanted = {letter.upper() for letter in letters} if letters is not None else None
    skipped = set(skip)
    entries: dict[str, ArtistEntry] = {}
    for ref in tracks:
        for name in dict.fromkeys(artist_names(ref.artist, articles)):  # uniek, volgorde intact
            if wanted is not None and letter_of(name, articles) not in wanted:
                continue
            if fold(name) in skipped:
                continue
            entries.setdefault(name, ArtistEntry(name)).tracks.append(ref)
    return sorted(entries.values(), key=lambda e: (sort_key(e.name, articles), e.name))


def letter_counts(
    tracks: Iterable[TrackRef],
    articles: Iterable[str] = DEFAULT_ARTICLES,
    skip: Iterable[str] = (),
) -> dict[str, tuple[int, int]]:
    """Per beginletter: (aantal artiesten, aantal tracks) dat nog te controleren is."""
    articles = tuple(articles)
    artists: dict[str, set[str]] = defaultdict(set)
    track_ids: dict[str, set[int]] = defaultdict(set)
    for entry in collect(tracks, articles, skip=skip):
        letter = letter_of(entry.name, articles)
        artists[letter].add(entry.name)
        track_ids[letter].update(t.track_id for t in entry.tracks)
    return {letter: (len(artists[letter]), len(track_ids[letter])) for letter in LETTERS}


# --- per track opzoeken ------------------------------------------------------------------


def best_recording(
    title: str, year: int | None, candidates: Sequence[RecordingCandidate]
) -> RecordingCandidate | None:
    """De opname die het best bij titel (en jaar) past, of ``None``."""
    title_key = match_key(title, ())
    best: tuple[tuple[float, ...], RecordingCandidate] | None = None
    for c in candidates:
        score = combined_score(title_key, match_key(c.title, ()))
        if score < MIN_TITLE_SCORE:
            continue
        if year is not None and c.year is not None:
            # Eerste release ná het trackjaar is verdacht (andere artiest of latere cover).
            year_fit = -abs(c.year - year) - (20 if c.year > year + 1 else 0)
        else:
            year_fit = -10
        rank = (score >= 95, year_fit, score, c.score)
        if best is None or rank > best[0]:
            best = (rank, c)
    return best[1] if best else None


def match_credit(
    name: str, recording: RecordingCandidate, articles: Iterable[str] = DEFAULT_ARTICLES
) -> tuple[str, str] | None:
    """De artist-credit (mbid, naam) die bij ``name`` hoort, of ``None``."""
    key = match_key(name, articles)
    scored = [
        (combined_score(key, match_key(credit_name, articles)), mbid, credit_name)
        for mbid, credit_name in recording.credits
    ]
    if not scored:
        return None
    score, mbid, credit_name = max(scored)
    return (mbid, credit_name) if score >= MIN_CREDIT_SCORE else None


def evidence_for(
    ref: TrackRef,
    names: Sequence[str],
    recordings: Sequence[RecordingCandidate],
    articles: Iterable[str] = DEFAULT_ARTICLES,
) -> dict[str, Evidence]:
    """Per artiest uit het veld wat de beste opname zegt."""
    recording = best_recording(ref.title, ref.year, recordings)
    result = {}
    for name in names:
        credit = match_credit(name, recording, articles) if recording else None
        if credit is None or recording is None:
            result[name] = Evidence(ref.track_id)
        else:
            result[name] = Evidence(
                ref.track_id, credit[0], credit[1], recording.title, recording.year
            )
    return result


# --- samenvatten -------------------------------------------------------------------------


def summarize(entry: ArtistEntry, evidence: dict[int, Evidence]) -> ArtistProposal:
    found = [ev for ev in evidence.values() if ev.mbid and ev.name]
    if not found:
        return ArtistProposal(entry, Status.NOT_FOUND, entry.name, [], evidence)
    groups: dict[str, Candidate] = {}
    for ev in found:
        assert ev.mbid is not None and ev.name is not None
        groups.setdefault(ev.mbid, Candidate(ev.mbid, ev.name)).track_ids.append(ev.track_id)
    candidates = sorted(groups.values(), key=lambda c: (-len(c.track_ids), c.name))
    top = candidates[0]
    same_name = len(candidates) > 1 and len({fold(c.name) for c in candidates}) == 1
    if same_name:
        status = Status.SPLIT
    elif len(top.track_ids) / len(found) < MAJORITY:
        status = Status.DOUBT
    elif top.name == entry.name:
        status = Status.OK
    else:
        status = Status.PROPOSAL
    return ArtistProposal(entry, status, top.name, candidates, evidence)


# --- de hele controle --------------------------------------------------------------------


def run_review(
    client: RecordingSearch,
    entries: Sequence[ArtistEntry],
    articles: Iterable[str] = DEFAULT_ARTICLES,
    *,
    on_result: Callable[[ArtistProposal], None],
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> str | None:
    """Controleer ``entries`` in volgorde; meld elk voorstel zodra de artiest klaar is.

    Elke track wordt hooguit één keer opgezocht, ook als hij bij meerdere artiesten hoort.
    Geeft een foutmelding terug als MusicBrainz herhaaldelijk onbereikbaar is, anders ``None``.
    """
    articles = tuple(articles)
    total = len({t.track_id for e in entries for t in e.tracks})
    looked_up: dict[int, dict[str, Evidence]] = {}
    errors = 0
    for entry in entries:
        evidence: dict[int, Evidence] = {}
        for ref in entry.tracks:
            if cancelled is not None and cancelled():
                return None
            if ref.track_id not in looked_up:
                names = artist_names(ref.artist, articles)
                try:
                    recordings = client.search_recording(ref.artist, ref.title)
                    errors = 0
                except MusicBrainzError as exc:
                    errors += 1
                    if errors >= MAX_CONSECUTIVE_ERRORS:
                        return str(exc)
                    recordings = []
                looked_up[ref.track_id] = evidence_for(ref, names, recordings, articles)
                if progress is not None:
                    progress(len(looked_up), total)
            evidence[ref.track_id] = looked_up[ref.track_id].get(entry.name, Evidence(ref.track_id))
        on_result(summarize(entry, evidence))
    return None


def recheck(
    client: RecordingSearch,
    entry: ArtistEntry,
    corrected: str,
    articles: Iterable[str] = DEFAULT_ARTICLES,
) -> ArtistProposal | str:
    """Zoek de tracks van ``entry`` opnieuw op, met ``corrected`` in plaats van de huidige naam.

    Voor een verkeerd geschreven naam ("Quien") vindt MusicBrainz vaak niets; met de door de
    gebruiker verbeterde naam ("Queen") wel. In samenwerkingen wordt alleen deze artiest
    vervangen. Het voorstel blijft bij de oorspronkelijke artiest horen, zodat toepassen
    "Quien" vervangt. Geeft een foutmelding terug als MusicBrainz onbereikbaar is.
    """
    articles = tuple(articles)
    corrected = " ".join(corrected.split())
    tracks = [
        TrackRef(
            t.track_id,
            replace_artist(t.artist, entry.name, corrected, articles) or corrected,
            t.title,
            t.year,
        )
        for t in entry.tracks
    ]
    results: list[ArtistProposal] = []
    error = run_review(client, [ArtistEntry(corrected, tracks)], articles, on_result=results.append)
    if error or not results:
        return error or "Geen resultaat"
    p = results[0]
    p.entry = entry
    if p.status is Status.NOT_FOUND:
        p.proposal = corrected  # niets gevonden: de eigen correctie is het voorstel
    elif p.status is Status.OK and p.proposal != entry.name:
        p.status = Status.PROPOSAL
    return p
