# Mp3Sanitizer

Desktop-applicatie (Python + PySide6) om een muziekcollectie van duizenden audiobestanden te
inventariseren, op te schonen en te hernoemen op basis van de bestandsnaam
`<Artiest> - <Titel> (<Jaar>)`.

> In ontwikkeling (0.x). Zie [CHANGELOG.md](CHANGELOG.md) voor wat er per versie klaar is.

## Installatie

Vereist: [uv](https://docs.astral.sh/uv/) en Git. uv installeert zelf een passende Python (3.12+).

```bash
git clone <repo-url> mp3sanitizer
cd mp3sanitizer
uv sync
uv run mp3sanitizer
```

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
| Lopende taak annuleren                  | Esc                |

Snelfilters: 1 Alles, 2 Gewijzigd (niet opgeslagen), 3 Alleen parse-fouten, 4 Zonder jaar,
5 Tag-mismatch, 6 Ongeldige namen, 7 Verkeerde jaarmap.

- De bestandsnaam wordt gesplitst op de **eerste** ` - ` (ook en-/em-dash). Een jaar `(dddd)` aan
  het eind telt alleen als het tussen 1900 en volgend jaar ligt.
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

Instellingen staan in `%APPDATA%\Mp3Sanitizer\settings.json`, het logbestand in
`%LOCALAPPDATA%\Mp3Sanitizer\logs\`.

## Ontwikkeling

```bash
uv sync
uv run pre-commit install
uv run pytest
uv run ruff check .
uv run ruff format .
```

- `mp3sanitizer/core/`: pure Python (parser, normalisatie, scanner, tags, opslag), zonder Qt.
- `mp3sanitizer/ui/`: PySide6-interface (model/view, workers).
- Werkwijze: `feat/<naam>` en `fix/<naam>`-branches, Conventional Commits, mergen in `main` als
  alle tests slagen.

## Licentie

MIT, zie [LICENSE](LICENSE).
