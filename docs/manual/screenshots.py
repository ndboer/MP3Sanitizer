"""Maakt screenshots van Mp3Sanitizer voor de handleiding (licht thema, plus één donker).

    uv run python docs/manual/screenshots.py <uitvoermap>

Werkt met een voorbeeldcollectie in een tijdelijke map; je eigen instellingen en muziek worden
niet gebruikt. Het volume staat op 0 tijdens het afspeelvoorbeeld.
"""

import math
import struct
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QPoint, Qt, QThreadPool
from PySide6.QtWidgets import QApplication, QMenu

from mp3sanitizer.core.journal import JournalStore
from mp3sanitizer.core.models import AudioInfo, Field
from mp3sanitizer.core.musicbrainz import ArtistCandidate
from mp3sanitizer.core.rules.config import RulesConfig
from mp3sanitizer.core.settings import SettingsStore
from mp3sanitizer.ui.about_dialog import AboutDialog
from mp3sanitizer.ui.artist_search import ArtistDialog, MusicBrainzDialog
from mp3sanitizer.ui.bulk_edit_dialog import BulkEditDialog
from mp3sanitizer.ui.corrections_dialog import CorrectionsDialog, RuleSettingsDialog, Scope
from mp3sanitizer.ui.delete_dialog import DeleteDialog
from mp3sanitizer.ui.duplicates_view import DuplicatesDialog
from mp3sanitizer.ui.main_window import MainWindow
from mp3sanitizer.ui.preview_dialog import PreviewDialog
from mp3sanitizer.ui.proxy_model import QuickFilter
from mp3sanitizer.ui.rule_editor import RuleEditorDialog
from mp3sanitizer.ui.save_dialog import SavePreviewDialog
from mp3sanitizer.ui.track_model import Col

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
app = QApplication([])
app.styleHints().setColorScheme(Qt.ColorScheme.Light)

# --- voorbeeldcollectie -------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
MUSIC = tmp / "Muziek"
FILES = {
    # pad: (duur s, kbps, tag-artiest, tag-titel, tag-jaar)
    "1965/The Beatles - Help! (1965).mp3": (139, 320, "The Beatles", "Help!", 1965),
    "1965/The Beatles - Yesterday (1965).mp3": (125, 320, "The Beatles", "Yesterday", 1965),
    "rommel/Beatles, The - Something (1969).mp3": (182, 192, "The Beatles", "Something", 1969),
    "rommel/beatles - let it be (1970).mp3": (243, 128, "Beatles", "Let It Be", 1970),
    "downloads/The Beatels - Girl (1965).mp3": (153, 128, None, None, None),
    "1991/Queen - Innuendo (1991).mp3": (391, 320, "Queen", "Innuendo", 1991),
    "downloads/Queen - Innuendo (1991)(2).mp3": (390, 192, "Queen", "Innuendo", 1991),
    "rommel/queen - bohemian rhapsody.mp3": (355, 256, "Queen", "Bohemian Rhapsody", 1975),
    "rommel/Queen Vs David Bowie - Under Pressure (1981).mp3": (
        248,
        256,
        "Queen & David Bowie",
        "Under Pressure",
        1981,
    ),
    "1984/bruce springsteen - born in the u.s.a (1984).mp3": (
        279,
        320,
        "Bruce Springsteen",
        "Born in the U.S.A.",
        1984,
    ),
    "1985/A-ha - Take On Me (1985).mp3": (225, 320, "a-ha", "Take On Me", 1985),
    "1985/Survivor - Rocky Iv Theme (1985).mp3": (230, 192, "Survivor", "Burning Heart", 1985),
    "2000/eminem - stan (featuring dido) (2000).mp3": (404, 320, "Eminem", "Stan", 2000),
    "2008/Beyoncé - Halo (2008).mp3": (261, 320, "Beyoncé", "Halo", 2008),
    "2003/Beyonce - Crazy In Love (2003).mp3": (236, 256, "Beyoncé", "Crazy In Love", 2003),
    "rommel/Simon &amp; Garfunkel - The Boxer (1969).mp3": (
        308,
        192,
        "Simon & Garfunkel",
        "The Boxer",
        1969,
    ),
    "rommel/Simon and Garfunkel - Mrs. Robinson (1968).mp3": (
        244,
        192,
        "Simon & Garfunkel",
        "Mrs. Robinson",
        1968,
    ),
    "rommel/dj shadow - Midnight In A Perfect World (1996).mp3": (
        298,
        256,
        "DJ Shadow",
        "Midnight in a Perfect World",
        1996,
    ),
    "rommel/Help! - The Beatles.mp3": (139, 128, "The Beatles", "Help!", 1965),
    "rommel/track 07.mp3": (201, 128, None, None, None),
    "rommel/Prince - 1999 (1982).mp3": (379, 320, "Prince", "1999", 1982),
    "1990s/U2 - One (1991).mp3": (276, 320, "U2", "One", 1991),
    "1990s/Nirvana - Come As You Are (1991).mp3": (218, 256, "Nirvana", "Come as You Are", 1992),
    "rommel/Guns N' Roses - Sweet Child O' Mine (1987).mp3": (
        356,
        320,
        "Guns N' Roses",
        "Sweet Child O' Mine",
        1987,
    ),
    "rommel/De Dijk - Mag Het Licht Uit (1994).mp3": (
        253,
        192,
        "De Dijk",
        "Mag Het Licht Uit",
        1994,
    ),
    "rommel/ABBA - Waterloo (1974).mp3": (167, 320, "ABBA", "Waterloo", 1974),
}
for rel in FILES:
    (MUSIC / rel).parent.mkdir(parents=True, exist_ok=True)
    (MUSIC / rel).write_bytes(b"\0" * 2048)


def tone(path: Path, seconds=6.0, rate=22050, freq=440):
    n = int(seconds * rate)
    data = b"".join(
        struct.pack("<h", int(800 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n)
    )
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    path.write_bytes(header + fmt + b"data" + struct.pack("<I", len(data)) + data)


(MUSIC / "2024").mkdir(parents=True, exist_ok=True)
tone(MUSIC / "2024" / "Demo - Afspeeltest (2024).wav")


def pump(seconds=0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def save(widget, name):
    pump(0.25)
    widget.grab().save(str(OUT / f"{name}.png"))
    print("screenshot", name)


store = SettingsStore.load(tmp / "config")
store.settings.visible_columns = [
    "status",
    "artist",
    "title",
    "year",
    "folder",
    "filename",
    "duration",
    "bitrate",
    "play",
]
store.settings.volume = 0  # geen geluid tijdens het maken van screenshots
w = MainWindow(store, QThreadPool(), JournalStore(tmp / "journal"))
w.show_update_dialogs = False
w.resize(1320, 720)
w.show()
w.start_scan(MUSIC)
while w.busy:
    pump(0.05)
infos = []
for t in w.model.tracks:
    rel = t.path.relative_to(MUSIC).as_posix()
    if rel in FILES:
        dur, br, ta, tt, ty = FILES[rel]
        infos.append((t.id, AudioInfo(float(dur), br, br * dur * 125, ta, tt, ty)))
w.model.set_infos(infos)
w.model.resort()
for col, width in (
    (Col.STATUS, 140),
    (Col.ARTIST, 180),
    (Col.TITLE, 220),
    (Col.YEAR, 50),
    (Col.FOLDER, 90),
    (Col.FILENAME, 300),
    (Col.DURATION, 55),
    (Col.BITRATE, 75),
):
    w.table.setColumnWidth(col, width)
pump(0.5)
ids = {t.filename: t.id for t in w.model.tracks}


def select_rows(filenames):
    sm = w.table.selectionModel()
    f = QItemSelectionModel.SelectionFlag
    sm.clearSelection()
    first = None
    for r in range(w.proxy.rowCount()):
        if w.proxy.index(r, Col.FILENAME).data() in filenames:
            sm.select(w.proxy.index(r, 0), f.Select | f.Rows)
            first = first if first is not None else r
    if first is not None:
        sm.setCurrentIndex(w.proxy.index(first, Col.ARTIST), f.NoUpdate)


# 1. Hoofdvenster na inlezen
select_rows({"Innuendo (1991).mp3"})
save(w, "01_hoofdvenster")

# 2. Snelfilter parse-fouten
w.set_quick_filter(QuickFilter.PARSE_ERRORS)
save(w, "02_filter_parsefouten")
w.set_quick_filter(QuickFilter.TAG_MISMATCH)
save(w, "03_filter_tagmismatch")
w.set_quick_filter(QuickFilter.ALL)

# 3. Bewerken: gewijzigde en ongeldige cellen + open editor
m = w.model
m.swap_artist_title([ids["Help! - The Beatles.mp3"]])
m.set_field([ids["track 07.mp3"]], Field.ARTIST, "AC/DC")
m.set_field([ids["track 07.mp3"]], Field.TITLE, "Thunderstruck")
m.set_field([ids["queen - bohemian rhapsody.mp3"]], Field.YEAR, 1975)
m.resort()
pump(0.3)
row = next(
    r
    for r in range(w.proxy.rowCount())
    if w.proxy.index(r, Col.FILENAME).data() == "Prince - 1999 (1982).mp3"
)
w.table.setCurrentIndex(w.proxy.index(row, Col.TITLE))
w.table.edit(w.proxy.index(row, Col.TITLE))
pump(0.2)
save(w, "04_bewerken")
w.table.closePersistentEditor(w.proxy.index(row, Col.TITLE))
w.table.setFocus()
w.table.clearSelection()

# 4. Bulk bewerken
d = BulkEditDialog(3, w, field=Field.YEAR, initial="1985")
d.show()
save(d, "05_bulk_bewerken")
d.close()

# 5. Menu Bewerken en contextmenu
for title, name in (("Be&werken", "06_menu_bewerken"), ("&Bestand", "07_menu_bestand")):
    menu = next(a.menu() for a in w.menuBar().actions() if a.text() == title)
    menu.popup(w.mapToGlobal(QPoint(40, 40)))
    save(menu, name)
    menu.close()
menu = QMenu(w)
w._add_row_actions(menu)
menu.popup(w.mapToGlobal(QPoint(300, 300)))
save(menu, "08_contextmenu")
menu.close()

# 6. Opslaan-preview
w._settings.folder_template = "year"
w._settings.collision_policy = "suffix"
sd = SavePreviewDialog(w.plan_inputs(), MUSIC, w._settings, w)
sd.include_unchanged.setChecked(True)
sd.resize(1250, 640)
sd.show()
save(sd, "09_opslaan_preview")
sd.close()

# 7. Afspelen
wav = ids["Demo - Afspeeltest (2024).wav"]
select_rows({"Demo - Afspeeltest (2024).wav"})
w.toggle_play(wav)
pump(1.5)
save(w, "10_afspelen")
w.player.stop()

# 8. Verwijderen
dd = DeleteDialog([r"downloads\Queen - Innuendo (1991)(2).mp3", r"rommel\track 07.mp3"], w)
dd.resize(640, 330)
dd.show()
save(dd, "11_verwijderen")
dd.permanent.setChecked(True)
save(dd, "12_verwijderen_permanent")
dd.close()


# 9. Artiesten
class FakeMB:
    def search_artist(self, name):
        return [
            ArtistCandidate(
                "b10bbbfc",
                "The Beatles",
                "Beatles, The",
                "GB",
                "UK rock band, “The Fab Four”",
                100,
                "Group",
            ),
            ArtistCandidate(
                "x1",
                "The Beatles Revival Band",
                "Beatles Revival Band, The",
                "DE",
                "tribute band",
                82,
                "Group",
            ),
        ]


ad = ArtistDialog(m, w._pool, FakeMB, query="beatles", parent=w)
ad.resize(1150, 620)
ad.show()
pump(1.0)
ad.results.expandItem(ad.results.topLevelItem(0))
save(ad, "13_artiesten_zoeken")
ad.tabs.setCurrentIndex(1)
pump(1.0)
ad.clusters.expandAll()
save(ad, "14_artiesten_overzicht")
ad.close()
mbd = MusicBrainzDialog(FakeMB(), "beatles", w._pool, w)
mbd.show()
pump(1.0)
save(mbd, "15_musicbrainz")
mbd.close()

# 10. Duplicaten
w._settings.dup_ignore_versions = True
dup = DuplicatesDialog(m, w._settings, w._pool, MUSIC, w.play_track, w)
dup.resize(1150, 480)
dup.show()
pump(1.0)
save(dup, "16_duplicaten")
dup.close()

# 11. Batch-correcties
m.edits.clear()
pump(0.2)
live = [t.id for t in m.tracks]
cfg = RulesConfig()
cd = CorrectionsDialog(
    m, cfg, {Scope.ALL: live, Scope.FILTER: live, Scope.SELECTION: []}, w._pool, ["The"], w
)
cd.show()
save(cd, "17_batchcorrecties")


class GrabPreview(PreviewDialog):
    def exec(self):
        self.resize(1200, 560)
        self.show()
        save(self, "18_batchcorrecties_preview")
        return 0


cd._preview_factory = GrabPreview
cd.preview_and_apply()
end = time.monotonic() + 5
while not cd.preview_button.isEnabled() and time.monotonic() < end:
    pump(0.05)
pump(0.3)
cd.close()

re_ = RuleEditorDialog(cfg.replacement_rules, w)
re_.add_rule()
re_.name_edit.setText("Pt. → Part")
re_.find_edit.setText(r"\bPt\.")
re_.regex_box.setChecked(True)
re_.replace_edit.setText("Part")
re_.test_edit.setText("Kill Bill Pt. 2")
re_.show()
save(re_, "19_regeleditor")
re_.find_edit.setText("(")
save(re_, "20_regeleditor_fout")
re_.close()
rs = RuleSettingsDialog(cfg, "roman", w)
rs.show()
save(rs, "21_instellingen_romeins")
rs.close()
fs = RuleSettingsDialog(cfg, "feat", w)
fs.show()
save(fs, "22_instellingen_featuring")
fs.close()

# 12. Over
about = AboutDialog(w)
about.show()
save(about, "23_over")
about.close()

# 13. Donker thema
app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
m.set_field([ids["queen - bohemian rhapsody.mp3"]], Field.YEAR, 1975)
m.set_field([ids["track 07.mp3"]], Field.ARTIST, "AC/DC")
m.set_field([ids["track 07.mp3"]], Field.TITLE, "Thunderstruck")
m.resort()
w.table.clearSelection()
w.table.scrollToTop()
pump(0.5)
save(w, "24_donker_thema")
m.edits.clear()
w.close()
print("klaar")
