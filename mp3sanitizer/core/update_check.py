"""Optionele updatecheck: vraagt de laatste release op en meldt alleen of er iets nieuws is.

Er wordt nooit iets gedownload of geïnstalleerd. Standaard staat de check UIT.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from mp3sanitizer import __version__
from mp3sanitizer.core.musicbrainz import DEFAULT_CONTACT
from mp3sanitizer.core.version_info import is_newer

RELEASES_API = "https://api.github.com/repos/ndboer/MP3Sanitizer/releases/latest"


@dataclass(frozen=True, slots=True)
class UpdateResult:
    latest: str | None  # tag van de laatste release
    url: str | None  # releasepagina
    newer: bool
    error: str | None = None


def check_for_update(
    current: str = __version__, http: httpx.Client | None = None, url: str = RELEASES_API
) -> UpdateResult:
    """Faalt nooit: netwerk- en API-fouten komen in ``error``."""
    client = http or httpx.Client(timeout=10)
    try:
        response = client.get(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"Mp3Sanitizer/{current} ( {DEFAULT_CONTACT} )",
            },
        )
    except httpx.HTTPError as exc:
        return UpdateResult(None, None, False, f"Geen verbinding: {exc}")
    if response.status_code == 404:
        return UpdateResult(None, None, False, "Er zijn nog geen releases gepubliceerd")
    if response.status_code != 200:
        return UpdateResult(None, None, False, f"GitHub antwoordde met {response.status_code}")
    try:
        data = response.json()
        tag = str(data["tag_name"])
        page = str(data.get("html_url") or "")
    except (ValueError, KeyError, TypeError) as exc:
        return UpdateResult(None, None, False, f"Onverwacht antwoord: {exc}")
    return UpdateResult(tag, page or None, is_newer(tag, current))
