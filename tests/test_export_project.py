import json

import pytest

from mp3sanitizer.core.export import export_csv
from mp3sanitizer.core.models import Field
from mp3sanitizer.core.project import (
    Project,
    ProjectEntry,
    ProjectError,
    load_project,
    match_project,
    save_project,
)


def test_csv_for_dutch_excel(tmp_path):
    path = tmp_path / "overzicht.csv"
    n = export_csv(
        path,
        ["Artiest", "Titel", "Jaar"],
        [["Beyoncé", "Crazy; In Love", 2003], ["Queen", 'Say "Hi"', None]],
    )
    assert n == 2
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM
    text = raw.decode("utf-8-sig")
    assert text.splitlines() == [
        "Artiest;Titel;Jaar",
        'Beyoncé;"Crazy; In Love";2003',
        'Queen;"Say ""Hi""";',
    ]


def test_project_roundtrip(tmp_path):
    path = tmp_path / "sessie.mp3s.json"
    n = save_project(
        path,
        tmp_path / "muziek",
        "0.9.0",
        [
            ProjectEntry("1985\\A - B.mp3", {Field.ARTIST: "A-ha", Field.YEAR: 1985}),
            ProjectEntry("leeg.mp3", {}),  # zonder wijzigingen: niet opgeslagen
            ProjectEntry("C - D.mp3", {Field.YEAR: None}),
        ],
    )
    assert n == 2
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["app_version"] == "0.9.0"
    project = load_project(path)
    assert project.root == str(tmp_path / "muziek")
    assert project.entries[0].fields == {Field.ARTIST: "A-ha", Field.YEAR: 1985}
    assert project.entries[1].fields == {Field.YEAR: None}


def test_project_ignores_bad_values(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "root": "/m",
                "changes": [
                    {"path": "a.mp3", "fields": {"year": "1985", "artist": 5, "wat": 1}},
                    {"fields": {}},
                    "rommel",
                ],
            }
        ),
        encoding="utf-8",
    )
    project = load_project(path)
    assert [e.path for e in project.entries] == ["a.mp3"]
    assert project.entries[0].fields == {}


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{kapot", "onleesbaar"),
        ('{"schema_version": 7, "root": "/m"}', "nieuwere versie"),
        ('{"schema_version": 1}', "geen hoofdmap"),
    ],
)
def test_project_errors(tmp_path, content, message):
    path = tmp_path / "p.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ProjectError, match=message):
        load_project(path)


def test_missing_project(tmp_path):
    with pytest.raises(ProjectError, match="bestaat niet"):
        load_project(tmp_path / "weg.json")


def test_match_project_case_insensitive_and_unmatched():
    project = Project(
        "/m",
        [
            ProjectEntry("1985/A - B.mp3", {Field.ARTIST: "A-ha", Field.TITLE: "B"}),
            ProjectEntry("weg.mp3", {Field.YEAR: 2000}),
        ],
    )
    current = {7: {Field.ARTIST: "A", Field.TITLE: "B", Field.YEAR: None}}
    result = match_project(project, [(7, "1985\\a - b.MP3")], current)
    assert [(c.track_id, c.field, c.old, c.new) for c in result.changes] == [
        (7, Field.ARTIST, "A", "A-ha")
    ]
    assert result.unmatched == ["weg.mp3"]
