import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def no_blocking_message_boxes(monkeypatch):
    """Een modaal berichtvenster zou een (offscreen) test eeuwig laten wachten.

    Bijvoorbeeld het foutenoverzicht na opslaan, als een virusscanner een bestand even vasthoudt.
    Hier worden ze vervangen door een variant die meteen een veilig antwoord geeft (Annuleren/Nee).
    Tests die een specifiek antwoord nodig hebben, overschrijven dit met hun eigen monkeypatch.
    Getoonde meldingen staan in ``shown_message_boxes``.
    """
    from PySide6.QtWidgets import QMessageBox

    shown: list[str] = []
    buttons = QMessageBox.StandardButton

    def answer(default):
        def fake(*args, **kwargs):
            shown.append(str(args[2]) if len(args) > 2 else "")
            return default

        return staticmethod(fake)

    for name, default in (
        ("information", buttons.Ok),
        ("warning", buttons.Cancel),
        ("critical", buttons.Ok),
        ("question", buttons.No),
    ):
        monkeypatch.setattr(QMessageBox, name, answer(default))
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: shown.append(self.text()) or int(buttons.Ok)
    )
    return shown
