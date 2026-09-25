import os
import sys
import tempfile
from pathlib import Path


def _smoke_test(output: Path) -> int:
    """Start Qt zonder venster, bouw het hoofdvenster op en schrijf de versie-info weg.

    Gebruikt door ``scripts/release.py`` en de CI om een PyInstaller-build te controleren (een
    ``--windowed`` exe heeft geen stdout).
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QThreadPool
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtWidgets import QApplication

    from mp3sanitizer.core.journal import JournalStore
    from mp3sanitizer.core.settings import SettingsStore
    from mp3sanitizer.core.version_info import version_info
    from mp3sanitizer.ui.main_window import MainWindow

    app = QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        window = MainWindow(SettingsStore.load(Path(tmp)), QThreadPool(), JournalStore(Path(tmp)))
        window.show()
        app.processEvents()
        title = window.windowTitle()
        window.close()
    # Afspelen vereist de multimedia-plugin (FFmpeg); die moet in een build meegekomen zijn.
    multimedia = QMediaPlayer().isAvailable()
    status = "OK" if multimedia else "FOUT: multimedia niet beschikbaar"
    output.write_text(
        f"{version_info().as_text()}\nVenster: {title}\nMultimedia: {multimedia}\n{status}\n",
        encoding="utf-8",
    )
    return 0 if multimedia else 1


def main() -> None:
    args = sys.argv[1:]
    if "--smoke-test" in args:
        index = args.index("--smoke-test")
        target = Path(args[index + 1]) if index + 1 < len(args) else Path("smoke-test.txt")
        sys.exit(_smoke_test(target))
    if "--version" in args:
        from mp3sanitizer.core.version_info import version_info

        text = version_info().as_text()
        if sys.stdout is not None:  # in een --windowed build is er geen console
            print(text)
        return
    from mp3sanitizer.ui.app import run

    sys.exit(run())


if __name__ == "__main__":
    main()
