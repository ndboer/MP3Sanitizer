"""Opslaan-preview: hernoemen/verplaatsen met opties, via het gedeelde preview-dialoog."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mp3sanitizer.core.models import Collision, PlanWarning, RenamePlan
from mp3sanitizer.core.planner import (
    DecadeStyle,
    FolderTemplate,
    PlanInput,
    PlanOptions,
    plan_renames,
)
from mp3sanitizer.core.settings import Settings
from mp3sanitizer.core.validate import (
    YearError,
    invalid_chars,
    parse_year_input,
    sanitize_text,
    text_issues,
)
from mp3sanitizer.ui.preview_dialog import Level, PreviewDialog, PreviewItem
from mp3sanitizer.ui.track_model import ERROR_COLOR

_TEMPLATES = [
    (FolderTemplate.NONE, "Niet verplaatsen"),
    (FolderTemplate.YEAR, "Jaarmap (1985\\)"),
    (FolderTemplate.DECADE, "Decenniummap"),
]
_STYLES = [(DecadeStyle.RANGE, "1980-1989\\"), (DecadeStyle.SHORT, "80s\\")]
_COLLISIONS = [
    (Collision.SKIP, "Overslaan"),
    (Collision.SUFFIX, 'Suffix " (2)" toevoegen'),
    (Collision.MARK_DUPLICATE, "Als duplicaat markeren"),
]
_INFO_WARNINGS = {PlanWarning.CASE_ONLY, PlanWarning.TAGS_ONLY}


def relative(path: Path, root: Path) -> str:
    text, base = os.fspath(path), os.fspath(root).rstrip("\\/") + os.sep
    return text[len(base) :] if text.startswith(base) else text


def plan_to_item(plan: RenamePlan, root: Path) -> PreviewItem:
    if plan.blocked:
        level = Level.ERROR
    elif set(plan.warnings) - _INFO_WARNINGS:
        level = Level.WARNING
    elif plan.warnings:
        level = Level.INFO
    else:
        level = Level.OK
    old = relative(plan.src, root)
    new = relative(plan.dst, root) if plan.renames else old
    label = "Pad" if plan.renames else "Tags"
    return PreviewItem(
        key=plan.track_id,
        label=label,
        old=old,
        new=new,
        note=plan.note,
        level=level,
        checkable=not plan.blocked,
        checked=not plan.blocked,
    )


class SaveFixer(Protocol):
    """Wat de opslaan-preview nodig heeft om niet-opslaanbare tracks te herstellen."""

    def plan_inputs(self) -> list[PlanInput]: ...

    def set_track_values(
        self, track_id: int, artist: str, title: str, year: int | None, text: str
    ) -> bool: ...

    def delete_tracks_now(self, track_ids: list[int], parent: QWidget) -> bool: ...


class TrackEditDialog(QDialog):
    """Artiest, titel en jaar van één track aanpassen, met directe controle op geldigheid."""

    def __init__(
        self, artist: str, title: str, year: int | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Track aanpassen")
        self.resize(560, 0)
        self.artist_edit = QLineEdit(artist, self)
        self.title_edit = QLineEdit(title, self)
        self.year_edit = QLineEdit("" if year is None else str(year), self)
        self.year_edit.setMaximumWidth(80)
        self.fix_button = QPushButton("Ongeldige tekens &vervangen", self)
        self.fix_button.clicked.connect(self.sanitize)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuleren")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("&Artiest:", self.artist_edit)
        form.addRow("&Titel:", self.title_edit)
        form.addRow("&Jaar:", self.year_edit)
        row = QHBoxLayout()
        row.addWidget(self.fix_button)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(row)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        for edit in (self.artist_edit, self.title_edit, self.year_edit):
            edit.textChanged.connect(self.validate)
        self.validate()

    def sanitize(self) -> None:
        for edit in (self.artist_edit, self.title_edit):
            edit.setText(sanitize_text(edit.text()))

    def problems(self) -> list[str]:
        problems = []
        for name, edit in (("Artiest", self.artist_edit), ("Titel", self.title_edit)):
            problems += [f"{name}: {issue.message.lower()}" for issue in text_issues(edit.text())]
        try:
            parse_year_input(self.year_edit.text())
        except YearError as exc:
            problems.append(f"Jaar: {exc}")
        return problems

    def validate(self) -> None:
        problems = self.problems()
        self.status.setStyleSheet(f"color: {ERROR_COLOR.name()}" if problems else "")
        self.status.setText("\n".join(problems) or "De naam is geldig.")
        self.fix_button.setEnabled(
            any(invalid_chars(e.text()) for e in (self.artist_edit, self.title_edit))
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not problems)

    def values(self) -> tuple[str, str, int | None]:
        return (
            " ".join(self.artist_edit.text().split()),
            " ".join(self.title_edit.text().split()),
            parse_year_input(self.year_edit.text()),
        )


class SavePreviewDialog(PreviewDialog):
    def __init__(
        self,
        inputs: Sequence[PlanInput],
        root: Path,
        settings: Settings,
        parent: QWidget | None = None,
        exists: Callable[[Path], bool] = os.path.exists,
        fixer: SaveFixer | None = None,
        move_only: bool = False,
    ) -> None:
        super().__init__(
            "Opslaan: hernoemen en verplaatsen",
            "Controleer de wijzigingen. Alleen aangevinkte regels worden uitgevoerd. Bestaande "
            "bestanden worden nooit overschreven; na afloop kun je de batch terugdraaien via "
            "Bestand → Laatste batch terugdraaien.",
            parent,
            accept_text="Opslaan",
        )
        self._inputs = list(inputs)
        self._root = root
        self._exists = exists
        self._fixer = fixer
        self.plans: dict[int, RenamePlan] = {}

        self.template_combo = QComboBox(self)
        for value, label in _TEMPLATES:
            self.template_combo.addItem(label, value.value)
        self.style_combo = QComboBox(self)
        for value, label in _STYLES:
            self.style_combo.addItem(label, value.value)
        self.unknown_edit = QLineEdit(settings.unknown_year_folder, self)
        self.unknown_edit.setMaximumWidth(160)
        self.collision_combo = QComboBox(self)
        for value, label in _COLLISIONS:
            self.collision_combo.addItem(label, value.value)
        self.include_unchanged = QCheckBox(
            "Ook niet-bewerkte tracks meenemen (naam normaliseren / naar de juiste map)", self
        )
        self.write_tags = QCheckBox("Tags bijwerken (artiest, titel, jaar)", self)
        self.cleanup = QCheckBox("Lege mappen opruimen na verplaatsen", self)
        self.keep_names = QCheckBox(
            "Bestandsnamen van niet-bewerkte tracks ongewijzigd laten (alleen verplaatsen)", self
        )

        self._select(self.template_combo, settings.folder_template)
        self._select(self.style_combo, settings.decade_style)
        self._select(self.collision_combo, settings.collision_policy)
        self.write_tags.setChecked(settings.write_tags)
        self.cleanup.setChecked(settings.cleanup_empty_dirs)
        if move_only:  # menu 'Verplaatsen naar jaarmap'
            self.setWindowTitle("Verplaatsen naar jaarmap")
            if settings.folder_template == FolderTemplate.NONE.value:
                self._select(self.template_combo, FolderTemplate.YEAR.value)
            self.include_unchanged.setChecked(True)
            self.keep_names.setChecked(True)
            self.write_tags.setChecked(False)

        folder_row = QHBoxLayout()
        folder_row.addWidget(self.template_combo)
        folder_row.addWidget(self.style_combo)
        folder_row.addWidget(QLabel("Zonder jaar naar:", self))
        folder_row.addWidget(self.unknown_edit)
        folder_row.addStretch(1)
        form = QFormLayout()
        form.addRow(QLabel("&Doelmap:", self, buddy=self.template_combo), folder_row)
        form.addRow("&Bij botsing:", self.collision_combo)
        form.addRow("", self.include_unchanged)
        form.addRow("", self.keep_names)
        form.addRow("", self.write_tags)
        form.addRow("", self.cleanup)
        self.options_layout.addLayout(form)

        # Herstellen van tracks die niet opgeslagen kunnen worden (ongeldig of botsing).
        self.fix_label = QLabel(self)
        self.edit_button = QPushButton("&Aanpassen…", self)
        self.edit_button.setToolTip("Artiest, titel en jaar van de geselecteerde track aanpassen")
        self.edit_button.clicked.connect(self.edit_selected)
        self.sanitize_button = QPushButton("Ongeldige &tekens vervangen", self)
        self.sanitize_button.setToolTip('Bijv. "AC/DC" wordt "AC-DC", "Deel: 2" wordt "Deel - 2"')
        self.sanitize_button.clicked.connect(self.sanitize_selected)
        self.delete_button = QPushButton("&Verwijderen (duplicaat)…", self)
        self.delete_button.setToolTip(
            "Het bronbestand verwijderen, bijvoorbeeld als het doelbestand al bestaat (duplicaat)"
        )
        self.delete_button.clicked.connect(self.delete_selected)
        self._fix_widgets = (
            self.fix_label,
            self.edit_button,
            self.sanitize_button,
            self.delete_button,
        )
        if fixer is not None:
            fix_row = QHBoxLayout()
            for widget in self._fix_widgets:
                fix_row.addWidget(widget)
            fix_row.addStretch(1)
            self.options_layout.addLayout(fix_row)
            self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.table.customContextMenuRequested.connect(self._context_menu)
            self.table.selectionModel().selectionChanged.connect(self._update_fix_buttons)
            self.table.selectionModel().currentChanged.connect(self._update_fix_buttons)
        else:
            for widget in self._fix_widgets:
                widget.hide()

        for combo in (self.template_combo, self.style_combo, self.collision_combo):
            combo.currentIndexChanged.connect(self.replan)
        for box in (self.include_unchanged, self.write_tags, self.keep_names):
            box.toggled.connect(self.replan)
        self.unknown_edit.editingFinished.connect(self.replan)
        self.replan()

    @staticmethod
    def _select(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(max(index, 0))

    def options(self) -> PlanOptions:
        return PlanOptions(
            root=self._root,
            folder_template=FolderTemplate(self.template_combo.currentData()),
            decade_style=DecadeStyle(self.style_combo.currentData()),
            unknown_folder=self.unknown_edit.text().strip() or "_Onbekend",
            collision=Collision(self.collision_combo.currentData()),
            write_tags=self.write_tags.isChecked(),
            include_unchanged=self.include_unchanged.isChecked(),
            keep_names=self.keep_names.isChecked(),
        )

    def replan(self) -> None:
        opts = self.options()
        self.style_combo.setEnabled(opts.folder_template is FolderTemplate.DECADE)
        self.unknown_edit.setEnabled(opts.folder_template is not FolderTemplate.NONE)
        plans = plan_renames(self._inputs, opts, self._exists)
        self.plans = {p.track_id: p for p in plans}
        self.set_items(plan_to_item(p, self._root) for p in plans)
        if hasattr(self, "_fix_widgets"):  # replan draait al tijdens __init__
            self._update_fix_buttons()

    # --- herstellen ----------------------------------------------------------------------
    def _selected_ids(self) -> list[int]:
        return [k for k in self.selected_keys() if isinstance(k, int) and k in self.plans]

    def _inputs_by_id(self) -> dict[int, PlanInput]:
        return {i.track_id: i for i in self._inputs}

    def _update_fix_buttons(self, *_args: object) -> None:
        blocked = sum(1 for p in self.plans.values() if p.blocked)
        self.fix_label.setText(
            f"{blocked} niet op te slaan. Geselecteerde track:"
            if blocked
            else "Geselecteerde track:"
        )
        ids = self._selected_ids()
        inputs = self._inputs_by_id()
        self.edit_button.setEnabled(len(ids) == 1)
        self.sanitize_button.setEnabled(
            any(invalid_chars(inputs[i].artist + inputs[i].title) for i in ids if i in inputs)
        )
        self.delete_button.setEnabled(bool(ids))

    def _refresh(self) -> None:
        assert self._fixer is not None
        self._inputs = list(self._fixer.plan_inputs())
        self.replan()

    def edit_selected(self) -> None:
        ids = self._selected_ids()
        inp = self._inputs_by_id().get(ids[0]) if len(ids) == 1 else None
        if inp is None or self._fixer is None:
            return
        dialog = TrackEditDialog(inp.artist, inp.title, inp.year, self)
        if not dialog.exec():
            return
        artist, title, year = dialog.values()
        if self._fixer.set_track_values(inp.track_id, artist, title, year, "Track aanpassen"):
            self._refresh()

    def sanitize_selected(self) -> None:
        if self._fixer is None:
            return
        inputs, changed = self._inputs_by_id(), False
        for tid in self._selected_ids():
            inp = inputs.get(tid)
            if inp is None:
                continue
            artist, title = sanitize_text(inp.artist), sanitize_text(inp.title)
            if (artist, title) != (inp.artist, inp.title):
                changed |= self._fixer.set_track_values(
                    tid, artist, title, inp.year, "Ongeldige tekens vervangen"
                )
        if changed:
            self._refresh()

    def delete_selected(self) -> None:
        ids = self._selected_ids()
        if ids and self._fixer is not None and self._fixer.delete_tracks_now(ids, self):
            self._refresh()

    def _context_menu(self, pos) -> None:
        if not self.table.indexAt(pos).isValid():
            return
        menu = QMenu(self)
        for button in (self.edit_button, self.sanitize_button, self.delete_button):
            action = menu.addAction(button.text().replace("&", ""))
            action.setEnabled(button.isEnabled())
            action.triggered.connect(button.click)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def summary_text(self) -> str:
        known = getattr(self, "plans", {})  # wordt al vanuit PreviewDialog.__init__ aangeroepen
        plans = [known[k] for k in self.checked_keys() if k in known]
        moves = sum(1 for p in plans if p.renames and p.src.parent != p.dst.parent)
        return f"{moves} verplaatsen" if moves else ""

    def selected_plans(self) -> list[RenamePlan]:
        return [self.plans[k] for k in self.checked_keys()]  # type: ignore[index]

    def duplicate_ids(self) -> list[int]:
        """Tracks die bij een botsing als duplicaat gemarkeerd moeten worden."""
        return [p.track_id for p in self.plans.values() if p.collision is Collision.MARK_DUPLICATE]

    def store_settings(self, settings: Settings) -> None:
        opts = self.options()
        settings.folder_template = opts.folder_template.value
        settings.decade_style = opts.decade_style.value
        settings.unknown_year_folder = opts.unknown_folder
        settings.collision_policy = opts.collision.value
        settings.write_tags = opts.write_tags
        settings.cleanup_empty_dirs = self.cleanup.isChecked()
