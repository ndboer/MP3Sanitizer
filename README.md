# Mp3Sanitizer

Desktop-applicatie (Python + PySide6) om een muziekcollectie van duizenden audiobestanden te
inventariseren, op te schonen en te hernoemen op basis van de bestandsnaam
`<Artiest> - <Titel> (<Jaar>)`.

Zie [CHANGELOG.md](CHANGELOG.md) voor wat er per versie is veranderd.

## Installatie

**Kant-en-klaar (Windows):** download `mp3sanitizer-X.Y.Z-win64.zip` bij de
[releases](https://github.com/ndboer/MP3Sanitizer/releases), pak uit en start
`Mp3Sanitizer\Mp3Sanitizer.exe`.

**Vanaf de broncode:** vereist [uv](https://docs.astral.sh/uv/) en Git; uv installeert zelf een
passende Python (3.12+).

```bash
git clone https://github.com/ndboer/MP3Sanitizer.git
cd MP3Sanitizer
uv sync
uv run mp3sanitizer
```

`uv run mp3sanitizer --version` toont versie, commit en bibliotheekversies zonder de GUI te
starten.

De versie komt uit de Git-tag (hatch-vcs). Na het wisselen van tag of branch:
`uv sync --reinstall-package mp3sanitizer`, zodat de getoonde versie klopt.

## Gebruik

| Actie                                   | Toets              |
|-----------------------------------------|--------------------|
| Map openen                              | Ctrl+O             |
| Herlaad (externe wijzigingen)           | F5                 |
| Zoeken in artiest/titel/bestand         | Ctrl+F (Esc wist)  |
| Snelfilters (zie hieronder)             | Ctrl+1 … Ctrl+6    |
| Cel bewerken (artiest, titel, jaar)     | F2 of dubbelklik   |
| Bulk bewerken (geselecteerde rijen)     | Ctrl+B             |
| Wissel artiest ⇄ titel                  | Ctrl+W             |
| Wijzigingen van selectie terugdraaien   | Ctrl+R             |
| Ongedaan maken / opnieuw                | Ctrl+Z / Ctrl+Y    |
| Opslaan (altijd via preview)            | Ctrl+S             |
| Afspelen / stoppen (huidige rij)        | Spatie             |
| Stoppen                                 | Ctrl+.             |
| 5 seconden terug / vooruit              | Alt+← / Alt+→      |
| Geselecteerde bestanden verwijderen     | Del                |
| Artiesten zoeken en corrigeren (fuzzy)  | Ctrl+Shift+F       |
| Artiestenoverzicht en voorstellen       | Ctrl+Shift+A       |
| Duplicaten zoeken                       | Ctrl+D             |
| Batch-correcties (opschoonregels)       | Ctrl+K             |
| Openen in Verkenner                     | Ctrl+E             |
| Sessie opslaan / openen                 | Ctrl+Shift+S / O   |
| Lopende taak annuleren                  | Esc                |

Snelfilters: 1 Alles, 2 Gewijzigd (niet opgeslagen), 3 Alleen parse-fouten, 4 Zonder jaar,
5 Tag-mismatch, 6 Ongeldige namen, 7 Verkeerde jaarmap, 8 Duplicaten.

- De bestandsnaam wordt gesplitst op de **eerste** ` - ` (ook en-/em-dash). Een jaar `(dddd)` aan
  het eind telt alleen als het tussen 1900 en volgend jaar ligt.
- Een volgnummer direct na het jaar, zoals `Titel (1985)(2)` of `Titel (1985) (2)`, wordt
  genegeerd: zo'n nummer wordt toegevoegd als er al een bestand met dezelfde naam bestond. De
  Status-tooltip meldt het; bij opslaan verdwijnt het uit de naam (bestaat het origineel nog,
  dan volgt de gewone botsingsafhandeling, en de duplicatenzoeker vindt beide).
- Bestanden die niet volgens het patroon parsen krijgen de status **Parse-fout** en blijven
  zichtbaar.
- Duur, bitrate, grootte en tags worden na het scannen op de achtergrond ingelezen. Wijken de tags
  af van de bestandsnaam, dan toont de Status-kolom `tags ≠` (tooltip toont de verschillen).
- Extra kolommen zet je aan via **Beeld → Kolommen** of rechtsklik op de kolomkop.
- Sorteren op artiest negeert lidwoorden: "The Beatles" en "Beatles, The" staan bij de B.
  Getallen sorteren natuurlijk ("Song 9" vóór "Song 10").

### Bewerken

- Artiest, Titel en Jaar zijn te bewerken (F2 of dubbelklik; F2 op een andere kolom bewerkt de
  artiest). Rechtsklik op een rij opent hetzelfde menu als **Bewerken**.
- Wijzigingen blijven in het geheugen tot je ze opslaat en zijn geel gemarkeerd.
  De tooltip toont de originele waarde; de Status-tooltip de nieuwe bestandsnaam.
- Ongeldige namen worden rood gemarkeerd: tekens die Windows niet toestaat (`< > : " / \ | ? *`),
  of een lege artiest/titel. Een jaar moet tussen 1900 en volgend jaar liggen; ongeldige invoer
  wordt geweigerd.
- Na een bewerking wordt niet automatisch opnieuw gesorteerd; klik op de kolomkop om te
  hersorteren.
- Bij openen van een andere map, herladen of afsluiten met openstaande wijzigingen vraagt de app
  eerst om bevestiging.

### Artiesten corrigeren (fuzzy zoeken en MusicBrainz)

- **Bewerken → Artiesten zoeken en corrigeren…** (Ctrl+Shift+F) zoekt fuzzy op artiest:
  hoofdletters, accenten (Beyoncé = Beyonce), lidwoorden (ook "Beatles, The"), "&/and/en/+" en
  leestekens tellen niet mee. De drempel (standaard 85) is instelbaar met de schuifregelaar.
- Resultaten zijn gegroepeerd per schrijfwijze met het aantal tracks ("The Beatles (40)",
  "Beatles, The (3)"). Vink groepen of losse tracks aan, vul de juiste schrijfwijze in en kies
  **Toepassen** (één undo-stap).
- **Opzoeken op MusicBrainz** toont kandidaten (naam, sort-name, land, toelichting, score ≥ 80);
  de gekozen kandidaat vult de officiële naam in. Maximaal één verzoek per seconde; resultaten
  worden 30 dagen gecachet in `%LOCALAPPDATA%\Mp3Sanitizer\musicbrainz_cache.json`. Ook
  beschikbaar via rechtsklik op een rij (toepassen op de geselecteerde rijen).
- **Artiestenoverzicht en voorstellen** (Ctrl+Shift+A) toont alle artiesten met aantallen en
  stelt clusters voor van waarschijnlijk dezelfde artiest, met de meestgebruikte schrijfwijze
  als voorstel.

De score is het gemiddelde van rapidfuzz `token_set_ratio` en `ratio` op de genormaliseerde naam
(zo is "Beatles Tribute Band" niet hetzelfde als "Beatles", maar "Beatels" wel); bij zoeken telt
ook een deelmatch mee ("beat" vindt "The Beatles").

### Batch-correcties (opschoonregels)

**Bewerken → Batch-correcties…** (Ctrl+K): vink regels aan (een combinatie is op te slaan als
*opschoonprofiel*), kies de scope (hele collectie, huidige filter of geselecteerde rijen) en
bekijk de **preview**: per veld oud → nieuw met de verschillen gemarkeerd; alleen aangevinkte
regels worden toegepast, als één undo-stap. Opslaan naar schijf gaat daarna via Ctrl+S.

| Regel | Wat |
|---|---|
| Spaties opschonen | trim, dubbele spaties, spaties rond ` - ` en haakjes |
| Title Case | hoofdletters per woord; kleine woorden (of, the, a, in, van, de, het, …) klein behalve aan het begin; afkortingen, Romeinse cijfers en woorden als McCartney blijven intact |
| Eigen vervangingsregels | zoek → vervang per veld, heel woord, hoofdlettergevoelig, regex; standaardregels: `vs/Vs./versus → vs.`, `&amp; → &`, dubbele spaties, spatie vóór `)`, `´` en `` ` `` → `'` |
| Lidwoord | "Beatles, The" ↔ "The Beatles" consequent (keuze instelbaar) |
| Featuring | `feat`, `feat.`, `featuring`, `ft`, `ft.`, `f.` → `ft.` (of `feat.`), ook in haakjes; optioneel verplaatsen naar artiest of titel |
| Afkortingen | `U.s.a` → `U.S.A.`, `u.k.` → `U.K.` (nooit dubbele punt) + vaste lijst (DJ, MC, UB40, ABBA, AC/DC, …) + uitzonderingen |
| Romeinse cijfers | alleen geldige Romeinse getallen; standaard t/m XXXIX, na Part/Pt./Vol./Volume/Chapter/Deel/Act of aan het eind van de titel; uitzonderingen (Mix, Mi, Di, …) |
| Jaar uit tag | vult het jaar in uit de tag als de bestandsnaam geen jaar heeft |

De regels worden altijd in deze volgorde toegepast. Instellingen per regel via **Instellingen…**
(of dubbelklik). **Bewerken → Vervangingsregels…** opent de regeleditor: volgorde slepen of met
Omhoog/Omlaag, een testveld dat de regel live uitprobeert, ongeldige regex wordt direct gemeld,
en regelsets zijn te importeren/exporteren als JSON. Alle regelinstellingen en profielen staan in
`%APPDATA%\Mp3Sanitizer\rules.json`.

### Duplicaten

**Bewerken → Duplicaten zoeken…** (Ctrl+D) vergelijkt genormaliseerde artiest + titel.

- Strikt (exact na normalisatie) of fuzzy met een drempel; jaar negeren; versie-aanduidingen
  negeren ((Remix), (Live), (Radio Edit), (Extended Mix), (Remastered), ook tussen `[ ]` of na
  " - "); optioneel duur ±2 s als extra criterium.
- Per groep zie je bitrate, duur, grootte, jaar en map. **Beste automatisch behouden**: hoogste
  bitrate, dan langste duur, dan kortste pad; de rest is aangevinkt voor verwijderen en per
  groep aan te passen (spatie). Enter speelt de track af.
- **Aangevinkte verwijderen** loopt via de gewone bevestiging (Prullenbak).
- Snelfilter 8 "Duplicaten" in de hoofdtabel gebruikt dezelfde (laatst gekozen) opties.

### Afspelen

- De eerste kolom heeft per rij een Play/Stop-knop; de spatiebalk speelt de huidige rij af (of
  stopt als die al speelt). Een nieuwe track stopt de vorige.
- Onderin staat de mini-player met play/pauze, stop, seekbalk, tijd en volume.
- "Automatisch volgende geselecteerde" speelt na afloop de volgende geselecteerde rij.
- Voor opslaan, terugdraaien en herladen stopt het afspelen automatisch: Windows kan een geopend
  bestand niet hernoemen.

### Verwijderen

- **Del** (of rechtsklik → Verwijderen) verplaatst de geselecteerde bestanden naar de
  **Prullenbak**, altijd na een bevestiging met het aantal en de lijst van bestanden.
- Permanent verwijderen kan alleen via het vinkje in dat venster, met een extra bevestiging;
  Enter kiest dan Annuleren.
- Verwijderingen staan in het journaal, maar zijn niet via "Laatste batch terugdraaien" te
  herstellen: haal bestanden terug uit de Prullenbak van Windows.

### Sessies, export en overig

- **Bestand → Sessie opslaan…** bewaart de niet-opgeslagen wijzigingen als projectbestand
  (`*.mp3s.json`); **Sessie openen…** leest de bijbehorende map opnieuw in en zet de wijzigingen
  terug (één undo-stap). Bestanden die intussen verdwenen zijn, worden gemeld.
- Bij afsluiten, herladen of een andere map openen met openstaande wijzigingen kun je kiezen:
  **Opslaan** (als sessie), **Verwerpen** of **Annuleren**.
- **Bestand → Exporteren naar CSV…** exporteert het (gefilterde) overzicht met de zichtbare
  kolommen, als UTF-8 met BOM en puntkomma's, zodat Nederlandse Excel het direct goed opent.
- Rechtsklik → **Openen in Verkenner** (Ctrl+E) toont het bestand geselecteerd in Verkenner.

### Opslaan

**Bestand → Opslaan…** (Ctrl+S) opent altijd eerst een preview met per bestand oud → nieuw pad,
de gewijzigde delen gemarkeerd, en een checkbox (spatie schakelt de geselecteerde regels).

- Doelnaam: `<Artiest> - <Titel> (<Jaar>).<ext>`, zonder jaar `<Artiest> - <Titel>.<ext>`.
- Doelmap: niet verplaatsen, jaarmap (`1985\`) of decenniummap (`1980-1989\` of `80s\`; vanaf
  2000 `2000s\`). Tracks zonder jaar gaan naar een instelbare map (standaard `_Onbekend\`).
- "Ook niet-bewerkte tracks meenemen" normaliseert ook namen die je niet hebt bewerkt en zet
  tracks in de juiste jaarmap.
- Bestaande bestanden worden **nooit** overschreven. Bij een botsing kies je: overslaan, suffix
  `" (2)"` of als duplicaat markeren. Naamwijzigingen die alleen hoofdletters betreffen, lopen via
  een tijdelijke naam (Windows ziet `a.mp3` en `A.mp3` als hetzelfde bestand).
- Waarschuwingen voor paden langer dan 260 tekens; ongeldige namen zijn niet aan te vinken.
- Optioneel: tags (artiest, titel, jaar) bijwerken en lege mappen opruimen.
- Een fout bij één bestand stopt de batch niet; na afloop volgt een overzicht.
- Na opslaan wordt de undo-geschiedenis (Ctrl+Z) gewist: de opgeslagen namen zijn het nieuwe
  uitgangspunt. Terugdraaien op schijf gaat via **Bestand → Laatste batch terugdraaien…**.

Elke batch krijgt een journaal in `%LOCALAPPDATA%\Mp3Sanitizer\journal\`: `<batch>.json`
(met appversie, gebruikt voor terugdraaien) en `<batch>.log` (leesbaar, wordt tijdens het
uitvoeren bijgeschreven).

### Help en updates

- **Help → Over Mp3Sanitizer…** toont versie, commit, builddatum en de versies van Python,
  PySide6 en mutagen; **Kopieer info** zet dit op het klembord voor een bugmelding.
- **Help → Controleren op updates…** vraagt de laatste release op en meldt alleen of er een
  nieuwere is. Automatisch controleren bij opstarten staat standaard **uit** (Help-menu). Er wordt
  nooit iets gedownload of geïnstalleerd.
- **Help → Map met logbestanden openen**: de eerste regel van elk logbestand bevat de appversie.

### Bestanden van de app

| Bestand | Locatie |
|---|---|
| Instellingen | `%APPDATA%\Mp3Sanitizer\settings.json` |
| Regels en opschoonprofielen | `%APPDATA%\Mp3Sanitizer\rules.json` |
| Journaal per batch | `%LOCALAPPDATA%\Mp3Sanitizer\journal\` |
| MusicBrainz-cache | `%LOCALAPPDATA%\Mp3Sanitizer\musicbrainz_cache.json` |
| Logbestanden (roterend) | `%LOCALAPPDATA%\Mp3Sanitizer\logs\` |
| Sessies | waar je ze opslaat (`*.mp3s.json`) |

Elk JSON-bestand bevat `schema_version`. Is het ouder, dan wordt het stap voor stap gemigreerd
(na een back-up `<naam>.v<oud>.bak`); is het nieuwer dan deze versie kent, dan wordt het niet
overschreven en meldt de app dat; is het corrupt, dan gebruikt de app standaardwaarden, bewaart
het bestand als `<naam>.corrupt` en meldt dat.

## Ontwikkeling

```bash
uv sync
uv run pre-commit install
uv run pytest
uv run ruff check .
uv run ruff format .
```

- `mp3sanitizer/core/`: pure Python zonder Qt (parser, normalisatie, regels, duplicaten,
  planner, executor, journaal, migraties, MusicBrainz, instellingen).
- `mp3sanitizer/ui/`: PySide6-interface (model/view, dialogen, achtergrond-workers).
- Werkwijze: `feat/<naam>` en `fix/<naam>`-branches, Conventional Commits, mergen in `main` als
  alle tests slagen. Nieuwe changelogregels komen onder `## [Unreleased]`.
- Een nieuwe schemaversie van een JSON-bestand: zie `mp3sanitizer/core/migrations.py`
  (migratie + fixture in `tests/fixtures/` + test).

### Bouwen

```bash
uv run pyinstaller mp3sanitizer.spec --noconfirm
```

Dit maakt `dist\Mp3Sanitizer\` (één map, zonder console). De spec schrijft vooraf
`mp3sanitizer/_build_info.py` met commit-hash en builddatum. Controle van een build:
`dist\Mp3Sanitizer\Mp3Sanitizer.exe --smoke-test uitvoer.txt` (start Qt zonder venster, controleert
ook de multimedia-plugin en schrijft de versie-info weg).

### Releasen

Versies volgen Semantic Versioning; de enige bron is de Git-tag `vX.Y.Z`.

```bash
uv run python scripts/release.py release X.Y.Z --dry-run
uv run python scripts/release.py release X.Y.Z --push
```

Het script:

1. controleert dat je op `main` zit, de werkboom schoon is, de versie hoger is dan de laatste
   tag, en dat tests en ruff slagen;
2. zet in `CHANGELOG.md` de sectie "Unreleased" om naar `[X.Y.Z] - datum` en commit dat als
   `chore(release): vX.Y.Z`;
3. maakt de tag `vX.Y.Z`;
4. bouwt met PyInstaller, draait de smoke-test en verpakt `dist\mp3sanitizer-X.Y.Z-win64.zip`;
5. met `--push`: `git push --follow-tags`.

Op GitHub draait bij elke push ruff + pytest (Windows). Bij een `v*`-tag bouwt de CI de zip
opnieuw en publiceert die als release-asset, met de changelogsectie als releasetekst.

## Licentie

MIT, zie [LICENSE](LICENSE).
