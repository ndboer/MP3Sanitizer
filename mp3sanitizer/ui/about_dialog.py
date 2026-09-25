"""Over-dialoog: versie, commit, builddatum en bibliotheekversies, plus 'Kopieer info'."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mp3sanitizer.core.version_info import VersionInfo, version_info

REPO_URL = "https://github.com/ndboer/MP3Sanitizer"


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, info: VersionInfo | None = None) -> None:
        super().__init__(parent)
        self.info = info or version_info()
        self.setWindowTitle("Over Mp3Sanitizer")
        title = QLabel(f"<h2>Mp3Sanitizer {self.info.version}</h2>", self)
        intro = QLabel(
            "Inventariseren, opschonen en hernoemen van een muziekcollectie op basis van de "
            f'bestandsnaam.<br><a href="{REPO_URL}">{REPO_URL}</a>',
            self,
        )
        intro.setWordWrap(True)
        intro.setOpenExternalLinks(True)
        intro.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)

        form = QFormLayout()
        for label, value in (
            ("Versie:", self.info.version),
            ("Commit:", self.info.commit),
            ("Build:", self.info.build_date),
            ("Python:", self.info.python),
            ("PySide6:", self.info.pyside),
            ("mutagen:", self.info.mutagen),
            ("Systeem:", self.info.platform),
        ):
            value_label = QLabel(value, self)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(label, value_label)

        self.copy_button = QPushButton("&Kopieer info", self)
        self.copy_button.setToolTip("Kopieert deze gegevens naar het klembord, voor een bugmelding")
        self.copy_button.clicked.connect(self.copy_info)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Sluiten")
        buttons.addButton(self.copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def copy_info(self) -> None:
        QGuiApplication.clipboard().setText(self.info.as_text())
        self.copy_button.setText("Gekopieerd ✓")
