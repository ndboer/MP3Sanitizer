# Changelog

Alle noemenswaardige wijzigingen in dit project worden in dit bestand bijgehouden.

Het formaat is gebaseerd op [Keep a Changelog](https://keepachangelog.com/nl/1.1.0/)
en dit project volgt [Semantic Versioning](https://semver.org/lang/nl/).

## [Unreleased]

## [0.6.0] - 2026-09-25

### Added
- Fuzzy zoeken op artiest (rapidfuzz) op een genormaliseerde sleutel: hoofdletters, diacrieten,
  lidwoorden (ook "Naam, The"), "&/and/en/+" en leestekens genegeerd; instelbare drempel.
- Resultaten gegroepeerd per schrijfwijze met aantallen; aangevinkte groepen/tracks in één
  undo-stap corrigeren.
- MusicBrainz WS/2 artist search: 1 verzoek per seconde, User-Agent met de appversie,
  herhaalpogingen bij 503, JSON-cache (30 dagen) met `schema_version`; kandidaten met naam,
  sort-name, land, toelichting en score ≥ 80; de officiële naam wordt ingevuld.
- Artiestenoverzicht met aantallen en automatische clustervoorstellen.
- Contextmenu "Opzoeken op MusicBrainz".
- Zoeken, clusteren en MusicBrainz draaien op de achtergrond.

## [0.5.0] - 2026-09-25

### Added
- Verwijderen (Del / contextmenu): standaard naar de Prullenbak via send2trash, altijd na een
  bevestiging met het aantal en de lijst van bestanden.
- Permanent verwijderen alleen via een expliciete optie met extra bevestiging.
- Verwijderen draait op de achtergrond; fouten per bestand stoppen de rest niet en worden
  gemeld. Elke verwijdering wordt in het journaal vastgelegd.
- Afspelen stopt als de spelende track wordt verwijderd; verwijderde tracks verdwijnen uit de
  tabel en tellers.

## [0.4.0] - 2026-09-25

### Added
- Afspelen met QtMultimedia (`QMediaPlayer` + `QAudioOutput`): Play/Stop-kolom per rij,
  spatiebalk speelt de huidige rij af; een nieuwe track stopt de vorige.
- Mini-player onderin met play/pauze, stop, seekbalk, tijd en volume; menu Afspelen met
  stoppen (Ctrl+.) en 5 s terug/vooruit (Alt+←/→).
- Optie "Automatisch volgende geselecteerde".
- Volume en de autoplay-optie worden in de instellingen bewaard.

### Changed
- Afspelen stopt (en laat het bestand los) vóór opslaan, terugdraaien en herladen.

## [0.3.0] - 2026-09-25

### Added
- Opslaan via een preview (Ctrl+S): oud → nieuw pad met gemarkeerde verschillen (difflib,
  per woord), checkbox per regel, alles/niets selecteren, filter en "alleen regels met
  opmerkingen".
- Hernoemen naar `<Artiest> - <Titel> (<Jaar>).<ext>` en optioneel verplaatsen naar een jaar-
  of decenniummap; instelbare map voor tracks zonder jaar.
- Botsingen worden nooit overschreven: overslaan, suffix " (2)" of als duplicaat markeren.
- Case-only renames en naamruil/ketens (A→B, B→A) via tijdelijke namen in twee stappen.
- Waarschuwingen voor paden > 260 tekens en ongeldige namen (niet uitvoerbaar).
- Optioneel tags bijwerken (mutagen) en lege mappen opruimen.
- Uitvoeren op de achtergrond met voortgang en annuleren; fouten per bestand in het resultaat.
- Journaal per batch (JSON met appversie + leesbaar logbestand) en "Laatste batch
  terugdraaien", inclusief het herstellen van tags en het opruimen van aangemaakte mappen.
- Snelfilter "Verkeerde jaarmap" (Ctrl+7) en duplicaatmarkering in de Status-kolom.

## [0.2.0] - 2026-09-25

### Added
- Inline bewerken van Artiest, Titel en Jaar (F2 of dubbelklik).
- Bulk bewerken: één veld voor alle geselecteerde tracks invullen (Ctrl+B).
- Wissel artiest ⇄ titel (Ctrl+W) en terugdraaien per rij (Ctrl+R), ook via het contextmenu.
- Undo/redo (Ctrl+Z / Ctrl+Y) voor alle bewerkingen; een bulk-actie is één undo-stap.
- Validatie: jaar numeriek en binnen bereik; ongeldige Windows-tekens en lege velden worden
  gemarkeerd; gereserveerde namen (CON, NUL, ...) worden op de volledige bestandsnaam gecontroleerd.
- Gewijzigde cellen zijn gemarkeerd tot ze zijn opgeslagen; tooltip met de originele waarde en
  de nieuwe bestandsnaam.
- Snelfilters "Gewijzigd (niet opgeslagen)" en "Ongeldige namen"; teller "Gewijzigd" in de
  statusbalk.
- Bevestiging bij openen van een andere map, herladen of afsluiten met openstaande wijzigingen.

### Changed
- Titels, bestandsnamen en artiesten sorteren natuurlijk ("Song 9" vóór "Song 10").
- Filters en zoeken gebruiken de bewerkte waarden.

## [0.1.0] - 2026-09-25

### Added
- Recursief scannen van een hoofdmap met `os.scandir`; instelbare extensies
  (standaard .mp3, .flac, .m4a, .wav, .ogg).
- Parser voor `<Artiest> - <Titel> (<Jaar>)`: splitst op de eerste ` - `, tolerant voor dubbele
  spaties, en-/em-dash en een ontbrekend jaar; jaar tussen 1900 en volgend jaar.
- Tabel (QTableView + eigen model) met kolommen Status, Artiest, Titel, Jaar, Folder en
  Bestandsnaam, plus optionele kolommen Duur, Bitrate, Grootte, Tag-artiest, Tag-titel en Tag-jaar.
- Duur, bitrate en tags worden lazy op de achtergrond ingelezen (mutagen), met voortgangsbalk
  en annuleerknop; een mismatch-indicator toont afwijkende tags.
- Sorteren via de kolomkop; sorteren op artiest negeert lidwoorden ("The Beatles" bij de B).
- Snelfilters Alles / Alleen parse-fouten / Zonder jaar / Tag-mismatch en een zoekveld.
- Statusbalk met totaal, geselecteerd, gewijzigd en parse-fouten.
- Instellingen als JSON met `schema_version`, met afhandeling van corrupte bestanden en
  bestanden van een nieuwere versie.
- Roterend logbestand met de appversie op de eerste regel; versie in de titelbalk.
- MIT-licentie en GitHub Actions-workflow (ruff + pytest op Windows).

## [0.0.1] - 2026-09-25

### Added
- Initiële projectopzet: `pyproject.toml` (hatchling + hatch-vcs), `.gitignore`,
  `.gitattributes`, pre-commit-configuratie en deze changelog.
