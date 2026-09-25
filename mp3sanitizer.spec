# PyInstaller-spec voor Mp3Sanitizer (één map, zonder console).
#
#   uv run pyinstaller mp3sanitizer.spec --noconfirm
#
# Voor het bouwen wordt mp3sanitizer/_build_info.py geschreven (commit-hash en builddatum voor de
# Over-dialoog). De versie zelf komt uit mp3sanitizer/_version.py, dat hatch-vcs genereert bij
# `uv sync`; zorg dus dat de juiste tag is uitgecheckt en draai
# `uv sync --reinstall-package mp3sanitizer` (scripts/release.py doet dit automatisch).
# ruff: noqa
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(SPECPATH)
PACKAGE = ROOT / "mp3sanitizer"


def _commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or "onbekend"
    except (OSError, subprocess.SubprocessError):
        return "onbekend"


(PACKAGE / "_build_info.py").write_text(
    "# Gegenereerd door mp3sanitizer.spec; niet in Git.\n"
    f'COMMIT = "{_commit()}"\n'
    f'BUILD_DATE = "{datetime.now():%Y-%m-%d %H:%M}"\n',
    encoding="utf-8",
)

a = Analysis(
    [str(PACKAGE / "__main__.py")],
    pathex=[str(ROOT)],
    hiddenimports=["mp3sanitizer._version", "mp3sanitizer._build_info"],
    excludes=[
        # niet gebruikt; scheelt veel ruimte
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtPdf",
        "tkinter",
        "pytest",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Mp3Sanitizer",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Mp3Sanitizer", upx=False)
