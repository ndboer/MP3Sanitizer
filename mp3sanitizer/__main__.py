import sys


def main() -> None:
    from mp3sanitizer.ui.app import run

    sys.exit(run())


if __name__ == "__main__":
    main()
