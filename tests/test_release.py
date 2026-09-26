import importlib.util
from datetime import date
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "release_script", Path(__file__).parents[1] / "scripts" / "release.py"
)
release = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(release)

CHANGELOG = """# Changelog

Intro.

## [Unreleased]

### Added
- Nieuw ding.

## [0.9.0] - 2026-09-25

### Added
- Oud ding.
"""


def test_promote_changelog():
    new = release.promote_changelog(CHANGELOG, "0.10.0", date(2026, 9, 26))
    assert (
        "## [Unreleased]\n\n## [0.10.0] - 2026-09-26\n\n### Added\n- Nieuw ding.\n\n## [0.9.0]"
        in new
    )
    assert release.changelog_section(new, "0.10.0") == "### Added\n- Nieuw ding."
    assert release.changelog_section(new, "0.9.0") == "### Added\n- Oud ding."


def test_promote_refuses_empty_or_duplicate():
    empty = CHANGELOG.replace("### Added\n- Nieuw ding.\n\n", "")
    with pytest.raises(release.ReleaseError, match="leeg"):
        release.promote_changelog(empty, "0.10.0", date.today())
    with pytest.raises(release.ReleaseError, match="al een sectie"):
        release.promote_changelog(CHANGELOG, "0.9.0", date.today())
    with pytest.raises(release.ReleaseError, match="Unreleased"):
        release.promote_changelog("# Changelog\n", "1.0.0", date.today())


def test_parse_version_and_zip_name():
    assert release.parse_version("v1.2.3") == (1, 2, 3)
    assert release.parse_version("0.10.0") > release.parse_version("0.9.9")
    with pytest.raises(release.ReleaseError):
        release.parse_version("1.2")
    assert release.zip_name("1.0.0") == "mp3sanitizer-1.0.0-win64.zip"


def test_real_changelog_has_unreleased_section():
    text = (Path(__file__).parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    assert release.UNRELEASED in text
    release.changelog_section(text, "0.1.0")


def test_manual_name():
    assert release.manual_name("0.10.2") == "Mp3Sanitizer-handleiding-0.10.2.pdf"
