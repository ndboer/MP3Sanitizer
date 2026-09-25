"""Batch-correcties (sectie 9): regels kiezen (opschoonprofiel), scope, preview en toepassen.

Het resultaat komt als één ``QUndoCommand`` in de tabel (niet-opgeslagen wijzigingen) en wordt
daarna via Opslaan (sectie 8) weggeschreven.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mp3sanitizer.core.models import PendingChange
from mp3sanitizer.core.rules.base import compute_corrections
from mp3sanitizer.core.rules.casing import ArticlePosition
from mp3sanitizer.core.rules.config import RULE_LABELS, RULE_ORDER, RulesConfig
from mp3sanitizer.core.rules.feat import FeatMove, FeatTarget
from mp3sanitizer.ui.preview_dialog import Level, PreviewDialog, PreviewItem
from mp3sanitizer.ui.rule_editor import RuleEditorDialog
from mp3sanitizer.ui.track_model import FIELD_LABEL, TrackTableModel, format_value
from mp3sanitizer.ui.workers import FunctionWorker, JobRunner

RULE_ID_ROLE = Qt.ItemDataRole.UserRole + 50
_HAS_SETTINGS = {"replace", "abbrev", "feat", "roman", "titlecase", "article"}


class Scope(StrEnum):
    ALL = "all"
    FILTER = "filter"
    SELECTION = "selection"


def _check_state(checked: bool) -> Qt.CheckState:
    return Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked


def _lines(widget: QPlainTextEdit) -> list[str]:
    return [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]


def _list_edit(values: Sequence[str], parent: QWidget) -> QPlainTextEdit:
    edit = QPlainTextEdit("\n".join(values), parent)
    edit.setTabChangesFocus(True)
    edit.setMinimumHeight(110)
    return edit


class RuleSettingsDialog(QDialog):
    """Instellingen van één regel (lijsten één item per regel)."""

    def __init__(self, config: RulesConfig, rule_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Instellingen: {RULE_LABELS[rule_id]}")
        self.config = config
        self.rule_id = rule_id
        form = QFormLayout()
        c = config
        if rule_id == "abbrev":
            self.abbrevs = _list_edit(c.abbreviations, self)
            self.exceptions = _list_edit(c.abbreviation_exceptions, self)
            form.addRow("&Vaste afkortingen\n(één per regel):", self.abbrevs)
            form.addRow("&Uitzonderingen:", self.exceptions)
        elif rule_id == "feat":
            self.target = QComboBox(self)
            for t in FeatTarget:
                self.target.addItem(t.value, t.value)
            self.target.setCurrentIndex(self.target.findData(c.feat_target))
            self.move_combo = QComboBox(self)
            for value, label in (
                (FeatMove.NONE, "Niet verplaatsen"),
                (FeatMove.TO_ARTIST, "Naar de artiest"),
                (FeatMove.TO_TITLE, "Naar de titel"),
            ):
                self.move_combo.addItem(label, value.value)
            self.move_combo.setCurrentIndex(self.move_combo.findData(c.feat_move))
            form.addRow("&Notatie:", self.target)
            form.addRow("&Verplaatsen:", self.move_combo)
        elif rule_id == "roman":
            self.max_spin = QSpinBox(self)
            self.max_spin.setRange(0, 3999)
            self.max_spin.setValue(c.roman_max)
            self.max_spin.setSpecialValueText("uit")
            self.at_end = QCheckBox("Ook aan het &eind van de titel", self)
            self.at_end.setChecked(c.roman_at_end)
            self.context = _list_edit(c.roman_context, self)
            self.exceptions = _list_edit(c.roman_exceptions, self)
            form.addRow("Altijd t/m &waarde:", self.max_spin)
            form.addRow("", self.at_end)
            form.addRow("Na deze &woorden:", self.context)
            form.addRow("&Uitzonderingen:", self.exceptions)
        elif rule_id == "titlecase":
            self.small = _list_edit(c.small_words, self)
            form.addRow("&Kleine woorden\n(niet aan het begin):", self.small)
        elif rule_id == "article":
            self.position = QComboBox(self)
            self.position.addItem("The Artiest (vooraan)", ArticlePosition.FRONT.value)
            self.position.addItem("Artiest, The (achteraan)", ArticlePosition.BACK.value)
            self.position.setCurrentIndex(self.position.findData(c.article_position))
            form.addRow("&Schrijfwijze:", self.position)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuleren")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def accept(self) -> None:
        c = self.config
        match self.rule_id:
            case "abbrev":
                c.abbreviations = _lines(self.abbrevs)
                c.abbreviation_exceptions = _lines(self.exceptions)
            case "feat":
                c.feat_target = self.target.currentData()
                c.feat_move = self.move_combo.currentData()
            case "roman":
                c.roman_max = self.max_spin.value()
                c.roman_at_end = self.at_end.isChecked()
                c.roman_context = _lines(self.context)
                c.roman_exceptions = _lines(self.exceptions)
            case "titlecase":
                c.small_words = _lines(self.small)
            case "article":
                c.article_position = self.position.currentData()
        super().accept()


def change_to_item(change: PendingChange, label: str) -> PreviewItem:
    return PreviewItem(
        key=(change.track_id, change.field.value),
        label=FIELD_LABEL[change.field],
        old=format_value(change.old),
        new=format_value(change.new),
        note=label,
        level=Level.OK,
    )


class CorrectionsDialog(QDialog):
    """Kies regels en scope; ``preview_and_apply`` toont de preview en past het resultaat toe."""

    def __init__(
        self,
        model: TrackTableModel,
        config: RulesConfig,
        scopes: Mapping[Scope, Sequence[int]],
        pool: QThreadPool,
        articles: Sequence[str],
        parent: QWidget | None = None,
        preview_factory: Callable[..., PreviewDialog] = PreviewDialog,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Batch-correcties")
        self.resize(640, 520)
        self.model = model
        self.config = config
        self.scopes = scopes
        self._articles = list(articles)
        self._jobs = JobRunner(pool, self)
        self._preview_factory = preview_factory
        self.applied = 0

        self.rule_list = QListWidget(self)
        for rid in RULE_ORDER:
            item = QListWidgetItem(RULE_LABELS[rid], self.rule_list)
            item.setData(RULE_ID_ROLE, rid)
            item.setCheckState(_check_state(rid in config.last_selection))
        self.rule_list.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.rule_list.itemDoubleClicked.connect(lambda *_: self.edit_settings())
        self.settings_button = QPushButton("&Instellingen…", self)
        self.settings_button.clicked.connect(self.edit_settings)

        self.profile_combo = QComboBox(self)
        self.profile_combo.setMinimumWidth(220)
        self._fill_profiles()
        self.load_profile_button = QPushButton("&Laden", self)
        self.load_profile_button.clicked.connect(self.load_profile)
        self.save_profile_button = QPushButton("Opslaan &als…", self)
        self.save_profile_button.clicked.connect(self.save_profile)
        self.delete_profile_button = QPushButton("&Verwijderen", self)
        self.delete_profile_button.clicked.connect(self.delete_profile)

        scope_box = QGroupBox("Toepassen op", self)
        self.scope_group = QButtonGroup(self)
        scope_layout = QVBoxLayout(scope_box)
        labels = {
            Scope.ALL: "&Hele collectie",
            Scope.FILTER: "Huidige &filter",
            Scope.SELECTION: "&Geselecteerde rijen",
        }
        self.scope_buttons: dict[Scope, QRadioButton] = {}
        for scope in Scope:
            n = len(scopes.get(scope, ()))
            button = QRadioButton(f"{labels[scope]} ({n})", scope_box)
            button.setEnabled(n > 0)
            self.scope_group.addButton(button)
            scope_layout.addWidget(button)
            self.scope_buttons[scope] = button
        # Standaard: de selectie als er meer dan één rij is geselecteerd, anders de filter.
        default = Scope.SELECTION if len(scopes.get(Scope.SELECTION, ())) > 1 else Scope.FILTER
        self.scope_buttons[default if scopes.get(default) else Scope.ALL].setChecked(True)

        self.status = QLabel(self)
        self.preview_button = QPushButton("&Preview…", self)
        self.preview_button.setDefault(True)
        self.preview_button.clicked.connect(self.preview_and_apply)
        close_button = QPushButton("Sluiten", self)
        close_button.clicked.connect(self.reject)

        rules_row = QHBoxLayout()
        rules_row.addWidget(self.rule_list, 1)
        side = QVBoxLayout()
        side.addWidget(self.settings_button)
        side.addStretch(1)
        rules_row.addLayout(side)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("P&rofiel:", self, buddy=self.profile_combo))
        profile_row.addWidget(self.profile_combo, 1)
        profile_row.addWidget(self.load_profile_button)
        profile_row.addWidget(self.save_profile_button)
        profile_row.addWidget(self.delete_profile_button)
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.preview_button)
        bottom.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Kies de regels (ze worden in deze volgorde toegepast):", self))
        layout.addLayout(rules_row, 1)
        layout.addLayout(profile_row)
        layout.addWidget(scope_box)
        layout.addLayout(bottom)
        self.rule_list.setCurrentRow(0)
        self._update_buttons()
        self.rule_list.setFocus()

    # --- regels en profielen -------------------------------------------------------------
    def selected_rule_ids(self) -> list[str]:
        return [
            self.rule_list.item(i).data(RULE_ID_ROLE)
            for i in range(self.rule_list.count())
            if self.rule_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def set_selected_rule_ids(self, ids: Sequence[str]) -> None:
        wanted = set(ids)
        for i in range(self.rule_list.count()):
            item = self.rule_list.item(i)
            item.setCheckState(_check_state(item.data(RULE_ID_ROLE) in wanted))

    def _update_buttons(self) -> None:
        item = self.rule_list.currentItem()
        self.settings_button.setEnabled(
            item is not None and item.data(RULE_ID_ROLE) in _HAS_SETTINGS
        )
        has_profile = self.profile_combo.count() > 0
        self.load_profile_button.setEnabled(has_profile)
        self.delete_profile_button.setEnabled(has_profile)

    def edit_settings(self) -> None:
        item = self.rule_list.currentItem()
        if item is None:
            return
        rid = item.data(RULE_ID_ROLE)
        if rid == "replace":
            editor = RuleEditorDialog(self.config.replacement_rules, self)
            if editor.exec():
                self.config.replacement_rules = editor.rules
        elif rid in _HAS_SETTINGS:
            RuleSettingsDialog(self.config, rid, self).exec()

    def _fill_profiles(self, select: str | None = None) -> None:
        self.profile_combo.clear()
        for name in sorted(self.config.profiles, key=str.casefold):
            self.profile_combo.addItem(name)
        if select is not None:
            self.profile_combo.setCurrentText(select)

    def load_profile(self) -> None:
        name = self.profile_combo.currentText()
        if name in self.config.profiles:
            self.set_selected_rule_ids(self.config.profiles[name])

    def save_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "Profiel opslaan",
            "Naam van het opschoonprofiel:",
            text=self.profile_combo.currentText(),
        )
        name = name.strip()
        if ok and name:
            self.config.profiles[name] = self.selected_rule_ids()
            self._fill_profiles(select=name)
            self._update_buttons()

    def delete_profile(self) -> None:
        name = self.profile_combo.currentText()
        if name in self.config.profiles:
            del self.config.profiles[name]
            self._fill_profiles()
            self._update_buttons()

    # --- preview en toepassen ------------------------------------------------------------
    def current_scope(self) -> Scope:
        for scope, button in self.scope_buttons.items():
            if button.isChecked():
                return scope
        return Scope.ALL

    def compute(self) -> list[PendingChange]:
        """Synchrone variant (tests); de knop gebruikt een achtergrondtaak."""
        return self._compute(self.selected_rule_ids(), self.current_scope())

    def _compute(self, rule_ids: list[str], scope: Scope) -> list[PendingChange]:
        rules = self.config.build(rule_ids, self._articles)
        inputs = self.model.correction_inputs(self.scopes.get(scope, ()))
        return compute_corrections(inputs, rules, source="rule:" + ",".join(rule_ids))

    def preview_and_apply(self) -> None:
        rule_ids = self.selected_rule_ids()
        if not rule_ids:
            self.status.setText("Kies minstens één regel.")
            return
        self.config.last_selection = rule_ids
        self.status.setText("Berekenen…")
        self.preview_button.setEnabled(False)
        worker = FunctionWorker(self._compute, rule_ids, self.current_scope())
        self._jobs.run("compute", worker, self._show_preview)

    def _show_preview(self, result: object) -> None:
        self.preview_button.setEnabled(True)
        changes: list[PendingChange] = result  # type: ignore[assignment]
        if not changes:
            self.status.setText("Geen wijzigingen: alles voldoet al aan deze regels.")
            return
        self.status.setText("")
        tracks = len({c.track_id for c in changes})
        preview = self._preview_factory(
            "Batch-correctie: preview",
            f"{len(changes)} wijzigingen in {tracks} tracks. Alleen aangevinkte regels worden "
            "toegepast (als niet-opgeslagen wijziging; opslaan gaat daarna via Ctrl+S).",
            self,
            accept_text="Toepassen",
        )
        preview.set_items(change_to_item(c, self.model.track_label(c.track_id)) for c in changes)
        if not preview.exec():
            return
        keys = set(preview.checked_keys())
        chosen = [c for c in changes if (c.track_id, c.field.value) in keys]
        chosen = self._current(chosen)
        name = self.profile_combo.currentText() or "eigen selectie"
        if self.model.push_changes(chosen, f"Opschonen: {name} ({len(chosen)} wijzigingen)"):
            self.applied += len(chosen)
            self.status.setText(f"{len(chosen)} wijzigingen toegepast (Ctrl+Z maakt ze ongedaan).")

    def _current(self, changes: list[PendingChange]) -> list[PendingChange]:
        """Zet 'old' op de huidige waarde, voor het geval er intussen iets is gewijzigd."""
        e = self.model.edits
        return [
            PendingChange(c.track_id, c.field, e.value(c.track_id, c.field), c.new, c.source)
            for c in changes
            if e.value(c.track_id, c.field) != c.new
        ]

    def done(self, result: int) -> None:
        self._jobs.cancel_all()
        self.config.last_selection = self.selected_rule_ids()
        super().done(result)
