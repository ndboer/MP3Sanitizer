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

| Actie                              | Toets            |
|------------------------------------|------------------|
| Map openen                         | Ctrl+O           |
| Herlaad (externe wijzigingen)      | F5               |
| Zoeken in artiest/titel/bestand    | Ctrl+F (Esc wist)|
| Snelfilter Alles / Parse-fouten / Zonder jaar / Tag-mismatch | Ctrl+1 … Ctrl+4 |
| Lopende taak annuleren             | Esc              |

- De bestandsnaam wordt gesplitst op de **eerste** ` - ` (ook en-/em-dash). Een jaar `(dddd)` aan
  het eind telt alleen als het tussen 1900 en volgend jaar ligt.
- Bestanden die niet volgens het patroon parsen krijgen de status **Parse-fout** en blijven
  zichtbaar.
- Duur, bitrate, grootte en tags worden na het scannen op de achtergrond ingelezen. Wijken de tags
  af van de bestandsnaam, dan toont de Status-kolom `tags ≠` (tooltip toont de verschillen).
- Extra kolommen zet je aan via **Beeld → Kolommen** of rechtsklik op de kolomkop.
- Sorteren op artiest negeert lidwoorden: "The Beatles" en "Beatles, The" staan bij de B.

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
