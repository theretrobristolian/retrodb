"""Nintendo Wii WBFS discovery must never equate disc IDs with RA content hashes."""
import csv
import importlib.util
import json
from pathlib import Path

import pytest

FILE = Path(__file__).resolve().parents[1] / "server" / "report_wii_audit.py"
spec = importlib.util.spec_from_file_location("report_wii_audit", FILE)
wii = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wii)


def create(tmp_path, title="Attack of the Movies 3D", disc_id="S3AE5G"):
    root = tmp_path / "wii"
    folder = root / f"{title} [{disc_id}]"
    folder.mkdir(parents=True)
    image = folder / f"{disc_id}.wbfs"
    image.write_bytes(b"WBFS" + b"\0" * 64)
    return root, image


def ra_catalogue(tmp_path):
    path = tmp_path / "wii.json"
    path.write_text(json.dumps([
        {"ID": 123, "ConsoleID": 19, "Title": "Attack of the Movies 3D",
         "Hashes": ["a" * 32], "NumAchievements": 19},
        {"ID": 124, "ConsoleID": 19, "Title": "Another Wii Game",
         "Hashes": [], "NumAchievements": 0},
        {"ID": 100, "ConsoleID": 10, "Title": "Not Wii",
         "Hashes": ["b" * 32], "NumAchievements": 10},
    ]))
    return path


def test_wbfs_disc_id_and_ra_title_candidate_are_not_hash_verified(tmp_path):
    root, image = create(tmp_path)
    before = image.read_bytes()
    records = wii.audit(root, ra_catalogue(tmp_path))
    assert len(records) == 1
    row = records[0]
    assert row["status"] == "TITLE_CANDIDATE"
    assert row["disc_id"] == "S3AE5G"
    assert row["region"] == "USA"
    assert row["ra_game_id"] == 123
    assert row["ra_achievements"] == 19
    assert row["title_source"] == "folder"
    assert "not verified" in row["reason"]
    assert image.read_bytes() == before


def test_wrong_disc_id_is_not_a_matched_game(tmp_path):
    root, image = create(tmp_path)
    image.rename(image.with_name("OTHER1.wbfs"))
    rows = wii.audit(root, ra_catalogue(tmp_path))
    assert len(rows) == 1
    assert rows[0]["status"] == "REVIEW"
    assert rows[0]["disc_id"] == ""
    assert rows[0]["ra_game_id"] == ""
    assert "differ" in rows[0]["reason"]


def test_missing_catalogue_still_identifies_disc(tmp_path):
    root, image = create(tmp_path)
    rows = wii.audit(root, tmp_path / "missing.json")
    assert len(rows) == 1
    assert rows[0]["status"] == "IDENTIFIED"
    assert rows[0]["ra_game_id"] == ""
    assert image.exists()


def test_counts_split_wbfs_parts_without_extra_rows(tmp_path):
    root, _ = create(tmp_path)
    folder = next(root.iterdir())
    (folder / "S3AE5G.wbf1").write_bytes(b"part2")
    (folder / "readme.txt").write_text("description")
    (folder / "S3AE5G.WBF2").write_bytes(b"123456")
    (folder / "S3AE5G.iso").write_bytes(b"iso")
    rows = {r["filename"]: r for r in wii.audit(root)}
    assert len(rows) == 2
    assert rows["S3AE5G.wbfs"]["size_bytes"] == 68 + 5 + 6
    assert rows["S3AE5G.iso"]["size_bytes"] == 3


def test_orphaned_continuation_warns_without_extra_game(tmp_path):
    root, image = create(tmp_path)
    (image.parent / "OTHER1.wbf1").write_bytes(b"orphan")
    with pytest.warns(UserWarning, match="Orphaned WBFS continuation"):
        assert len(wii.audit(root)) == 1


def test_gap_in_split_parts_requires_review(tmp_path):
    root, image = create(tmp_path)
    image.with_suffix(".wbf2").write_bytes(b"part")
    row = wii.audit(root)[0]
    assert row["status"] == "REVIEW"
    assert row["size_bytes"] == 72


def test_optional_gametdb_xml_matches_disc_id(tmp_path):
    root, _ = create(tmp_path)
    xml = tmp_path / "wii.xml"
    xml.write_text('<datafile><game><id>S3AE5G</id>'
                   '<title>Attack of the Movies 3D</title>'
                   '</game></datafile>')
    rows = wii.audit(root, ra_catalogue(tmp_path), xml)
    assert rows[0]["title_source"] == "GameTDB disc ID"
    assert rows[0]["status"] == "TITLE_CANDIDATE"


def test_real_gametdb_locale_structure(tmp_path):
    root, _ = create(tmp_path)
    xml = tmp_path / "wii.xml"
    xml.write_text('<datafile><game><id>S3AE5G</id><locale lang="FR">'
                   '<title>French title</title></locale><locale lang="EN">'
                   '<title>Attack of the Movies 3D</title></locale></game></datafile>')
    row = wii.audit(root, ra_catalogue(tmp_path), xml)[0]
    assert row["title"] == "Attack of the Movies 3D"
    assert row["title_source"] == "GameTDB disc ID"


def test_wrong_console_in_ra_catalogue_ignored(tmp_path):
    path = tmp_path / "wii.json"
    path.write_text('[{"ID":11,"ConsoleID":10,"Title":"Not Wii",'
                    '"NumAchievements":10,"Hashes":[]}]')
    assert wii.game_catalogue(path) == {}


def test_csv_output_round_trip(tmp_path):
    root, _ = create(tmp_path)
    rows = wii.audit(root)
    path = tmp_path / "wii.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=wii.FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with path.open(newline="") as handle:
        result = list(csv.DictReader(handle))
    assert result[0]["relative_path"] == "Attack of the Movies 3D [S3AE5G]/S3AE5G.wbfs"
    assert result[0]["disc_id"] == "S3AE5G"


def test_ambiguous_ra_title_never_claimed_as_verified(tmp_path):
    root, _ = create(tmp_path)
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps([
        {"ID": 1, "ConsoleID": 19, "Title": "Attack of the Movies 3D", "NumAchievements": 4},
        {"ID": 2, "ConsoleID": 19, "Title": "Attack of the Movies 3D", "NumAchievements": 8},
    ]))
    row = wii.audit(root, path)[0]
    assert row["status"] == "AMBIGUOUS_TITLE"
    assert not row["ra_game_id"]
