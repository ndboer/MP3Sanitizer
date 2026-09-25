"""Opslaan-preview: hernoemen/verplaatsen met opties, via het gedeelde preview-dialoog."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from mp3sanitizer.ui.preview_dialog import Level, PreviewDialog, PreviewItem

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


class SavePreviewDialog(PreviewDialog):
    def __init__(
        self,
        inputs: Sequence[PlanInput],
        root: Path,
        settings: Settings,
        parent: QWidget | None = None,
        exists: Callable[[Path], bool] = os.path.exists,
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

        self._select(self.template_combo, settings.folder_template)
        self._select(self.style_combo, settings.decade_style)
        self._select(self.collision_combo, settings.collision_policy)
        self.write_tags.setChecked(settings.write_tags)
        self.cleanup.setChecked(settings.cleanup_empty_dirs)

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
        form.addRow("", self.write_tags)
        form.addRow("", self.cleanup)
        self.options_layout.addLayout(form)

        for combo in (self.template_combo, self.style_combo, self.collision_combo):
            combo.currentIndexChanged.connect(self.replan)
        for box in (self.include_unchanged, self.write_tags):
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
        )

    def replan(self) -> None:
        opts = self.options()
        self.style_combo.setEnabled(opts.folder_template is FolderTemplate.DECADE)
        self.unknown_edit.setEnabled(opts.folder_template is not FolderTemplate.NONE)
        plans = plan_renames(self._inputs, opts, self._exists)
        self.plans = {p.track_id: p for p in plans}
        self.set_items(plan_to_item(p, self._root) for p in plans)

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
