# Changelog

Alle noemenswaardige wijzigingen in dit project worden in dit bestand bijgehouden.

Het formaat is gebaseerd op [Keep a Changelog](https://keepachangelog.com/nl/1.1.0/)
en dit project volgt [Semantic Versioning](https://semver.org/lang/nl/).

## [Unreleased]

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
