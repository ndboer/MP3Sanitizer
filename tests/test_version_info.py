import httpx
import pytest

from mp3sanitizer import __version__
from mp3sanitizer.core import version_info as vi
from mp3sanitizer.core.update_check import check_for_update


def test_version_info_contents():
    info = vi.version_info()
    assert info.version == __version__
    text = info.as_text()
    for label in ("Mp3Sanitizer", "Commit:", "Build:", "Python:", "PySide6:", "mutagen:"):
        assert label in text
    assert info.commit  # hash, of 'onbekend'


def test_commit_from_local_version_part(monkeypatch):
    monkeypatch.setattr(vi, "_build_info", lambda: (None, None))
    assert vi.commit_hash("0.9.1.dev2+g1a2b3c4d.d20260925") == "1a2b3c4"


def test_build_info_file_wins(monkeypatch):
    monkeypatch.setattr(vi, "_build_info", lambda: ("abcdef0", "2026-09-25 12:00"))
    assert vi.commit_hash("0.9.1+gffffff") == "abcdef0"
    assert vi.build_date() == "2026-09-25 12:00"


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("v0.10.0", "0.9.0", True),
        ("v0.9.0", "0.9.0", False),
        ("v0.9.0", "0.10.0", False),
        ("v1.0.0", "0.10.3", True),
        ("v0.10.1", "0.10.1.dev3+gabc", True),  # dev vóór de release
        ("v0.10.1", "0.10.2.dev1+gabc", False),
        ("nightly", "0.9.0", False),
        ("v0.10.0", "0.0.0+unknown", True),
    ],
)
def test_is_newer(candidate, current, newer):
    assert vi.is_newer(candidate, current) is newer


def _client(response=None, exc=None):
    def handler(request):
        assert request.headers["User-Agent"].startswith("Mp3Sanitizer/")
        if exc:
            raise exc
        return response

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_update_check_newer():
    resp = httpx.Response(200, json={"tag_name": "v9.9.9", "html_url": "https://x/releases/9"})
    result = check_for_update("0.10.0", _client(resp))
    assert result.newer and result.latest == "v9.9.9" and result.url == "https://x/releases/9"


def test_update_check_up_to_date():
    resp = httpx.Response(200, json={"tag_name": "v0.10.0"})
    assert not check_for_update("0.10.0", _client(resp)).newer


@pytest.mark.parametrize(
    ("client", "message"),
    [
        (_client(httpx.Response(404)), "nog geen releases"),
        (_client(httpx.Response(500)), "500"),
        (_client(httpx.Response(200, text="geen json")), "Onverwacht"),
        (_client(exc=httpx.ConnectError("x")), "Geen verbinding"),
    ],
)
def test_update_check_errors(client, message):
    result = check_for_update("0.10.0", client)
    assert not result.newer
    assert message in (result.error or "")
