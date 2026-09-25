"""Batch-correcties: dialoog, preview, één undo-stap, profielen en de regeleditor."""

import time
from pathlib import Path
from typing import ClassVar

import pytest
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog

from mp3sanitizer.core.models import AudioInfo, Field
from mp3sanitizer.core.rules.config import RulesConfig
from mp3sanitizer.core.rules.replace import ReplacementRule
from mp3sanitizer.core.scanner import track_from_path
from mp3sanitizer.ui.corrections_dialog import (
    RULE_ID_ROLE,
    CorrectionsDialog,
    RuleSettingsDialog,
    Scope,
)
from mp3sanitizer.ui.rule_editor import RuleEditorDialog
from mp3sanitizer.ui.track_model import TrackTableModel

NAMES = [
    "eminem - stan (featuring dido) (2000).mp3",
    "bruce springsteen - born in the u.s.a (1984).mp3",
    "Queen - Innuendo (1991).mp3",
    "Survivor - Rocky Iv Theme.mp3",
]


def wait_for(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not cond() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    QApplication.processEvents()
    assert cond()


class FakePreview:
    """Vervangt PreviewDialog: vinkt eventueel sleutels uit en accepteert."""

    uncheck: ClassVar[set] = set()
    last: "FakePreview | None" = None

    def __init__(self, title, description, parent=None, accept_text=""):
        self.items = []
        FakePreview.last = self

    def set_items(self, items):
        self.items = list(items)

    def checked_keys(self):
        return [i.key for i in self.items if i.key not in FakePreview.uncheck]

    def exec(self):
        return QDialog.DialogCode.Accepted


@pytest.fixture
def model(qapp, tmp_path: Path):
    m = TrackTableModel()
    m.undo_stack = QUndoStack()
    m.append_tracks([track_from_path(i, tmp_path / n, tmp_path) for i, n in enumerate(NAMES)])
    m.set_infos([(3, AudioInfo(tag_year=1985))])
    return m


@pytest.fixture
def pool():
    p = QThreadPool()
    yield p
    p.waitForDone(5000)


def _dialog(model, pool, config=None, scopes=None, selected=None):
    FakePreview.uncheck = set()
    config = config or RulesConfig()
    if selected is not None:
        config.last_selection = selected
    scopes = scopes or {Scope.ALL: [0, 1, 2, 3], Scope.FILTER: [0, 1, 2, 3], Scope.SELECTION: []}
    return CorrectionsDialog(model, config, scopes, pool, ["The"], preview_factory=FakePreview)


def _apply(d):
    d.preview_and_apply()
    wait_for(lambda: d.preview_button.isEnabled())


def test_default_profile_changes(model, pool):
    d = _dialog(model, pool)
    assert set(d.selected_rule_ids()) == {"spacing", "replace", "feat", "abbrev", "roman"}
    changes = d.compute()
    got = {(c.track_id, c.field): c.new for c in changes}
    assert got[(0, Field.TITLE)] == "stan (ft. dido)"
    assert got[(1, Field.TITLE)] == "born in the U.S.A."
    assert got[(3, Field.TITLE)] == "Rocky IV Theme"
    assert (2, Field.TITLE) not in got  # Queen voldoet al


def test_apply_is_one_undo_step_and_respects_unchecked(model, pool):
    config = RulesConfig(feat_move="artist")
    d = _dialog(model, pool, config, selected=["titlecase", "feat", "abbrev", "roman", "tagyear"])
    FakePreview.uncheck = set()
    _apply(d)
    items = {i.key: i for i in FakePreview.last.items}
    assert items[(0, "artist")].new == "Eminem ft. Dido"
    assert items[(0, "title")].new == "Stan"
    assert items[(3, "year")].new == "1985"  # jaar uit tag
    assert model.undo_stack.count() == 1
    assert model.edits.artist(0) == "Eminem ft. Dido"
    assert model.edits.year(3) == 1985
    model.undo_stack.undo()
    assert model.edits.artist(0) == "eminem"
    assert model.changed_count() == 0

    # opnieuw, maar het jaar uitgevinkt
    FakePreview.uncheck = {(3, "year")}
    _apply(d)
    assert model.edits.year(3) is None
    assert model.edits.title(1) == "Born in the U.S.A."


def test_no_changes_message(model, pool):
    d = _dialog(model, pool, selected=["spacing"])
    d.scopes = {Scope.ALL: [2]}
    d.scope_buttons[Scope.ALL].setChecked(True)
    _apply(d)
    assert "Geen wijzigingen" in d.status.text()
    assert model.undo_stack.count() == 0


def test_scope_selection_only(model, pool):
    scopes = {Scope.ALL: [0, 1, 2, 3], Scope.FILTER: [0, 1, 2, 3], Scope.SELECTION: [1, 3]}
    d = _dialog(model, pool, scopes=scopes)
    assert d.current_scope() is Scope.SELECTION  # meer dan één rij geselecteerd
    assert {c.track_id for c in d.compute()} == {1, 3}


def test_profiles(model, pool, monkeypatch):
    config = RulesConfig()
    d = _dialog(model, pool, config)
    d.set_selected_rule_ids(["titlecase"])
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *a, **k: ("Hoofdletters", True))
    )
    d.save_profile()
    assert config.profiles["Hoofdletters"] == ["titlecase"]
    d.set_selected_rule_ids(["spacing"])
    d.profile_combo.setCurrentText("Hoofdletters")
    d.load_profile()
    assert d.selected_rule_ids() == ["titlecase"]
    d.delete_profile()
    assert "Hoofdletters" not in config.profiles
    d.done(0)
    assert config.last_selection == ["titlecase"]


def test_rule_settings_dialog(qapp):
    config = RulesConfig()
    s = RuleSettingsDialog(config, "abbrev")
    s.abbrevs.setPlainText("NASA\n  \nFBI")
    s.exceptions.setPlainText("u.s.a")
    s.accept()
    assert config.abbreviations == ["NASA", "FBI"]
    assert config.abbreviation_exceptions == ["u.s.a"]
    r = RuleSettingsDialog(config, "roman")
    r.max_spin.setValue(0)
    r.accept()
    assert config.roman_max == 0
    f = RuleSettingsDialog(config, "feat")
    f.move_combo.setCurrentIndex(f.move_combo.findData("title"))
    f.accept()
    assert config.feat_move == "title"


# --- regeleditor --------------------------------------------------------------------------


def test_rule_editor_add_validate_and_test(qapp):
    editor = RuleEditorDialog(RulesConfig().replacement_rules)
    n = len(editor.rules)
    editor.add_rule()
    assert len(editor.rules) == n + 1
    editor.find_edit.setText("(")
    editor.regex_box.setChecked(True)
    assert "Ongeldige regex" in editor.error_label.text()
    editor.find_edit.setText(r"(\w+), The")
    editor.replace_edit.setText(r"The \1")
    assert editor.error_label.text() == ""
    editor.test_edit.setText("Beatles, The")
    assert editor.test_result.text() == "The Beatles"
    new_rule = editor.current_rule()
    assert new_rule.regex and new_rule.find == r"(\w+), The"


def test_rule_editor_builtins_and_order(qapp):
    editor = RuleEditorDialog(RulesConfig().replacement_rules)
    editor.list.setCurrentItem(editor.list.topLevelItem(0))
    assert editor.current_rule().builtin
    assert not editor.delete_button.isEnabled()
    assert not editor.find_edit.isEnabled()  # standaardregel: alleen aan/uit
    editor.active_box.setChecked(False)
    assert editor.rules[0].active is False
    first = editor.rules[0]
    editor.move(1)
    assert editor.rules[1] is first
    assert editor.current_rule() is first
    # het origineel is niet aangepast (editor werkt op een kopie)
    original = RulesConfig().replacement_rules
    assert original[0].active is True


def test_rule_editor_checkbox_in_list(qapp):
    editor = RuleEditorDialog([ReplacementRule("a", "b", name="x")])
    item = editor.list.topLevelItem(0)
    item.setCheckState(0, Qt.CheckState.Unchecked)
    assert editor.rules[0].active is False
    assert not editor.active_box.isChecked()


def test_rule_editor_export_import(qapp, tmp_path, monkeypatch):
    path = tmp_path / "regels.json"
    editor = RuleEditorDialog([ReplacementRule("Pt.", "Part", name="deel")])
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(path), ""))
    )
    editor.export_file()
    other = RuleEditorDialog([])
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), ""))
    )
    other.import_file()
    assert [r.find for r in other.rules] == ["Pt."]


def test_rule_ids_in_list_follow_rule_order(model, pool):
    d = _dialog(model, pool)
    ids = [d.rule_list.item(i).data(RULE_ID_ROLE) for i in range(d.rule_list.count())]
    assert ids[0] == "spacing" and ids[-1] == "tagyear"
