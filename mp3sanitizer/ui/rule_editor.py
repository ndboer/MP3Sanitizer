"""Editor voor eigen vervangingsregels (9c): lijst (slepen/omhoog/omlaag) + detailformulier."""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mp3sanitizer.core.models import Field
from mp3sanitizer.core.rules.config import export_rules, import_rules
from mp3sanitizer.core.rules.replace import ReplacementRule, RuleField
from mp3sanitizer.ui.track_model import ERROR_COLOR

RULE_ROLE = Qt.ItemDataRole.UserRole + 40
_FIELD_LABELS = {RuleField.BOTH: "Beide", RuleField.ARTIST: "Artiest", RuleField.TITLE: "Titel"}


def _yes(value: bool) -> str:
    return "✓" if value else ""


class RuleEditorDialog(QDialog):
    """Bewerkt een kopie van de regels; ``rules`` bevat het resultaat na OK."""

    def __init__(self, rules: list[ReplacementRule], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vervangingsregels")
        self.resize(980, 620)
        self.rules = [copy.copy(r) for r in rules]
        self._loading = False

        self.list = QTreeWidget(self)
        self.list.setRootIsDecorated(False)
        self.list.setHeaderLabels(
            ["Actief", "Naam", "Zoek", "Vervang", "Veld", "Heel woord", "Hoofdl.", "Regex"]
        )
        self.list.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.list.setColumnWidth(1, 200)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.model().rowsMoved.connect(self._sync_order_from_list)
        self.list.currentItemChanged.connect(lambda *_: self._load_current())
        self.list.itemChanged.connect(self._on_item_changed)

        self.new_button = QPushButton("&Nieuw", self)
        self.new_button.clicked.connect(self.add_rule)
        self.delete_button = QPushButton("&Verwijderen", self)
        self.delete_button.clicked.connect(self.delete_rule)
        self.up_button = QPushButton("Omh&oog", self)
        self.up_button.clicked.connect(lambda: self.move(-1))
        self.down_button = QPushButton("Oml&aag", self)
        self.down_button.clicked.connect(lambda: self.move(1))
        self.import_button = QPushButton("&Importeren…", self)
        self.import_button.clicked.connect(self.import_file)
        self.export_button = QPushButton("&Exporteren…", self)
        self.export_button.clicked.connect(self.export_file)

        # Detailformulier
        self.name_edit = QLineEdit(self)
        self.find_edit = QLineEdit(self)
        self.replace_edit = QLineEdit(self)
        self.field_combo = QComboBox(self)
        for value, label in _FIELD_LABELS.items():
            self.field_combo.addItem(label, value.value)
        self.active_box = QCheckBox("Actief", self)
        self.word_box = QCheckBox("Heel woord", self)
        self.case_box = QCheckBox("Hoofdlettergevoelig", self)
        self.regex_box = QCheckBox("Reguliere expressie (Python re)", self)
        self.error_label = QLabel(self)
        self.error_label.setStyleSheet(f"color: {ERROR_COLOR.name()}")
        self.test_edit = QLineEdit(self)
        self.test_edit.setPlaceholderText("Typ hier een voorbeeld om de regel uit te proberen")
        self.test_result = QLabel(self)
        self.test_result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        for w in (self.name_edit, self.find_edit, self.replace_edit, self.test_edit):
            w.textChanged.connect(self._on_form_changed)
        self.field_combo.currentIndexChanged.connect(self._on_form_changed)
        for box in (self.active_box, self.word_box, self.case_box, self.regex_box):
            box.toggled.connect(self._on_form_changed)

        form = QFormLayout()
        form.addRow("Naa&m:", self.name_edit)
        form.addRow("&Zoektekst:", self.find_edit)
        form.addRow("Vervang &door:", self.replace_edit)
        form.addRow("&Veld:", self.field_combo)
        boxes = QHBoxLayout()
        for box in (self.active_box, self.word_box, self.case_box, self.regex_box):
            boxes.addWidget(box)
        boxes.addStretch(1)
        form.addRow("", boxes)
        form.addRow("", self.error_label)
        form.addRow("&Test:", self.test_edit)
        form.addRow("Resultaat:", self.test_result)
        self.form_widget = QWidget(self)
        self.form_widget.setLayout(form)

        side = QVBoxLayout()
        for b in (self.new_button, self.delete_button, self.up_button, self.down_button):
            side.addWidget(b)
        side.addSpacing(12)
        side.addWidget(self.import_button)
        side.addWidget(self.export_button)
        side.addStretch(1)
        top = QHBoxLayout()
        top.addWidget(self.list, 1)
        top.addLayout(side)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuleren")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Regels worden van boven naar beneden toegepast (slepen of Omhoog/Omlaag).", self
            )
        )
        layout.addLayout(top, 1)
        layout.addWidget(self.form_widget)
        layout.addWidget(self.buttons)
        self._rebuild()

    # --- lijst ---------------------------------------------------------------------------
    def _rebuild(self, select: int = 0) -> None:
        self._loading = True
        self.list.clear()
        for rule in self.rules:
            item = QTreeWidgetItem()
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            item.setData(0, RULE_ROLE, rule)
            self._fill(item, rule)
            self.list.addTopLevelItem(item)
        self._loading = False
        if self.rules:
            self.list.setCurrentItem(
                self.list.topLevelItem(max(0, min(select, len(self.rules) - 1)))
            )
        self._load_current()

    def _fill(self, item: QTreeWidgetItem, rule: ReplacementRule) -> None:
        self._loading, was = True, self._loading
        item.setCheckState(0, Qt.CheckState.Checked if rule.active else Qt.CheckState.Unchecked)
        item.setText(1, rule.name + (" (standaard)" if rule.builtin else ""))
        item.setText(2, rule.find)
        item.setText(3, rule.replace)
        item.setText(4, _FIELD_LABELS[rule.field])
        item.setText(5, _yes(rule.whole_word))
        item.setText(6, _yes(rule.case_sensitive))
        item.setText(7, _yes(rule.regex))
        error = rule.error()
        item.setForeground(2, ERROR_COLOR if error else item.foreground(1))
        item.setToolTip(2, error or "")
        self._loading = was

    def current_rule(self) -> ReplacementRule | None:
        item = self.list.currentItem()
        return item.data(0, RULE_ROLE) if item else None

    def _sync_order_from_list(self, *_: object) -> None:
        self.rules = [
            self.list.topLevelItem(i).data(0, RULE_ROLE)
            for i in range(self.list.topLevelItemCount())
        ]

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._loading or column != 0:
            return
        rule: ReplacementRule = item.data(0, RULE_ROLE)
        rule.active = item.checkState(0) == Qt.CheckState.Checked
        if rule is self.current_rule():
            self._loading = True
            self.active_box.setChecked(rule.active)
            self._loading = False

    def add_rule(self) -> None:
        index = self.list.indexOfTopLevelItem(self.list.currentItem()) + 1
        self.rules.insert(index, ReplacementRule("", "", name="Nieuwe regel"))
        self._rebuild(index)
        self.find_edit.setFocus()

    def delete_rule(self) -> None:
        rule = self.current_rule()
        if rule is None or rule.builtin:
            return
        index = self.rules.index(rule)
        del self.rules[index]
        self._rebuild(index)

    def move(self, delta: int) -> None:
        rule = self.current_rule()
        if rule is None:
            return
        i = self.rules.index(rule)
        j = i + delta
        if 0 <= j < len(self.rules):
            self.rules[i], self.rules[j] = self.rules[j], self.rules[i]
            self._rebuild(j)

    # --- formulier -----------------------------------------------------------------------
    def _load_current(self) -> None:
        rule = self.current_rule()
        self.form_widget.setEnabled(rule is not None)
        self.delete_button.setEnabled(rule is not None and not rule.builtin)
        if rule is None:
            return
        self._loading = True
        self.name_edit.setText(rule.name)
        self.find_edit.setText(rule.find)
        self.replace_edit.setText(rule.replace)
        self.field_combo.setCurrentIndex(self.field_combo.findData(rule.field.value))
        self.active_box.setChecked(rule.active)
        self.word_box.setChecked(rule.whole_word)
        self.case_box.setChecked(rule.case_sensitive)
        self.regex_box.setChecked(rule.regex)
        # standaardregels: alleen aan/uit te zetten
        for w in (
            self.name_edit,
            self.find_edit,
            self.replace_edit,
            self.field_combo,
            self.word_box,
            self.case_box,
            self.regex_box,
        ):
            w.setEnabled(not rule.builtin)
        self._loading = False
        self._update_feedback(rule)

    def _on_form_changed(self, *_: object) -> None:
        rule = self.current_rule()
        if rule is None:
            return
        if not self._loading:
            rule.active = self.active_box.isChecked()
            if not rule.builtin:
                rule.name = self.name_edit.text()
                rule.find = self.find_edit.text()
                rule.replace = self.replace_edit.text()
                rule.field = RuleField(self.field_combo.currentData())
                rule.whole_word = self.word_box.isChecked()
                rule.case_sensitive = self.case_box.isChecked()
                rule.regex = self.regex_box.isChecked()
            self._fill(self.list.currentItem(), rule)
        self._update_feedback(rule)

    def _update_feedback(self, rule: ReplacementRule) -> None:
        error = rule.error()
        self.error_label.setText(error or "")
        sample = self.test_edit.text()
        if not sample:
            self.test_result.setText("")
        elif error:
            self.test_result.setText("(regel is ongeldig)")
        else:
            field_ok = rule.field.covers(Field.TITLE) or rule.field.covers(Field.ARTIST)
            self.test_result.setText(rule.apply_to(sample) if field_ok else sample)

    # --- import/export -------------------------------------------------------------------
    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Regelset importeren", "", "JSON (*.json)")
        if not path:
            return
        try:
            imported = import_rules(Path(path))
        except ValueError as exc:
            QMessageBox.warning(self, "Importeren", str(exc))
            return
        self.rules.extend(imported)
        self._rebuild(len(self.rules) - len(imported))

    def export_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Regelset exporteren", "vervangingsregels.json", "JSON (*.json)"
        )
        if path:
            export_rules(Path(path), self.rules)

    def accept(self) -> None:
        invalid = [r for r in self.rules if r.active and r.error()]
        if invalid:
            names = ", ".join(r.name or r.find or "(leeg)" for r in invalid)
            answer = QMessageBox.question(
                self,
                "Ongeldige regels",
                f"Deze actieve regels zijn ongeldig en worden overgeslagen: {names}.\n\n"
                "Toch opslaan?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        super().accept()
