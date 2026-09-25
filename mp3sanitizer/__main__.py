import sys


def main() -> None:
    if "--version" in sys.argv[1:]:
        from mp3sanitizer.core.version_info import version_info

        print(version_info().as_text())
        return
    from mp3sanitizer.ui.app import run

    sys.exit(run())


if __name__ == "__main__":
    main()
