"""Schema-migraties met fixturebestanden van oudere versies (tests/fixtures)."""

import json
import shutil
from pathlib import Path

import pytest

from mp3sanitizer.core import migrations
from mp3sanitizer.core.batch import run_undo
from mp3sanitizer.core.journal import JOURNAL_SCHEMA_VERSION, JournalStore
from mp3sanitizer.core.settings import SETTINGS_SCHEMA_VERSION, SettingsStore
from mp3sanitizer.core.storage import LoadStatus

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str, target: Path, **placeholders: str) -> Path:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    for key, value in placeholders.items():
        # JSON-escaping van backslashes in Windows-paden
        text = text.replace("{" + key + "}", value.replace("\\", "\\\\"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def test_migrate_journal_1_to_2_function():
    data = json.loads((FIXTURES / "journal_v1.json").read_text(encoding="utf-8"))
    migrated = migrations.migrate_journal_1_to_2(data)
    assert all(e["app_version"] == "0.8.0" for e in migrated["entries"])
    assert "app_version" not in data["entries"][0]  # origineel ongewijzigd


def test_every_step_up_to_current_version_exists():
    for current, table in (
        (JOURNAL_SCHEMA_VERSION, migrations.JOURNAL),
        (SETTINGS_SCHEMA_VERSION, migrations.SETTINGS),
    ):
        assert set(table) == set(range(1, current))


def test_old_journal_is_migrated_with_backup_and_can_be_undone(tmp_path):
    root = tmp_path / "muziek"
    # de toestand ná de oude batch
    (root / "1991").mkdir(parents=True)
    (root / "1991" / "Queen - Innuendo (1991).mp3").write_bytes(b"Q")
    (root / "A-ha - Take On Me.mp3").write_bytes(b"A")
    store = JournalStore(tmp_path / "journal")
    path = _fixture("journal_v1.json", store.json_path("20260925-120000-abc123"), root=str(root))

    journal = store.latest_undoable()
    assert journal is not None
    assert journal.app_version == "0.8.0"
    assert all(e.app_version == "0.8.0" for e in journal.entries)
    backup = path.parent / (path.name + ".v1.bak")
    assert backup.exists()  # back-up vóór migratie
    assert json.loads(backup.read_text(encoding="utf-8"))["schema_version"] == 1
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2  # eenmalig

    result, undo = run_undo(journal, store, "0.10.0")
    assert not result.failures
    assert (root / "rommel" / "queen - innuendo.mp3").read_bytes() == b"Q"
    assert (root / "a-ha - take on me.mp3").read_bytes() == b"A"
    assert not (root / "1991").exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == JOURNAL_SCHEMA_VERSION  # na terugdraaien als v2 bewaard
    assert saved["undone_by"] == undo.batch_id
    assert all(
        e["app_version"] == "0.10.0"
        for e in json.loads(store.json_path(undo.batch_id).read_text(encoding="utf-8"))["entries"]
    )


def test_settings_v1_fixture_loads(tmp_path):
    shutil.copy(FIXTURES / "settings_v1.json", tmp_path / "settings.json")
    store = SettingsStore.load(tmp_path)
    assert store.load_result.status in (LoadStatus.OK, LoadStatus.MIGRATED)
    s = store.settings
    assert s.extensions == [".mp3", ".flac"]
    assert s.last_root == "D:\\Muziek"
    assert s.fuzzy_threshold == 85  # later toegevoegde instelling: standaardwaarde


@pytest.mark.parametrize("version", [JOURNAL_SCHEMA_VERSION + 1, 99])
def test_newer_journal_is_skipped_and_not_overwritten(tmp_path, version):
    store = JournalStore(tmp_path)
    data = json.loads((FIXTURES / "journal_v1.json").read_text(encoding="utf-8"))
    data["schema_version"] = version
    path = tmp_path / "20260925-120000-abc123.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert store.latest_undoable() is None
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == version
