# Changelog

Alle noemenswaardige wijzigingen in dit project worden in dit bestand bijgehouden.

Het formaat is gebaseerd op [Keep a Changelog](https://keepachangelog.com/nl/1.1.0/)
en dit project volgt [Semantic Versioning](https://semver.org/lang/nl/).

## [Unreleased]

### Fixed
- Artiestnamen met "and"/"en"/"&" erin (bijv. "adam and the ants") werden bij het toepassen
  van een voorstel verdubbeld tot "Adam and the Ants and the ants". Dekt de nieuwe naam het
  hele artiestveld, dan wordt nu het hele veld vervangen; echte samenwerkingen
  ("Quien & David Bowie" → "Queen & David Bowie") blijven per artiest werken.

## [0.14.0] - 2026-10-05

### Fixed
- Tests en releases bleven soms eindeloos hangen: de Windows-mediabackend blokkeerde in een
  afspeeltest. De tests gebruiken nu een nepspeler (de echte wordt gecontroleerd door de
  smoke-test van de exe), en het releasescript stopt bij een time-out de hele procesboom.

### Added
- Artiestencontrole: **Naam corrigeren en opnieuw zoeken…** (F2, knop of rechtsklik). Typ de
  juiste schrijfwijze van een verkeerd geschreven artiest ("Quien" → "Queen"); de tracks worden
  daarmee opnieuw opgezocht zonder het venster te sluiten, en het voorstel staat meteen
  aangevinkt. In samenwerkingen wordt alleen die artiest vervangen
  ("Quien & David Bowie" → "Queen & David Bowie").

## [0.13.1] - 2026-10-05

### Fixed
- Release op de CI: de release-notes worden in UTF-8 geschreven. Tekens als "→" in de
  changelog lieten de build eerder stil mislukken (0.11.0 en 0.13.0 verschenen daardoor niet
  als GitHub-release); deze versie bevat alles uit 0.13.0.

## [0.13.0] - 2026-10-05

### Added
- **Bewerken → Artiesten controleren (MusicBrainz)**: alle artiesten per beginletter nagaan.
  Elke track wordt opgezocht op artiest + titel; per artiest volgt een voorstel (officiële naam
  van de meeste tracks). Artiesten met dezelfde naam worden op jaar onderscheiden (voorstel per
  track), samenwerkingen per artiest. Voorstellen aanpassen, toepassen (één undo-stap) of
  negeren; beoordeelde artiesten worden onthouden en volgende keer overgeslagen.

## [0.12.1] - 2026-09-30

### Fixed
- Artiesten zoeken: een korte naam die toevallig in de zoekterm voorkomt (bijv. "A" in
  "Cadets") telt niet meer als treffer met score 100. Deelovereenkomst werkt alleen nog in de
  bedoelde richting ("beat" vindt "The Beatles").

## [0.12.0] - 2026-09-30

### Changed
- Artiest opzoeken (zoeken en corrigeren, MusicBrainz) gebruikt alleen de geselecteerde tekst
  als je in een cel tekst selecteert; enkele letters alleen als die echt geselecteerd zijn.
  Zonder selectie blijft het hele veld (of bij een samenwerking de eerste artiest) de zoekterm.
  Rechtsklik in de cel-editor biedt beide opzoekacties met de selectie.

## [0.11.1] - 2026-09-30

### Fixed
- Release-build op de CI: ook onverwachte fouten verschijnen als annotatie en de build krijgt
  één herkansing. 0.11.0 is daardoor niet als GitHub-release verschenen; deze versie bevat
  alles uit 0.11.0.

## [0.11.0] - 2026-09-30

### Added
- Rechtsklik → **Opzoeken op MusicBrainz (artiest + titel)**: zoekt de track op en neemt de
  officiële titel, artiest en/of het jaar over (één undo-stap). Alleen de artiest opzoeken
  blijft beschikbaar.
- Opslaan-preview: niet-opslaanbare tracks herstellen met **Aanpassen…**, **Ongeldige tekens
  vervangen** en **Verwijderen (duplicaat)…**; de preview rekent daarna direct opnieuw.

## [0.10.7] - 2026-09-28

### Fixed
- Release-build op de CI: fouten van smoke-test en handleiding verschijnen als annotatie en de
  screenshots krijgen één herkansing. 0.10.6 is daardoor niet als GitHub-release verschenen;
  deze versie bevat alles uit 0.10.6.

## [0.10.6] - 2026-09-28

### Added
- Artiestenvoorstellen tonen onder elke schrijfwijze de tracks: per track uit te vinken,
  Enter speelt af, tooltip met het pad, rechtsklik → Toon in hoofdvenster.

## [0.10.5] - 2026-09-27

### Fixed
- De handleiding wordt op de CI offscreen gebouwd (daar is geen betrouwbare desktopsessie),
  zodat de PDF weer bij de GitHub-release komt. Deze versie bevat ook alles uit 0.10.4, dat
  daardoor niet als GitHub-release is verschenen.

## [0.10.4] - 2026-09-27

### Added
- Artiestenoverzicht: knop "Opzoeken op MusicBrainz" naast het clustervoorstel om de
  officiële schrijfwijze in te vullen.

## [0.10.3] - 2026-09-27

### Fixed
- Artiesten corrigeren houdt rekening met samenwerkingen ("Queen & David Bowie",
  "Eminem ft. Dido", "A, B & C", x, vs., with, met, and, en): alleen de gekozen artiest wordt
  vervangen, de andere artiesten blijven staan. Zoeken en clustervoorstellen vinden ook de losse
  artiesten in samenwerkingen; een groep met het complete samenwerkingsveld staat standaard uit.
  Opzoeken op MusicBrainz via het contextmenu vervangt in samenwerkingen alleen de gezochte
  artiest.
- De Windows-build bevatte onnodig Pillow (±13 MB) uit de ontwikkelomgeving; die wordt nu
  uitgesloten.

## [0.10.2] - 2026-09-26

### Added
- Handleiding (PDF, Nederlands) met screenshots van de echte app en onderschriften; wordt bij
  elke release gebouwd (`scripts/release.py manual`) en als download bij de GitHub-release gezet.

### Fixed
- Een cel-editor annuleren met Esc gaf een foutmelding in de achtergrond (de eigen
  terugdraaifunctie van het tabelmodel botste met Qt's `revert()`).

## [0.10.1] - 2026-09-26

### Fixed
- Een volgnummer na het jaar (`Titel (1985)(2)` of `Titel (1985) (2)`) wordt genegeerd bij het
  parsen: het jaar wordt herkend en het nummer komt niet meer in de titel. De Status-tooltip
  meldt het volgnummer; bij opslaan verdwijnt het uit de naam. Namen die de app zelf met een
  suffix " (2)" opsloeg, worden nu ook correct teruggelezen.

## [0.10.0] - 2026-09-25

### Added
- Over-dialoog (Help) met versie, commit-hash, builddatum en de versies van Python, PySide6 en
  mutagen, plus "Kopieer info" voor bugmeldingen.
- Optionele updatecheck via de GitHub releases-API (standaard uit): alleen een melding, nooit
  automatisch downloaden of installeren.
- `mp3sanitizer --version` en `--smoke-test` (controle van een build, inclusief multimedia).
- Schema-migraties per bestandssoort (`core/migrations.py`) met fixture-tests; journaal
  schema 2 legt de appversie per journaalregel vast. "Laatste batch terugdraaien" werkt ook
  voor journalen van oudere versies.
- PyInstaller-spec (`mp3sanitizer.spec`, één map) met buildinfo.
- Releasescript `scripts/release.py` (controles, changelog, tag, build, zip).
- CI: bij een `v*`-tag automatisch bouwen en de zip als release-asset publiceren.

## [0.9.0] - 2026-09-25

### Added
- Sessie opslaan/openen als projectbestand (`*.mp3s.json`, met `schema_version`); bij het
  openen wordt de map opnieuw ingelezen en worden de wijzigingen als één undo-stap teruggezet.
- Keuze "Opslaan" (als sessie) in de waarschuwing bij afsluiten/herladen met open wijzigingen.
- Export van het (gefilterde) overzicht naar CSV voor Nederlandse Excel (UTF-8 met BOM, `;`).
- Contextmenu "Openen in Verkenner" (`explorer /select,`), Ctrl+E.

## [0.8.0] - 2026-09-25

### Added
- Batch-correcties (Ctrl+K) via het gedeelde preview-dialoog, toegepast als één undo-stap;
  scope: hele collectie, huidige filter of selectie; opschoonprofielen (combinaties van regels).
- 9a Afkortingen naar hoofdletters (letters met punten, vaste lijst, uitzonderingen).
- 9b Featuring normaliseren (`ft.`/`feat.`), ook in haakjes; optioneel naar artiest of titel.
- 9c Eigen vervangingsregels met regeleditor (volgorde, testveld, regex-validatie,
  import/export) en uitschakelbare standaardregels.
- 9d Romeinse cijfers naar hoofdletters met bescherming tegen valse positieven.
- 9e Title Case, spaties opschonen, jaar uit tag, "Artiest, The" ↔ "The Artiest".
- Regelinstellingen en profielen in `rules.json` met `schema_version`.

### Changed
- pre-commit gebruikt dezelfde ruff-versie als `uv.lock`.

## [0.7.0] - 2026-09-25

### Added
- Duplicaatdetectie op genormaliseerde artiest + titel: strikt of fuzzy (drempel), jaar
  negeren, versie-aanduidingen negeren, optioneel duur ±2 s.
- Duplicatenvenster (Ctrl+D) gegroepeerd per duplicaatgroep met bitrate, duur, grootte, jaar
  en map; "Beste automatisch behouden" (hoogste bitrate, langste duur, kortste pad) met
  per groep aanpasbare selectie; afspelen vanuit het venster.
- Verwijderen van de aangevinkte duplicaten via de gewone bevestiging (Prullenbak).
- Snelfilter "Duplicaten" (Ctrl+8).

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
