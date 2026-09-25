"""Versie- en buildinformatie voor de Over-dialoog, het logbestand en bugmeldingen.

Eén bron van waarheid: de Git-tag via hatch-vcs (``mp3sanitizer/_version.py``). Commit-hash en
builddatum komen, in deze volgorde, uit:

1. ``mp3sanitizer/_build_info.py`` (gegenereerd bij een PyInstaller-build, niet in Git);
2. het lokale deel van de versie (``0.9.1.dev2+g1a2b3c4``);
3. ``git`` als de app vanuit een checkout draait.
"""

from __future__ import annotations

import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from importlib import metadata
from pathlib import Path

from mp3sanitizer import __version__

_LOCAL_HASH = re.compile(r"\+g([0-9a-f]{7,40})")
_RELEASE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True, slots=True)
class VersionInfo:
    version: str
    commit: str
    build_date: str
    python: str
    pyside: str
    mutagen: str
    platform: str

    def as_text(self) -> str:
        """Tekst voor 'Kopieer info' (bugmeldingen)."""
        return "\n".join(
            [
                f"Mp3Sanitizer {self.version}",
                f"Commit: {self.commit}",
                f"Build: {self.build_date}",
                f"Python: {self.python}",
                f"PySide6: {self.pyside}",
                f"mutagen: {self.mutagen}",
                f"Systeem: {self.platform}",
            ]
        )


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        module = sys.modules.get(name.lower())
        return str(getattr(module, "__version__", "onbekend"))


def _git(*args: str) -> str | None:
    root = Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _build_info() -> tuple[str | None, str | None]:
    try:
        from mp3sanitizer import _build_info  # type: ignore[attr-defined]
    except ImportError:
        return None, None
    return getattr(_build_info, "COMMIT", None), getattr(_build_info, "BUILD_DATE", None)


def commit_hash(version: str = __version__) -> str:
    built_commit, _ = _build_info()
    if built_commit:
        return built_commit
    match = _LOCAL_HASH.search(version)
    if match:
        return match.group(1)[:7]
    return _git("rev-parse", "--short", "HEAD") or "onbekend"


def build_date() -> str:
    _, built = _build_info()
    if built:
        return built
    version_file = Path(__file__).resolve().parents[1] / "_version.py"
    try:
        stamp = datetime.fromtimestamp(version_file.stat().st_mtime)
    except OSError:
        return "onbekend"
    return stamp.strftime("%Y-%m-%d %H:%M") + " (installatie)"


def version_info() -> VersionInfo:
    import mutagen
    import PySide6

    return VersionInfo(
        version=__version__,
        commit=commit_hash(),
        build_date=build_date(),
        python=platform.python_version(),
        pyside=getattr(PySide6, "__version__", _package_version("PySide6")),
        mutagen=getattr(mutagen, "version_string", _package_version("mutagen")),
        platform=platform.platform(),
    )


def release_tuple(version: str) -> tuple[int, int, int] | None:
    """(major, minor, patch) van '0.10.1', 'v0.10.1' of '0.10.1.dev3+g…'; anders ``None``."""
    match = _RELEASE.match(version.strip())
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def is_newer(candidate: str, current: str = __version__) -> bool:
    """Is ``candidate`` (bijv. een release-tag) nieuwer dan de huidige versie?

    Een dev-versie ``0.10.1.dev3`` komt vóór release ``0.10.1``, dus die release is 'nieuwer'.
    """
    new, cur = release_tuple(candidate), release_tuple(current)
    if new is None or cur is None:
        return False
    if new != cur:
        return new > cur
    return ".dev" in current and ".dev" not in candidate
