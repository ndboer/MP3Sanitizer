"""Locaties van configuratie en data (via platformdirs)."""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "Mp3Sanitizer"


def config_dir() -> Path:
    return Path(user_config_dir(APP_NAME, appauthor=False, roaming=True))


def data_dir() -> Path:
    return Path(user_data_dir(APP_NAME, appauthor=False))


def log_dir() -> Path:
    return data_dir() / "logs"
