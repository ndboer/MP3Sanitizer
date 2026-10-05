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


@pytest.fixture(autouse=True)
def fake_media_player(monkeypatch):
    """Vervang QMediaPlayer door een nepspeler.

    De echte Windows-mediabackend blokkeert soms in ``stop()`` vlak na ``play()``, waardoor de
    hele testrun (en daarmee een release) bleef hangen. De echte backend wordt bij elke release
    gecontroleerd door de smoke-test van de exe.
    """
    from PySide6.QtCore import QObject, QUrl, Signal
    from PySide6.QtMultimedia import QMediaPlayer

    from mp3sanitizer.ui import player as player_module

    class FakeMediaPlayer(QObject):
        PlaybackState = QMediaPlayer.PlaybackState
        MediaStatus = QMediaPlayer.MediaStatus
        Error = QMediaPlayer.Error
        mediaStatusChanged = Signal(QMediaPlayer.MediaStatus)
        playbackStateChanged = Signal(QMediaPlayer.PlaybackState)
        positionChanged = Signal("qlonglong")
        durationChanged = Signal("qlonglong")
        errorOccurred = Signal(QMediaPlayer.Error, str)

        def __init__(self, parent=None):
            super().__init__(parent)
            self._source = QUrl()
            self._state = QMediaPlayer.PlaybackState.StoppedState
            self._position = 0

        def setAudioOutput(self, output):
            self._output = output

        def setSource(self, url):
            self._source = QUrl(url)

        def source(self):
            return self._source

        def _set_state(self, state):
            if state != self._state:
                self._state = state
                self.playbackStateChanged.emit(state)

        def play(self):
            if not self._source.isEmpty():
                self._set_state(QMediaPlayer.PlaybackState.PlayingState)

        def pause(self):
            self._set_state(QMediaPlayer.PlaybackState.PausedState)

        def stop(self):
            self._set_state(QMediaPlayer.PlaybackState.StoppedState)

        def playbackState(self):
            return self._state

        def position(self):
            return self._position

        def setPosition(self, ms):
            self._position = int(ms)
            self.positionChanged.emit(self._position)

    monkeypatch.setattr(player_module, "QMediaPlayer", FakeMediaPlayer)
