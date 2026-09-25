"""Afspelen: ``Player`` (QMediaPlayer + QAudioOutput) en de mini-player onderin het venster."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QStyle,
    QToolButton,
    QWidget,
)

from mp3sanitizer.ui.track_model import format_duration

log = logging.getLogger(__name__)

SEEK_STEP_MS = 5000


def next_in_selection(selection: Sequence[int], current: int | None) -> int | None:
    """De track na ``current`` in de (weergave)volgorde van de selectie, of ``None``."""
    if current is None or current not in selection:
        return None
    index = selection.index(current)
    return selection[index + 1] if index + 1 < len(selection) else None


class Player(QObject):
    """Speelt één track tegelijk af. Een nieuwe ``play`` stopt de vorige."""

    trackChanged = Signal(object)  # track-id of None
    playingChanged = Signal(bool)
    positionChanged = Signal(int)  # ms
    durationChanged = Signal(int)  # ms
    finished = Signal(int)  # track-id die tot het eind is afgespeeld
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._track: int | None = None
        self._title = ""
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.playbackStateChanged.connect(
            lambda state: self.playingChanged.emit(state == QMediaPlayer.PlaybackState.PlayingState)
        )
        # qint64 -> int: een directe signal-naar-signal-koppeling weigert PySide.
        self._player.positionChanged.connect(lambda ms: self.positionChanged.emit(int(ms)))
        self._player.durationChanged.connect(lambda ms: self.durationChanged.emit(int(ms)))
        self._player.errorOccurred.connect(self._on_error)

    @property
    def current_track(self) -> int | None:
        return self._track

    @property
    def title(self) -> str:
        return self._title

    @property
    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @property
    def source(self) -> QUrl:
        return self._player.source()

    def play(self, track_id: int, path: Path, title: str = "") -> None:
        self._player.stop()
        self._track = track_id
        self._title = title or path.name
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        self.trackChanged.emit(track_id)

    def toggle_pause(self) -> None:
        if self._track is None:
            return
        if self.is_playing:
            self._player.pause()
        else:
            self._player.play()

    def stop(self) -> None:
        """Stop en laat het bestand los (anders kan Windows het niet hernoemen)."""
        self._player.stop()
        self._player.setSource(QUrl())
        if self._track is not None:
            self._track = None
            self._title = ""
            self.trackChanged.emit(None)

    def seek(self, position_ms: int) -> None:
        self._player.setPosition(max(0, position_ms))

    def seek_relative(self, delta_ms: int) -> None:
        if self._track is not None:
            self.seek(self._player.position() + delta_ms)

    def set_volume(self, percent: int) -> None:
        self._audio.setVolume(max(0, min(100, percent)) / 100)

    @Slot(QMediaPlayer.MediaStatus)
    def _on_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self._track is not None:
            ended = self._track
            self.stop()
            self.finished.emit(ended)

    @Slot(QMediaPlayer.Error, str)
    def _on_error(self, error: QMediaPlayer.Error, message: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        log.warning("Afspelen mislukt (%s): %s", self._title, message)
        self.error.emit(message or "onbekende fout")


class MiniPlayer(QWidget):
    """Balk onderin: huidige track, play/pauze, stop, seekbalk, tijd en volume."""

    def __init__(self, player: Player, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.player = player
        style = self.style()
        self._play_icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        self._pause_icon = style.standardIcon(QStyle.StandardPixmap.SP_MediaPause)

        self.play_button = QToolButton(self)
        self.play_button.setIcon(self._play_icon)
        self.play_button.setToolTip("Afspelen/pauzeren")
        self.play_button.clicked.connect(player.toggle_pause)
        self.stop_button = QToolButton(self)
        self.stop_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.stop_button.setToolTip("Stoppen")
        self.stop_button.clicked.connect(player.stop)
        self.title_label = QLabel("Niets aan het afspelen", self)
        self.title_label.setMinimumWidth(200)
        self.title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.seek_slider.setAccessibleName("Positie")
        self.seek_slider.setSingleStep(SEEK_STEP_MS)
        self.seek_slider.setPageStep(SEEK_STEP_MS * 6)
        self.seek_slider.sliderReleased.connect(lambda: player.seek(self.seek_slider.value()))
        self.seek_slider.actionTriggered.connect(self._on_slider_action)
        self.time_label = QLabel("0:00 / 0:00", self)

        volume_icon = QLabel(self)
        volume_icon.setPixmap(style.standardIcon(QStyle.StandardPixmap.SP_MediaVolume).pixmap(16))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.volume_slider.setAccessibleName("Volume")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setMaximumWidth(110)
        self.volume_slider.valueChanged.connect(player.set_volume)
        self.autoplay = QCheckBox("Automatisch &volgende geselecteerde", self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.addWidget(self.play_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.title_label, 2)
        layout.addWidget(self.seek_slider, 3)
        layout.addWidget(self.time_label)
        layout.addSpacing(8)
        layout.addWidget(volume_icon)
        layout.addWidget(self.volume_slider)
        layout.addSpacing(8)
        layout.addWidget(self.autoplay)

        player.trackChanged.connect(self._on_track)
        player.playingChanged.connect(self._on_playing)
        player.positionChanged.connect(self._on_position)
        player.durationChanged.connect(self._on_duration)
        self._duration = 0
        self._on_track(None)

    def _on_track(self, track_id: object) -> None:
        active = track_id is not None
        self.title_label.setText(self.player.title if active else "Niets aan het afspelen")
        for w in (self.play_button, self.stop_button, self.seek_slider):
            w.setEnabled(active)
        if not active:
            self._duration = 0
            self.seek_slider.setRange(0, 0)
            self._on_position(0)

    def _on_playing(self, playing: bool) -> None:
        self.play_button.setIcon(self._pause_icon if playing else self._play_icon)

    def _on_duration(self, duration: int) -> None:
        self._duration = duration
        self.seek_slider.setRange(0, duration)
        self._on_position(self.seek_slider.value())

    def _on_position(self, position: int) -> None:
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(position)
        self.time_label.setText(
            f"{format_duration(position / 1000) or '0:00'} / "
            f"{format_duration(self._duration / 1000) or '0:00'}"
        )

    def _on_slider_action(self, _action: int) -> None:
        # Toetsenbord/klik op de balk (niet slepen): direct naar de nieuwe positie.
        if not self.seek_slider.isSliderDown():
            self.player.seek(self.seek_slider.sliderPosition())
