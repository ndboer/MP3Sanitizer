import json
import logging

import pytest

from mp3sanitizer.core.app_logging import LOG_FILENAME, setup_logging
from mp3sanitizer.core.settings import Settings, SettingsStore
from mp3sanitizer.core.storage import LoadStatus, load_document, save_document


def test_missing(tmp_path):
    result = load_document(tmp_path / "x.json", 1)
    assert result.status is LoadStatus.MISSING
    assert result.writable


def test_roundtrip(tmp_path):
    path = tmp_path / "x.json"
    save_document(path, {"a": 1, "schema_version": 99}, 3)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw == {"schema_version": 3, "a": 1}
    result = load_document(path, 3)
    assert result.status is LoadStatus.OK
    assert result.data["a"] == 1


@pytest.mark.parametrize("content", ["{niet json", "[1, 2]", '{"schema_version": "x"}', ""])
def test_corrupt_is_quarantined(tmp_path, content):
    path = tmp_path / "x.json"
    path.write_text(content, encoding="utf-8")
    result = load_document(path, 1)
    assert result.status is LoadStatus.CORRUPT
    assert result.message
    assert not path.exists()
    assert (tmp_path / "x.json.corrupt").read_text(encoding="utf-8") == content


def test_newer_is_not_writable(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"schema_version": 5, "a": 1}', encoding="utf-8")
    result = load_document(path, 2)
    assert result.status is LoadStatus.NEWER
    assert not result.writable
    assert "nieuwere versie" in (result.message or "")


def test_migration_chain_with_backup(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"schema_version": 1, "naam": "a"}', encoding="utf-8")
    migrations = {
        1: lambda d: {**d, "stap2": True},
        2: lambda d: {**d, "naam": d["naam"].upper()},
    }
    result = load_document(path, 3, migrations)
    assert result.status is LoadStatus.MIGRATED
    assert result.file_version == 1
    assert result.data == {"schema_version": 3, "naam": "A", "stap2": True}
    assert (tmp_path / "x.json.v1.bak").exists()


def test_missing_migration_raises(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(LookupError):
        load_document(path, 2, {})


def test_settings_from_dict_ignores_garbage():
    s = Settings.from_dict(
        {"extensions": [".mp3"], "last_root": 5, "visible_columns": [1, 2], "onbekend": True}
    )
    assert s.extensions == [".mp3"]
    assert s.last_root is None
    assert s.visible_columns == Settings().visible_columns


def test_settings_store_roundtrip(tmp_path):
    store = SettingsStore.load(tmp_path)
    assert store.load_result.status is LoadStatus.MISSING
    store.settings.last_root = "D:\\Muziek"
    assert store.save()
    again = SettingsStore.load(tmp_path)
    assert again.settings.last_root == "D:\\Muziek"


def test_settings_store_refuses_to_overwrite_newer(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"schema_version": 999}', encoding="utf-8")
    store = SettingsStore.load(tmp_path)
    assert not store.save()
    assert json.loads(path.read_text(encoding="utf-8")) == {"schema_version": 999}


def test_log_first_line_has_version(tmp_path):
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        path = setup_logging(tmp_path)
        logging.getLogger("test").warning("hallo")
        for h in root.handlers:
            h.flush()
        first = path.read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith("Mp3Sanitizer ")
        assert path.name == LOG_FILENAME
    finally:
        for h in root.handlers[:]:
            if h not in before:
                root.removeHandler(h)
                h.close()
