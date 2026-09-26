"""Bouwt de handleiding van Mp3Sanitizer als PDF (ReportLab Platypus).

    uv run python docs/manual/build_pdf.py <screenshotmap> <uitvoer.pdf> <versie>

De screenshots maak je eerst met docs/manual/screenshots.py. Lettertypen: Segoe UI, Segoe UI
Symbol en Consolas uit C:/Windows/Fonts (dus Windows).
"""

import sys
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

SHOTS = Path(sys.argv[1])
OUTPUT = Path(sys.argv[2])
VERSION = sys.argv[3] if len(sys.argv) > 3 else "0.10.1"

FONTS = Path("C:/Windows/Fonts")
pdfmetrics.registerFont(TTFont("Segoe", str(FONTS / "segoeui.ttf")))
pdfmetrics.registerFont(TTFont("Segoe-Bold", str(FONTS / "segoeuib.ttf")))
pdfmetrics.registerFont(TTFont("Segoe-Italic", str(FONTS / "segoeuii.ttf")))
pdfmetrics.registerFont(TTFont("Segoe-BoldItalic", str(FONTS / "segoeuiz.ttf")))
pdfmetrics.registerFont(TTFont("Segoe-Semi", str(FONTS / "seguisb.ttf")))
pdfmetrics.registerFont(TTFont("Mono", str(FONTS / "consola.ttf")))
pdfmetrics.registerFont(TTFont("Sym", str(FONTS / "seguisym.ttf")))
pdfmetrics.registerFontFamily(
    "Segoe", normal="Segoe", bold="Segoe-Bold", italic="Segoe-Italic", boldItalic="Segoe-BoldItalic"
)

ACCENT = colors.HexColor("#1F5FA8")
MUTED = colors.HexColor("#5B6573")
LIGHT = colors.HexColor("#EEF3FA")
GRID = colors.HexColor("#C9D3E0")

base = getSampleStyleSheet()
S = {
    "body": ParagraphStyle(
        "body", parent=base["BodyText"], fontName="Segoe", fontSize=10.2, leading=14.6, spaceAfter=6
    ),
    "h1": ParagraphStyle(
        "h1",
        parent=base["Heading1"],
        fontName="Segoe-Bold",
        fontSize=20,
        leading=24,
        textColor=ACCENT,
        spaceBefore=4,
        spaceAfter=10,
    ),
    "h2": ParagraphStyle(
        "h2",
        parent=base["Heading2"],
        fontName="Segoe-Semi",
        fontSize=13.5,
        leading=17,
        textColor=ACCENT,
        spaceBefore=12,
        spaceAfter=5,
    ),
    "bullet": ParagraphStyle(
        "bullet",
        fontName="Segoe",
        fontSize=10.2,
        leading=14.4,
        leftIndent=14,
        bulletIndent=4,
        spaceAfter=3,
    ),
    "caption": ParagraphStyle(
        "caption",
        fontName="Segoe-Italic",
        fontSize=9,
        leading=12,
        textColor=MUTED,
        alignment=TA_CENTER,
        spaceBefore=4,
        spaceAfter=12,
    ),
    "cell": ParagraphStyle("cell", fontName="Segoe", fontSize=9.2, leading=12),
    "cellb": ParagraphStyle("cellb", fontName="Segoe-Bold", fontSize=9.2, leading=12),
    "note": ParagraphStyle(
        "note",
        fontName="Segoe",
        fontSize=9.6,
        leading=13.5,
        backColor=LIGHT,
        borderColor=GRID,
        borderWidth=0.6,
        borderPadding=7,
        leftIndent=7,
        rightIndent=7,
        spaceBefore=8,
        spaceAfter=12,
    ),
    "title": ParagraphStyle(
        "title",
        fontName="Segoe-Bold",
        fontSize=34,
        leading=40,
        textColor=ACCENT,
        alignment=TA_CENTER,
    ),
    "subtitle": ParagraphStyle(
        "subtitle", fontName="Segoe", fontSize=15, leading=20, textColor=MUTED, alignment=TA_CENTER
    ),
    "toc0": ParagraphStyle("toc0", fontName="Segoe", fontSize=11, leading=17, leftIndent=0),
    "toc1": ParagraphStyle(
        "toc1", fontName="Segoe", fontSize=9.6, leading=13.5, leftIndent=16, textColor=MUTED
    ),
}

MAX_W = A4[0] - 4.4 * cm
_SYMBOLS = "▶⇄★✕■"


def glyphs(text: str) -> str:
    """Symbolen die Segoe UI niet heeft, in Segoe UI Symbol zetten."""
    for ch in _SYMBOLS:
        text = text.replace(ch, f'<font name="Sym">{ch}</font>')
    return text


class P(Paragraph):
    def __init__(self, text, style, **kw):
        super().__init__(glyphs(text), style, **kw)


_figure = 0


def kbd(key: str) -> str:
    return f'<font name="Mono" size="9" color="#1F3B5C">{key}</font>'


def code(text: str) -> str:
    return f'<font name="Mono" size="9">{text}</font>'


def p(text: str) -> Paragraph:
    return P(text, S["body"])


def bullets(items: list[str]) -> list[Paragraph]:
    return [P(i, S["bullet"], bulletText="•") for i in items]


def note(text: str) -> Paragraph:
    return P(f"<b>Tip.</b> {text}", S["note"])


def warn(text: str) -> Paragraph:
    return P(f"<b>Let op.</b> {text}", S["note"])


class Heading(Paragraph):
    """Kop die in de inhoudsopgave komt."""

    def __init__(self, text: str, level: int):
        super().__init__(text, S["h1" if level == 0 else "h2"])
        self.toc_level = level
        self.toc_text = text


def h1(text: str) -> list:
    return [Heading(text, 0)]


def h2(text: str) -> Heading:
    return Heading(text, 1)


def figure(name: str, caption: str, width: float = 1.0) -> KeepTogether:
    global _figure
    _figure += 1
    path = SHOTS / f"{name}.png"
    iw, ih = ImageReader(str(path)).getSize()
    w = min(MAX_W * width, iw * 0.75)  # niet groter dan ~96 dpi
    h = w * ih / iw
    max_h = A4[1] * 0.52
    if h > max_h:
        h = max_h
        w = h * iw / ih
    img = Image(str(path), width=w, height=h)
    img.hAlign = "CENTER"
    frame = Table(
        [[img]],
        style=[
            ("BOX", (0, 0), (-1, -1), 0.6, GRID),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ],
    )
    return KeepTogether([Spacer(1, 4), frame, P(f"Afbeelding {_figure} — {caption}", S["caption"])])


def table(rows: list[list[str]], widths: list[float], header: bool = True) -> Table:
    data = [
        [P(c, S["cellb" if header and i == 0 else "cell"]) for c in row]
        for i, row in enumerate(rows)
    ]
    t = Table(data, colWidths=[w * cm for w in widths], repeatRows=1 if header else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), LIGHT))
    t.setStyle(TableStyle(style))
    return t


class ManualDoc(BaseDocTemplate):
    def __init__(self, filename: str):
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=2.2 * cm,
            rightMargin=2.2 * cm,
            topMargin=2.0 * cm,
            bottomMargin=2.0 * cm,
            title=f"Mp3Sanitizer {VERSION} – Handleiding",
            author="Mp3Sanitizer",
            subject="Handleiding",
            creator="Mp3Sanitizer",
        )
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="f")
        self.addPageTemplates(
            [
                PageTemplate(id="cover", frames=[frame], onPage=self._cover),
                PageTemplate(id="body", frames=[frame], onPage=self._decorate),
            ]
        )

    def afterFlowable(self, flowable):
        if isinstance(flowable, Heading):
            key = f"h{self.seq.nextf('heading')}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(flowable.toc_text, key, level=flowable.toc_level)
            self.notify("TOCEntry", (flowable.toc_level, flowable.toc_text, self.page, key))

    @staticmethod
    def _cover(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(ACCENT)
        canvas.rect(0, A4[1] - 1.1 * cm, A4[0], 1.1 * cm, stroke=0, fill=1)
        canvas.restoreState()

    @staticmethod
    def _decorate(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.6)
        canvas.line(2.2 * cm, 1.45 * cm, A4[0] - 2.2 * cm, 1.45 * cm)
        canvas.setFont("Segoe", 8.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(2.2 * cm, 1.0 * cm, f"Mp3Sanitizer {VERSION} – Handleiding")
        canvas.drawRightString(A4[0] - 2.2 * cm, 1.0 * cm, f"Pagina {doc.page}")
        canvas.restoreState()


# =============================================================================================
story: list = []

# --- titelpagina ------------------------------------------------------------------------------
story += [
    Spacer(1, 3.2 * cm),
    Paragraph("Mp3Sanitizer", S["title"]),
    Spacer(1, 0.3 * cm),
    Paragraph("Handleiding", S["subtitle"]),
    Spacer(1, 0.15 * cm),
    Paragraph(f"versie {VERSION} · {date.today():%d-%m-%Y}", S["subtitle"]),
    Spacer(1, 1.2 * cm),
]
_cw, _ch = ImageReader(str(SHOTS / "01_hoofdvenster.png")).getSize()
cover = Image(str(SHOTS / "01_hoofdvenster.png"), width=MAX_W, height=MAX_W * _ch / _cw)
story += [
    cover,
    Spacer(1, 1.0 * cm),
    Paragraph(
        "Inventariseren, opschonen en hernoemen van een muziekcollectie op basis van de "
        "bestandsnaam <i>Artiest - Titel (Jaar)</i>.",
        S["subtitle"],
    ),
    NextPageTemplate("body"),
    PageBreak(),
]

# --- inhoudsopgave ----------------------------------------------------------------------------
toc = TableOfContents()
toc.levelStyles = [S["toc0"], S["toc1"]]
story += [Paragraph("Inhoud", S["h1"]), toc, PageBreak()]

# --- 1. inleiding -----------------------------------------------------------------------------
story += h1("1. Inleiding")
story += [
    p(
        "Mp3Sanitizer helpt je een grote muziekcollectie (duizenden bestanden) op orde te brengen. "
        "De app leest van elk bestand de naam en haalt daar artiest, titel en jaar uit. Die "
        "gegevens kun je bekijken, filteren, corrigeren en ten slotte gebruiken om bestanden "
        "consequent te hernoemen en in jaar- of decenniummappen te zetten."
    ),
    p("De gewenste vorm van een bestandsnaam is:"),
    p(
        f"&nbsp;&nbsp;&nbsp;&nbsp;{code('Artiest - Titel (Jaar).mp3')}&nbsp;&nbsp; bijvoorbeeld "
        f"{code('Queen - Innuendo (1991).mp3')}"
    ),
    h2("Veilig werken"),
    *bullets(
        [
            "Alles wat je bewerkt, blijft eerst <b>in het geheugen</b> (geel gemarkeerd). Er verandert "
            "pas iets op schijf als je <b>opslaat</b>, en dat gaat altijd via een <b>preview</b>.",
            "Bestaande bestanden worden <b>nooit overschreven</b>.",
            "Elke opslagactie wordt vastgelegd in een <b>journaal</b> en is terug te draaien met "
            "<i>Bestand → Laatste batch terugdraaien</i>.",
            "Verwijderen gaat standaard naar de <b>Prullenbak</b>, altijd na een bevestiging.",
            "Alles is met het toetsenbord te bedienen; de sneltoetsen staan in hoofdstuk 16.",
        ]
    ),
    note("Probeer de app de eerste keer op een <b>kopie</b> van (een deel van) je collectie."),
    PageBreak(),
]

# --- 2. installatie ---------------------------------------------------------------------------
story += h1("2. Installeren en starten")
story += [
    h2("Kant-en-klare versie (Windows)"),
    *bullets(
        [
            "Download <b>mp3sanitizer-X.Y.Z-win64.zip</b> van de releasepagina: "
            "github.com/ndboer/MP3Sanitizer/releases.",
            "Pak het zip-bestand uit, bijvoorbeeld naar <i>C:\\Programma's\\Mp3Sanitizer</i>.",
            f"Start {code('Mp3Sanitizer\\Mp3Sanitizer.exe')}. Installeren is niet nodig.",
        ]
    ),
    h2("Vanaf de broncode"),
    p(
        f"Met <b>uv</b> en Git geïnstalleerd: {code('git clone https://github.com/ndboer/MP3Sanitizer.git')}, "
        f"dan in die map {code('uv sync')} en {code('uv run mp3sanitizer')}."
    ),
    h2("Eerste keer"),
    p(
        f"Kies met {kbd('Ctrl+O')} (<i>Bestand → Map openen</i>) de hoofdmap van je muziek. De app "
        "onthoudt deze map en opent hem de volgende keer automatisch. Met "
        f"{kbd('F5')} (<i>Herlaad</i>) lees je de map opnieuw in, bijvoorbeeld na wijzigingen "
        "buiten de app."
    ),
    PageBreak(),
]

# --- 3. hoofdvenster --------------------------------------------------------------------------
story += h1("3. Het hoofdvenster")
story += [
    figure(
        "01_hoofdvenster",
        "Het hoofdvenster na het inlezen van een map. Bovenaan menu, "
        "werkbalk met snelfilter en zoekveld; in het midden de tabel; onderin de mini-player "
        "en de statusbalk met tellers.",
    ),
    h2("Onderdelen"),
    *bullets(
        [
            "<b>Menubalk</b>: Bestand, Bewerken, Afspelen, Beeld en Help.",
            "<b>Werkbalk</b>: Map openen, Herlaad, het <b>snelfilter</b> en het <b>zoekveld</b> "
            f"({kbd('Ctrl+F')}; {kbd('Esc')} maakt het leeg).",
            "<b>Tabel</b>: één rij per bestand. Klik op een kolomkop om te sorteren.",
            "<b>Mini-player</b>: afspelen, pauzeren, spoelen en volume (hoofdstuk 10).",
            "<b>Statusbalk</b>: totaal, zichtbaar, geselecteerd, gewijzigd en parse-fouten; rechts "
            "meldingen, voortgang en de knop <i>Annuleren</i> tijdens achtergrondtaken.",
        ]
    ),
    h2("Kolommen"),
    table(
        [
            ["Kolom", "Betekenis"],
            ["▶ (eerste kolom)", "Afspelen/stoppen van die rij (■ bij de track die speelt)."],
            [
                "Status",
                "OK, Geen jaar, Parse-fout, Gewijzigd, Ongeldig; eventueel aangevuld met "
                "“tags ≠” of “duplicaat”. De tooltip geeft uitleg.",
            ],
            ["Artiest, Titel, Jaar", "Uit de bestandsnaam, of je (nog niet opgeslagen) wijziging."],
            ["Folder", "Map ten opzichte van de hoofdmap."],
            ["Bestandsnaam", "Huidige naam op schijf."],
            ["Duur, Bitrate, Grootte", "Optioneel; op de achtergrond ingelezen."],
            ["Tag-artiest, Tag-titel, Tag-jaar", "Optioneel; de tags in het bestand."],
        ],
        [4.6, 12.0],
    ),
    p(
        "Extra kolommen zet je aan via <i>Beeld → Kolommen</i> of met een rechtsklik op een "
        "kolomkop. Breedte en volgorde van de kolommen worden onthouden."
    ),
    h2("Kleuren"),
    table(
        [
            ["Markering", "Betekenis"],
            ["Gele achtergrond", "Gewijzigd, nog niet opgeslagen."],
            ["Rode achtergrond", "Ongeldig: leeg, of tekens die Windows niet toestaat."],
            ["Rode statustekst", "Parse-fout of ongeldige naam."],
            ["Oranje tekst", "Tags wijken af van de bestandsnaam."],
            ["Vetgedrukt", "Deze track speelt nu."],
        ],
        [4.6, 12.0],
    ),
    PageBreak(),
]

# --- 4. inlezen -------------------------------------------------------------------------------
story += h1("4. Inlezen en herkennen")
story += [
    p(
        "Bij het openen van een map worden alle audiobestanden (standaard .mp3, .flac, .m4a, "
        ".wav en .ogg, ook in submappen) direct in de tabel gezet. Daarna leest de app op de "
        "achtergrond duur, bitrate, grootte en tags; je kunt intussen gewoon verder werken."
    ),
    h2("Zo wordt een bestandsnaam gelezen"),
    *bullets(
        [
            f"Er wordt gesplitst op het <b>eerste</b> {code(' - ')} (ook een en- of em-streepje). "
            f"De titel mag zelf een streepje bevatten: {code('A-ha - Take On Me - Live')}.",
            f"Een jaar {code('(dddd)')} aan het eind telt als het tussen 1900 en volgend jaar ligt.",
            f"Een <b>volgnummer</b> direct na het jaar, zoals {code('(1985)(2)')} of "
            f"{code('(1985) (2)')}, wordt genegeerd. Zo'n nummer ontstaat als er al een bestand "
            "met dezelfde naam bestond; de Status-tooltip meldt het.",
            "Dubbele spaties worden genegeerd.",
            "Namen zonder artiest–titel-scheiding krijgen de status <b>Parse-fout</b>; ze blijven "
            "zichtbaar en zijn met de hand te corrigeren.",
        ]
    ),
    figure(
        "02_filter_parsefouten",
        "Snelfilter “Alleen parse-fouten” (Ctrl+3): namen die niet "
        "volgens het patroon zijn opgebouwd. De rest van de naam staat in Titel, zodat je "
        "alleen de artiest hoeft in te vullen.",
    ),
    h2("Tags vergelijken"),
    p(
        "Als de tags (artiest, titel, jaar) afwijken van de bestandsnaam, staat in de Status-kolom "
        "“tags ≠” en kleuren de betreffende tag-kolommen oranje. De tooltip toont precies wat er "
        "verschilt."
    ),
    figure(
        "03_filter_tagmismatch",
        "Snelfilter “Tag-mismatch” (Ctrl+5) met de optionele kolommen Duur en Bitrate zichtbaar.",
    ),
    h2("Sorteren"),
    p(
        "Sorteren op artiest negeert lidwoorden: “The Beatles” en “Beatles, The” staan bij de B. "
        "Getallen sorteren natuurlijk (“Song 9” vóór “Song 10”). Na een bewerking blijft een rij "
        "staan waar hij staat; klik opnieuw op de kolomkop om te hersorteren."
    ),
    PageBreak(),
]

# --- 5. filteren ------------------------------------------------------------------------------
story += h1("5. Filteren en zoeken")
story += [
    p(
        "Het <b>snelfilter</b> in de werkbalk (of <i>Beeld → Filter</i>) beperkt de tabel tot een "
        "bepaalde groep. Het <b>zoekveld</b> zoekt tegelijk in artiest, titel en bestandsnaam, "
        "zonder op hoofdletters of accenten te letten."
    ),
    table(
        [
            ["Toets", "Filter", "Toont"],
            [kbd("Ctrl+1"), "Alles", "Alle bestanden."],
            [kbd("Ctrl+2"), "Gewijzigd", "Niet-opgeslagen wijzigingen."],
            [kbd("Ctrl+3"), "Alleen parse-fouten", "Namen die niet volgens het patroon zijn."],
            [kbd("Ctrl+4"), "Zonder jaar", "Tracks zonder (geldig) jaar."],
            [kbd("Ctrl+5"), "Tag-mismatch", "Tags wijken af van de bestandsnaam."],
            [kbd("Ctrl+6"), "Ongeldige namen", "Lege velden of verboden tekens."],
            [
                kbd("Ctrl+7"),
                "Verkeerde jaarmap",
                "Staat niet in de map die bij het jaar hoort "
                "(als je een map-sjabloon gebruikt, hoofdstuk 11).",
            ],
            [kbd("Ctrl+8"), "Duplicaten", "Waarschijnlijk dubbele nummers (hoofdstuk 9)."],
        ],
        [2.2, 4.2, 10.2],
    ),
    PageBreak(),
]

# --- 6. bewerken ------------------------------------------------------------------------------
story += h1("6. Bewerken")
story += [
    p(
        f"Artiest, Titel en Jaar zijn te bewerken met {kbd('F2')} of een dubbelklik. "
        f"{kbd('F2')} op een andere kolom bewerkt de artiest. {kbd('Enter')} bevestigt, "
        f"{kbd('Esc')} annuleert. Een jaar moet tussen 1900 en volgend jaar liggen; ongeldige "
        "invoer wordt geweigerd met een melding in de statusbalk."
    ),
    figure(
        "04_bewerken",
        "Bewerken in de tabel. Geel: gewijzigd (nog niet opgeslagen). Rood: "
        "ongeldig (hier “AC/DC”: de schuine streep mag niet in een Windows-bestandsnaam). "
        "In de rij van Prince staat de editor open.",
    ),
    h2("Meer bewerkfuncties"),
    table(
        [
            ["Functie", "Toets", "Wat"],
            ["Bulk bewerken", kbd("Ctrl+B"), "Eén veld invullen voor alle geselecteerde rijen."],
            ["Wissel artiest ⇄ titel", kbd("Ctrl+W"), "Voor namen als “Help! - The Beatles”."],
            ["Terugdraaien", kbd("Ctrl+R"), "Wijzigingen van de geselecteerde rijen ongedaan."],
            [
                "Ongedaan maken / opnieuw",
                f"{kbd('Ctrl+Z')} / {kbd('Ctrl+Y')}",
                "Voor alle bewerkingen in het geheugen; een bulkactie is één stap.",
            ],
            ["Alle wijzigingen verwerpen", "—", "Menu Bewerken; ook dit is ongedaan te maken."],
        ],
        [4.3, 3.2, 9.1],
    ),
    figure(
        "05_bulk_bewerken",
        "Bulk bewerken: kies het veld en de nieuwe waarde. Leeg bij Jaar "
        "betekent: jaar verwijderen.",
        width=0.6,
    ),
    figure(
        "06_menu_bewerken",
        "Het menu Bewerken met alle bewerk- en opschoonfuncties en hun sneltoetsen.",
        width=0.55,
    ),
    figure("08_contextmenu", "Rechtsklik op een rij opent dit contextmenu.", width=0.45),
    note(
        "Bij afsluiten, herladen of een andere map openen met openstaande wijzigingen vraagt de "
        "app wat je wilt: <b>Opslaan</b> (als sessie, hoofdstuk 13), <b>Verwerpen</b> of "
        "<b>Annuleren</b>."
    ),
    PageBreak(),
]

# --- 7. artiesten -----------------------------------------------------------------------------
story += h1("7. Artiesten zoeken en corrigeren")
story += [
    p(
        f"<i>Bewerken → Artiesten zoeken en corrigeren</i> ({kbd('Ctrl+Shift+F')}) zoekt "
        "<b>fuzzy</b> op artiest. Hoofdletters, accenten (Beyoncé = Beyonce), lidwoorden (ook in "
        "de vorm “Beatles, The”), “&amp;/and/en/+” en leestekens tellen niet mee. Met de "
        "schuifregelaar stel je in hoe streng de vergelijking is (standaard 85)."
    ),
    figure(
        "13_artiesten_zoeken",
        "Zoeken op “beatles”: de resultaten zijn gegroepeerd per "
        "schrijfwijze met het aantal tracks, inclusief de tikfout “The Beatels”. Vink aan wat "
        "je wilt corrigeren, vul de juiste schrijfwijze in en kies Toepassen.",
    ),
    *bullets(
        [
            "Het veld <i>Juiste schrijfwijze</i> wordt vooraf ingevuld met de meestgebruikte "
            "schrijfwijze.",
            "<b>Toepassen</b> past alle aangevinkte tracks aan in één undo-stap.",
        ]
    ),
    h2("Overzicht en voorstellen"),
    p(
        f"Het tabblad <i>Overzicht en voorstellen</i> ({kbd('Ctrl+Shift+A')}) toont alle "
        "artiesten met het aantal tracks, en rechts groepen van waarschijnlijk dezelfde artiest. "
        "Pas de voorgestelde schrijfwijze aan en kies <b>Toepassen op cluster</b>."
    ),
    figure(
        "14_artiesten_overzicht",
        "Links alle artiesten (Enter zoekt op die artiest), rechts "
        "automatische voorstellen, zoals The Beatles, Beyoncé en Simon &amp; Garfunkel.",
    ),
    h2("Opzoeken op MusicBrainz"),
    p(
        "Met <b>Opzoeken op MusicBrainz</b> (in het zoekvenster of via rechtsklik op een rij) "
        "vraag je de officiële naam op. Je ziet naam, sort-name, land, toelichting en score; "
        "alleen kandidaten met een score van 80 of hoger worden getoond. De gekozen kandidaat "
        "vult de <b>officiële naam</b> in, niet de sort-name."
    ),
    figure(
        "15_musicbrainz",
        "Kandidaten van MusicBrainz. Kies er één met Enter of dubbelklik.",
        width=0.8,
    ),
    note(
        "De app doet maximaal één verzoek per seconde (zoals MusicBrainz vraagt) en onthoudt "
        "de resultaten 30 dagen, dus dezelfde vraag is de volgende keer direct beantwoord."
    ),
    PageBreak(),
]

# --- 8. batch-correcties ----------------------------------------------------------------------
story += h1("8. Batch-correcties (opschoonregels)")
story += [
    p(
        f"<i>Bewerken → Batch-correcties</i> ({kbd('Ctrl+K')}) past opschoonregels in één keer "
        "toe op de hele collectie, het huidige filter of de geselecteerde rijen. Vink de regels "
        "aan die je wilt gebruiken; een combinatie sla je op als <b>opschoonprofiel</b>."
    ),
    figure(
        "17_batchcorrecties",
        "Regels kiezen, profiel laden of opslaan en de scope bepalen. "
        "Instellingen per regel via Instellingen… of een dubbelklik.",
        width=0.65,
    ),
    h2("De regels"),
    table(
        [
            ["Regel", "Wat het doet", "Voorbeeld"],
            [
                "Spaties opschonen",
                "Spaties aan de randen, dubbele spaties, rond “ - ” en haakjes.",
                "Song( Live ) → Song (Live)",
            ],
            [
                "Title Case",
                "Hoofdletter per woord; kleine woorden klein (niet aan het begin); "
                "afkortingen, Romeinse cijfers en McCartney blijven intact.",
                "in the air tonight → In the Air Tonight",
            ],
            [
                "Eigen vervangingsregels",
                "Zoek → vervang, met standaardregels.",
                "Queen Vs Bowie → Queen vs. Bowie; &amp;amp; → &amp;",
            ],
            [
                "Lidwoord",
                "“Beatles, The” ↔ “The Beatles” consequent (instelbaar).",
                "Beatles, The → The Beatles",
            ],
            [
                "Featuring",
                "feat, featuring, ft, f. → ft. (of feat.); ook in haakjes; eventueel "
                "naar artiest of titel verplaatsen.",
                "Stan (Featuring Dido) → Stan (ft. Dido)",
            ],
            [
                "Afkortingen",
                "Letters met punten en een vaste lijst (DJ, MC, ABBA, AC/DC, …).",
                "u.s.a → U.S.A.; dj → DJ",
            ],
            [
                "Romeinse cijfers",
                "Alleen geldige getallen, t/m XXXIX, na Part/Vol./… of aan het "
                "eind van de titel; uitzonderingen zoals Mix.",
                "Rocky Iv → Rocky IV; Club Mix blijft",
            ],
            [
                "Jaar uit tag",
                "Neemt het jaar uit de tag over als de naam geen jaar heeft.",
                "Bohemian Rhapsody → 1975",
            ],
        ],
        [3.5, 7.2, 5.9],
    ),
    p(
        "De regels worden altijd in deze volgorde toegepast, ongeacht de volgorde waarin je ze "
        "aanvinkt."
    ),
    h2("Preview en toepassen"),
    figure(
        "18_batchcorrecties_preview",
        "De preview toont per veld oud → nieuw; verwijderde "
        "delen zijn rood, toegevoegde groen. Alleen aangevinkte regels worden toegepast. "
        "Spatie schakelt de geselecteerde regels aan of uit.",
    ),
    p(
        "De wijzigingen komen in de tabel als niet-opgeslagen wijziging (één undo-stap). Opslaan "
        f"naar schijf doe je daarna met {kbd('Ctrl+S')} (hoofdstuk 11)."
    ),
    h2("Vervangingsregels bewerken"),
    p(
        "<i>Bewerken → Vervangingsregels</i> opent de regeleditor. Per regel stel je zoektekst, "
        "vervangtekst, veld (artiest, titel of beide), heel woord, hoofdlettergevoelig en regex "
        "in. De volgorde wijzig je door te slepen of met Omhoog/Omlaag. Het testveld laat direct "
        "zien wat de regel doet. Standaardregels kun je uitzetten maar niet verwijderen."
    ),
    figure("19_regeleditor", "De regeleditor met een eigen regel “Pt. → Part” en het testveld."),
    figure(
        "20_regeleditor_fout",
        "Een ongeldige reguliere expressie wordt direct gemeld; zo'n regel wordt overgeslagen.",
        width=0.8,
    ),
    p("Met <b>Importeren/Exporteren</b> deel je regelsets als JSON-bestand."),
    h2("Instellingen per regel"),
    figure(
        "21_instellingen_romeins",
        "Instellingen voor Romeinse cijfers: tot welke waarde "
        "altijd, na welke woorden, aan het eind van de titel, en uitzonderingen.",
        width=0.55,
    ),
    figure(
        "22_instellingen_featuring",
        "Instellingen voor featuring: notatie en verplaatsen.",
        width=0.5,
    ),
    PageBreak(),
]

# --- 9. duplicaten ----------------------------------------------------------------------------
story += h1("9. Duplicaten")
story += [
    p(
        f"<i>Bewerken → Duplicaten zoeken</i> ({kbd('Ctrl+D')}) zoekt nummers die waarschijnlijk "
        "dubbel zijn, op basis van genormaliseerde artiest en titel."
    ),
    *bullets(
        [
            "<b>Strikt</b> (exact na normalisatie) of <b>fuzzy</b> met een drempel.",
            "<b>Jaar negeren</b> ja/nee.",
            "<b>Versies negeren</b>: (Remix), (Live), (Radio Edit), (Extended Mix), (Remastered).",
            "Optioneel <b>duur ±2 s</b> als extra criterium.",
        ]
    ),
    figure(
        "16_duplicaten",
        "Duplicaatgroepen met bitrate, duur, grootte, jaar en map. Per groep "
        "is de beste versie gemarkeerd met ★ behouden; de rest is aangevinkt voor verwijderen.",
    ),
    p(
        "<b>Beste automatisch behouden</b> kiest per groep: hoogste bitrate, dan langste duur, dan "
        "kortste pad. Pas de vinkjes per groep aan met de spatiebalk; Enter speelt een track af. "
        "<b>Aangevinkte verwijderen</b> loopt via de gewone bevestiging (hoofdstuk 12)."
    ),
    warn(
        "Als in een groep alle tracks zijn aangevinkt, waarschuwt de app dat er niets van "
        "overblijft."
    ),
    PageBreak(),
]

# --- 10. afspelen -----------------------------------------------------------------------------
story += h1("10. Afspelen")
story += [
    p(
        f"Klik op ▶ in de eerste kolom of druk op de {kbd('spatiebalk')} om de huidige rij af te "
        "spelen; nog eens drukken stopt. Een nieuwe track stopt de vorige."
    ),
    figure(
        "10_afspelen",
        "Afspelen: de spelende rij is vetgedrukt met een stopknop; onderin "
        "de mini-player met pauze, stop, positie, tijd en volume.",
    ),
    table(
        [
            ["Actie", "Toets"],
            ["Afspelen / stoppen", kbd("Spatie")],
            ["Stoppen", kbd("Ctrl+.")],
            ["5 seconden terug / vooruit", f"{kbd('Alt+←')} / {kbd('Alt+→')}"],
        ],
        [8.0, 8.6],
    ),
    p(
        "<b>Automatisch volgende geselecteerde</b>: selecteer meerdere rijen en vink deze optie "
        "aan; na afloop speelt de volgende geselecteerde track. Volume en deze optie worden "
        "onthouden."
    ),
    note(
        "Voor opslaan, terugdraaien en herladen stopt het afspelen vanzelf, omdat Windows een "
        "geopend bestand niet kan hernoemen."
    ),
    PageBreak(),
]

# --- 11. opslaan ------------------------------------------------------------------------------
story += h1("11. Opslaan: hernoemen en verplaatsen")
story += [
    p(
        f"<i>Bestand → Opslaan</i> ({kbd('Ctrl+S')}) opent altijd eerst een <b>preview</b>. Pas "
        "als je daar op Opslaan klikt, worden bestanden hernoemd en verplaatst."
    ),
    figure(
        "09_opslaan_preview",
        "De opslaan-preview: per bestand oud → nieuw pad met de "
        "verschillen gemarkeerd, opmerkingen bij botsingen, en onderaan de opties. Regels met "
        "✕ zijn niet uitvoerbaar.",
    ),
    h2("Opties"),
    table(
        [
            ["Optie", "Betekenis"],
            [
                "Doelmap",
                "Niet verplaatsen, jaarmap (1985\\) of decenniummap (1980-1989\\ of 80s\\; "
                "vanaf 2000 2000s\\). Tracks zonder jaar gaan naar de map bij "
                "“Zonder jaar naar” (standaard _Onbekend\\).",
            ],
            [
                "Bij botsing",
                "Overslaan, suffix “ (2)” toevoegen of als duplicaat markeren. Er wordt "
                "nooit overschreven.",
            ],
            [
                "Ook niet-bewerkte tracks",
                "Normaliseert ook namen die je niet hebt bewerkt en zet tracks in de juiste map.",
            ],
            ["Tags bijwerken", "Schrijft artiest, titel en jaar ook in de tags."],
            [
                "Lege mappen opruimen",
                "Verwijdert mappen die na het verplaatsen leeg zijn (nooit de hoofdmap).",
            ],
        ],
        [4.4, 12.2],
    ),
    h2("Waarschuwingen"),
    *bullets(
        [
            "<b>Doelbestand bestaat al</b>: afgehandeld volgens de gekozen botsingsregel.",
            "<b>Alleen hoofdletters wijzigen</b>: gaat via een tijdelijke naam (Windows ziet "
            f"{code('a.mp3')} en {code('A.mp3')} als hetzelfde bestand).",
            "<b>Pad langer dan 259 tekens</b>: kan problemen geven in oudere programma's.",
            "<b>Ongeldige naam</b>: niet aan te vinken; corrigeer eerst de artiest of titel.",
        ]
    ),
    h2("Na het opslaan"),
    p(
        "Het opslaan draait op de achtergrond met voortgangsbalk; <i>Annuleren</i> kan tussendoor. "
        "Een fout bij één bestand stopt de rest niet; na afloop volgt een overzicht."
    ),
    h2("Terugdraaien"),
    p(
        "<i>Bestand → Laatste batch terugdraaien</i> zet de bestanden van de laatste opslagactie "
        "terug naar hun oude naam en map, herstelt bijgewerkte tags en ruimt mappen op die de "
        "batch had aangemaakt. Dat werkt ook voor opslagacties uit oudere versies van de app."
    ),
    note(
        "Na het opslaan wordt de ongedaan-maken-geschiedenis (Ctrl+Z) gewist: de opgeslagen "
        "namen zijn het nieuwe uitgangspunt. Terugdraaien op schijf gaat via het journaal."
    ),
    PageBreak(),
]

# --- 12. verwijderen --------------------------------------------------------------------------
story += h1("12. Verwijderen")
story += [
    p(
        f"{kbd('Del')} (of rechtsklik → Verwijderen) verplaatst de geselecteerde bestanden naar de "
        "<b>Prullenbak</b>. Je krijgt altijd eerst het aantal en de lijst te zien."
    ),
    figure("11_verwijderen", "Bevestiging vóór het verwijderen naar de Prullenbak.", width=0.7),
    p(
        "<b>Permanent verwijderen</b> kan alleen via het vinkje in dit venster en vraagt om een "
        "extra bevestiging. Enter kiest dan Annuleren, zodat het nooit per ongeluk gebeurt."
    ),
    figure(
        "12_verwijderen_permanent",
        "Permanent verwijderen: rode waarschuwing, en Annuleren is de standaardknop.",
        width=0.7,
    ),
    warn(
        "Verwijderde bestanden zijn niet terug te zetten met “Laatste batch terugdraaien”. "
        "Haal ze terug uit de Prullenbak van Windows."
    ),
    PageBreak(),
]

# --- 13. sessies en export --------------------------------------------------------------------
story += h1("13. Sessies, export en Verkenner")
story += [
    figure("07_menu_bestand", "Het menu Bestand.", width=0.55),
    h2("Sessie opslaan en openen"),
    p(
        f"<i>Sessie opslaan</i> ({kbd('Ctrl+Shift+S')}) bewaart je niet-opgeslagen wijzigingen in "
        f"een projectbestand ({code('*.mp3s.json')}). <i>Sessie openen</i> ({kbd('Ctrl+Shift+O')}) "
        "leest de bijbehorende map opnieuw in en zet de wijzigingen terug als één undo-stap. "
        "Bestanden die intussen verdwenen zijn, worden gemeld."
    ),
    h2("Exporteren naar CSV"),
    p(
        "<i>Bestand → Exporteren naar CSV</i> slaat het overzicht op zoals je het ziet: alleen de "
        "zichtbare rijen (filter en zoekterm tellen mee) en de zichtbare kolommen, in de getoonde "
        "volgorde. Het bestand gebruikt puntkomma's en UTF-8 met BOM, zodat Nederlandse Excel het "
        "direct goed opent."
    ),
    h2("Openen in Verkenner"),
    p(
        f"Rechtsklik → <i>Openen in Verkenner</i> ({kbd('Ctrl+E')}) opent de map met het bestand "
        "al geselecteerd."
    ),
    PageBreak(),
]

# --- 14. help ---------------------------------------------------------------------------------
story += h1("14. Help, versie en updates")
story += [
    figure(
        "23_over",
        "Help → Over Mp3Sanitizer: versie, commit, builddatum en de versies van "
        "Python, PySide6 en mutagen. “Kopieer info” zet dit op het klembord voor een "
        "foutmelding.",
        width=0.55,
    ),
    *bullets(
        [
            "<b>Controleren op updates</b> vraagt de laatste versie op en meldt alleen of er een "
            "nieuwere is. Er wordt nooit iets gedownload of geïnstalleerd.",
            "<b>Automatisch controleren bij opstarten</b> staat standaard uit.",
            "<b>Map met logbestanden openen</b>: de eerste regel van elk logbestand bevat de versie.",
        ]
    ),
    h2("Licht en donker"),
    p("De app volgt automatisch het licht of donker thema van Windows."),
    figure(
        "24_donker_thema",
        "Hetzelfde hoofdvenster in het donkere thema; ook de markeringen "
        "voor gewijzigd en ongeldig blijven leesbaar.",
    ),
    PageBreak(),
]

# --- 15. bestanden ----------------------------------------------------------------------------
story += h1("15. Bestanden en instellingen")
story += [
    table(
        [
            ["Wat", "Waar"],
            ["Instellingen", code("%APPDATA%\\Mp3Sanitizer\\settings.json")],
            ["Opschoonregels en profielen", code("%APPDATA%\\Mp3Sanitizer\\rules.json")],
            ["Journaal (per opslagactie)", code("%LOCALAPPDATA%\\Mp3Sanitizer\\journal\\")],
            ["MusicBrainz-cache", code("%LOCALAPPDATA%\\Mp3Sanitizer\\musicbrainz_cache.json")],
            ["Logbestanden", code("%LOCALAPPDATA%\\Mp3Sanitizer\\logs\\")],
            ["Sessies", "Waar je ze zelf opslaat (*.mp3s.json)"],
        ],
        [5.0, 11.6],
    ),
    p(
        "Het journaal bestaat per opslagactie uit een <b>.json</b>-bestand (voor terugdraaien) en "
        "een leesbaar <b>.log</b>-bestand dat tijdens het uitvoeren regel voor regel wordt "
        "bijgewerkt."
    ),
    h2("Bestanden van andere versies"),
    *bullets(
        [
            "Een bestand van een <b>oudere</b> versie wordt automatisch bijgewerkt; eerst wordt een "
            f"back-up gemaakt ({code('naam.v1.bak')}).",
            "Een bestand van een <b>nieuwere</b> versie wordt niet overschreven; de app meldt dit.",
            f"Een <b>beschadigd</b> bestand wordt bewaard als {code('naam.corrupt')}; de app gebruikt "
            "dan de standaardinstellingen en meldt dit.",
        ]
    ),
    PageBreak(),
]

# --- 16. sneltoetsen --------------------------------------------------------------------------
story += h1("16. Sneltoetsen")
story += [
    table(
        [
            ["Actie", "Toets"],
            ["Map openen", kbd("Ctrl+O")],
            ["Herlaad", kbd("F5")],
            ["Zoeken (Esc wist)", kbd("Ctrl+F")],
            ["Snelfilters", f"{kbd('Ctrl+1')} … {kbd('Ctrl+8')}"],
            ["Cel bewerken", f"{kbd('F2')} of dubbelklik"],
            ["Bulk bewerken", kbd("Ctrl+B")],
            ["Wissel artiest ⇄ titel", kbd("Ctrl+W")],
            ["Wijzigingen van selectie terugdraaien", kbd("Ctrl+R")],
            ["Ongedaan maken / opnieuw", f"{kbd('Ctrl+Z')} / {kbd('Ctrl+Y')}"],
            ["Opslaan (via preview)", kbd("Ctrl+S")],
            ["Afspelen / stoppen", kbd("Spatie")],
            ["Stoppen", kbd("Ctrl+.")],
            ["5 s terug / vooruit", f"{kbd('Alt+←')} / {kbd('Alt+→')}"],
            ["Verwijderen", kbd("Del")],
            ["Artiesten zoeken en corrigeren", kbd("Ctrl+Shift+F")],
            ["Artiestenoverzicht en voorstellen", kbd("Ctrl+Shift+A")],
            ["Duplicaten zoeken", kbd("Ctrl+D")],
            ["Batch-correcties", kbd("Ctrl+K")],
            ["Openen in Verkenner", kbd("Ctrl+E")],
            ["Sessie opslaan / openen", f"{kbd('Ctrl+Shift+S')} / {kbd('Ctrl+Shift+O')}"],
            ["Lopende taak annuleren", kbd("Esc")],
            ["In previews: regels aan/uit", kbd("Spatie")],
        ],
        [9.5, 7.1],
    ),
    PageBreak(),
]

# --- 17. tips ---------------------------------------------------------------------------------
story += h1("17. Werkwijze en tips")
story += [
    h2("Een aanpak die goed werkt"),
    *bullets(
        [
            "1. Open de map en loop de <b>parse-fouten</b> (Ctrl+3) langs; vul ontbrekende artiesten "
            "in (F2, Ctrl+B voor meerdere tegelijk, Ctrl+W bij omgedraaide namen).",
            "2. Draai <b>Batch-correcties</b> (Ctrl+K) met het profiel “Standaard opschonen” en "
            "controleer de preview.",
            "3. Maak artiesten consequent met <b>Artiestenoverzicht en voorstellen</b> (Ctrl+Shift+A).",
            "4. Ruim <b>duplicaten</b> op (Ctrl+D).",
            "5. <b>Sla op</b> (Ctrl+S), eventueel met jaarmappen, en controleer het resultaat in "
            "Verkenner. Niet goed? Bestand → Laatste batch terugdraaien.",
        ]
    ),
    h2("Problemen oplossen"),
    table(
        [
            ["Situatie", "Oplossing"],
            [
                "Een bestand kan niet worden hernoemd",
                "Het is waarschijnlijk geopend in een ander "
                "programma. Sluit dat en sla opnieuw op; de rest van de batch is gewoon uitgevoerd.",
            ],
            [
                "Een naam wordt verkeerd opgeknipt",
                "Corrigeer met F2 of Ctrl+W; voor een "
                "terugkerend patroon kun je een eigen vervangingsregel maken.",
            ],
            [
                "MusicBrainz geeft geen resultaat",
                "Controleer de internetverbinding; bij drukte "
                "probeert de app het automatisch opnieuw.",
            ],
            ["De tabel toont “…”", "Duur, bitrate en tags worden nog ingelezen; even wachten."],
            [
                "Iets werkt niet zoals verwacht",
                "Help → Over → Kopieer info, en stuur dat samen met "
                "een beschrijving en het logbestand (Help → Map met logbestanden openen).",
            ],
        ],
        [5.2, 11.4],
    ),
]

doc = ManualDoc(str(OUTPUT))
doc.multiBuild(story)
print("PDF:", OUTPUT, OUTPUT.stat().st_size // 1024, "KB")
