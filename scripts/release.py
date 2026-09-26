"""Releaseproces voor Mp3Sanitizer.

    uv run python scripts/release.py release 0.10.0          # controleren, changelog, tag, build
    uv run python scripts/release.py release 0.10.0 --push   # idem, daarna git push --follow-tags
    uv run python scripts/release.py release 0.10.0 --dry-run
    uv run python scripts/release.py build                   # alleen PyInstaller-build + zip
    uv run python scripts/release.py manual                  # alleen de handleiding (PDF)
    uv run python scripts/release.py notes 0.10.0            # changelogsectie (voor de CI)

Stappen van ``release``:

1. controleren: op ``main``, werkboom schoon, versie hoger dan de laatste tag, tests en ruff groen;
2. ``CHANGELOG.md``: de sectie "Unreleased" wordt "[X.Y.Z] - datum" (met een nieuwe, lege
   "Unreleased" erboven) en gecommit als ``chore(release): vX.Y.Z``;
3. Git-tag ``vX.Y.Z``;
4. PyInstaller-build (``mp3sanitizer.spec``), smoke-test van de exe en
   ``dist/mp3sanitizer-X.Y.Z-win64.zip``, plus de handleiding
   ``dist/Mp3Sanitizer-handleiding-X.Y.Z.pdf`` (screenshots van de echte app).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
DIST = ROOT / "dist"
APP_DIR = DIST / "Mp3Sanitizer"
EXE = APP_DIR / "Mp3Sanitizer.exe"
UNRELEASED = "## [Unreleased]"
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_SECTION = re.compile(r"^## \[", re.MULTILINE)
COMMIT_TRAILER = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


class ReleaseError(Exception):
    pass


# --- pure hulpfuncties (getest in tests/test_release.py) -------------------------------------


def parse_version(text: str) -> tuple[int, int, int]:
    match = _SEMVER.match(text.strip().removeprefix("v"))
    if not match:
        raise ReleaseError(f"'{text}' is geen versie in de vorm MAJOR.MINOR.PATCH")
    return int(match[1]), int(match[2]), int(match[3])


def _split_sections(text: str) -> list[tuple[int, int]]:
    """(start, einde) van elke '## [' sectie."""
    starts = [m.start() for m in _SECTION.finditer(text)]
    return [(s, starts[i + 1] if i + 1 < len(starts) else len(text)) for i, s in enumerate(starts)]


def changelog_section(text: str, version: str) -> str:
    """De inhoud (zonder kop) van de sectie ``[version]``."""
    heading = f"## [{version}]"
    for start, end in _split_sections(text):
        if text.startswith(heading, start):
            body = text[start:end].split("\n", 1)[1] if "\n" in text[start:end] else ""
            return body.strip()
    raise ReleaseError(f"Sectie {heading} niet gevonden in CHANGELOG.md")


def promote_changelog(text: str, version: str, day: date) -> str:
    """Zet de inhoud van 'Unreleased' onder een nieuwe kop '[version] - datum'."""
    if f"## [{version}]" in text:
        raise ReleaseError(f"CHANGELOG.md bevat al een sectie voor {version}")
    for start, end in _split_sections(text):
        if text.startswith(UNRELEASED, start):
            body = text[start + len(UNRELEASED) : end].strip()
            if not body:
                raise ReleaseError("De sectie 'Unreleased' in CHANGELOG.md is leeg")
            new = f"{UNRELEASED}\n\n## [{version}] - {day.isoformat()}\n\n{body}\n\n"
            return text[:start] + new + text[end:]
    raise ReleaseError("CHANGELOG.md heeft geen sectie '## [Unreleased]'")


def zip_name(version: str) -> str:
    return f"mp3sanitizer-{version}-win64.zip"


def manual_name(version: str) -> str:
    return f"Mp3Sanitizer-handleiding-{version}.pdf"


# --- stappen ---------------------------------------------------------------------------------


def run(*cmd: str, capture: bool = False, dry: bool = False, timeout: float | None = None) -> str:
    print("  $", " ".join(cmd))
    if dry and not capture:
        return ""
    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=capture, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ReleaseError(f"Commando duurde langer dan {timeout:.0f} s: {' '.join(cmd)}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        raise ReleaseError(f"Commando mislukt ({result.returncode}): {' '.join(cmd)}\n{detail}")
    return (result.stdout or "").strip()


def latest_tag() -> str | None:
    try:
        return run("git", "describe", "--tags", "--abbrev=0", "--match", "v*", capture=True)
    except ReleaseError:
        return None


def check_repository(version: str) -> None:
    print("1. Controleren…")
    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD", capture=True)
    if branch != "main":
        raise ReleaseError(f"Releasen kan alleen vanaf 'main' (nu: {branch})")
    if run("git", "status", "--porcelain", capture=True):
        raise ReleaseError("De werkboom is niet schoon; commit of stash eerst je wijzigingen")
    if run("git", "tag", "--list", f"v{version}", capture=True):
        raise ReleaseError(f"Tag v{version} bestaat al")
    previous = latest_tag()
    if previous and parse_version(version) <= parse_version(previous):
        raise ReleaseError(f"Versie {version} moet hoger zijn dan de laatste tag {previous}")


def run_checks(dry: bool) -> None:
    print("   tests en ruff…")
    # Een hangende test mag de release nooit eeuwig laten wachten.
    run("uv", "run", "pytest", "-q", "-p", "no:cacheprovider", dry=dry, timeout=900)
    run("uv", "run", "ruff", "check", ".", dry=dry)
    run("uv", "run", "ruff", "format", "--check", ".", dry=dry)


def update_changelog(version: str, dry: bool) -> None:
    print("2. CHANGELOG.md bijwerken…")
    text = CHANGELOG.read_text(encoding="utf-8")
    new = promote_changelog(text, version, date.today())
    if dry:
        print(changelog_section(new, version))
        return
    CHANGELOG.write_text(new, encoding="utf-8", newline="\n")
    run("git", "add", "CHANGELOG.md")
    run("git", "commit", "-q", "-m", f"chore(release): v{version}\n\n{COMMIT_TRAILER}")


def create_tag(version: str, dry: bool) -> None:
    print(f"3. Tag v{version}…")
    run("git", "tag", "-a", f"v{version}", "-m", f"v{version}", dry=dry)


def build(expected_version: str | None = None, dry: bool = False) -> Path:
    print("4. Bouwen…")
    # _version.py opnieuw laten genereren, zodat de build de juiste (getagde) versie krijgt.
    run("uv", "sync", "--reinstall-package", "mp3sanitizer", dry=dry)
    version = expected_version or run(
        "uv",
        "run",
        "python",
        "-c",
        "import mp3sanitizer; print(mp3sanitizer.__version__)",
        capture=True,
    )
    if dry:
        return DIST / zip_name(version)
    shutil.rmtree(APP_DIR, ignore_errors=True)
    run("uv", "run", "pyinstaller", "mp3sanitizer.spec", "--noconfirm", "--log-level", "WARN")
    smoke = DIST / "smoke-test.txt"
    smoke.unlink(missing_ok=True)
    subprocess.run([str(EXE), "--smoke-test", str(smoke)], cwd=ROOT, timeout=120, check=True)
    report = smoke.read_text(encoding="utf-8")
    first = report.splitlines()[0]
    if first != f"Mp3Sanitizer {version}" or not report.rstrip().endswith("OK"):
        raise ReleaseError(f"Smoke-test van de exe mislukt:\n{report}")
    print(f"   smoke-test OK: {first}")
    archive = DIST / zip_name(version)
    archive.unlink(missing_ok=True)
    shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=DIST, base_dir=APP_DIR.name)
    print(f"   {archive.relative_to(ROOT)} ({archive.stat().st_size / 1e6:.0f} MB)")
    build_manual(version)
    return archive


def build_manual(version: str | None = None) -> Path:
    """Screenshots van de echte app maken en de PDF-handleiding bouwen."""
    print("   handleiding…")
    version = version or run(
        "uv",
        "run",
        "python",
        "-c",
        "import mp3sanitizer; print(mp3sanitizer.__version__)",
        capture=True,
    )
    shots = ROOT / "build" / "manual" / "screenshots"
    shutil.rmtree(shots, ignore_errors=True)
    DIST.mkdir(exist_ok=True)
    pdf = DIST / manual_name(version)
    run("uv", "run", "python", "docs/manual/screenshots.py", str(shots), timeout=600)
    run(
        "uv",
        "run",
        "python",
        "docs/manual/build_pdf.py",
        str(shots),
        str(pdf),
        version,
        timeout=300,
    )
    print(f"   {pdf.relative_to(ROOT)} ({pdf.stat().st_size / 1e3:.0f} KB)")
    return pdf


def release(version: str, *, push: bool, no_build: bool, dry: bool) -> None:
    parse_version(version)
    check_repository(version)
    run_checks(dry)
    update_changelog(version, dry)
    create_tag(version, dry)
    if not no_build:
        build(version, dry)
    if push:
        print("5. Pushen…")
        run("git", "push", "--follow-tags", dry=dry)
    print(f"\nKlaar: v{version}" + (" (dry-run, er is niets gewijzigd)" if dry else ""))
    if not push and not dry:
        print("Vergeet niet: git push --follow-tags")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_release = sub.add_parser("release", help="volledige release")
    p_release.add_argument("version")
    p_release.add_argument("--push", action="store_true", help="daarna git push --follow-tags")
    p_release.add_argument("--no-build", action="store_true", help="geen PyInstaller-build")
    p_release.add_argument("--dry-run", action="store_true", help="alleen tonen wat er gebeurt")
    p_build = sub.add_parser("build", help="PyInstaller-build + smoke-test + zip")
    p_build.add_argument("--version", help="verwachte versie (standaard: huidige)")
    p_manual = sub.add_parser("manual", help="alleen de PDF-handleiding bouwen")
    p_manual.add_argument("--version", help="versie op de titelpagina (standaard: huidige)")
    p_notes = sub.add_parser("notes", help="changelogsectie van een versie tonen")
    p_notes.add_argument("version")
    args = parser.parse_args(argv)
    try:
        if args.command == "release":
            release(args.version, push=args.push, no_build=args.no_build, dry=args.dry_run)
        elif args.command == "build":
            build(args.version)
        elif args.command == "manual":
            build_manual(args.version)
        else:
            print(changelog_section(CHANGELOG.read_text(encoding="utf-8"), args.version))
    except ReleaseError as exc:
        print(f"\nFOUT: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
