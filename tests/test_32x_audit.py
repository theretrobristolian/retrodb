import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

FILE = Path(__file__).resolve().parents[1] / "server" / "report_32x_audit.py"
spec = importlib.util.spec_from_file_location("sega32x_audit", FILE)
audit32 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit32)


def write_zip(folder, filename, members):
    with zipfile.ZipFile(folder / filename, "w") as archive:
        for member, data in members.items():
            archive.writestr(member, data)


def catalogue(path, good_rom, include_other=False):
    games = [{
        "ID": 101,
        "ConsoleID": 10,
        "Title": "After Burner Complete",
        "NumAchievements": 13,
        "Hashes": [hashlib.md5(good_rom).hexdigest()],
    }]
    if include_other:
        games.append({
            "ID": 102, "ConsoleID": 10, "Title": "Doom",
            "NumAchievements": 20, "Hashes": [],
        })
    path.write_text(json.dumps(games))


def test_exact_and_soft_pass_regional_zip(tmp_path):
    roms = tmp_path / "roms"
    roms.mkdir()
    good = b"canonical-32x-rom"
    write_zip(roms, "[32X] After Burner Complete (USA).zip",
              {"After Burner Complete (USA).32x": good})
    write_zip(roms, "[32X] After Burner Complete (Japan).zip",
              {"After Burner Complete (Japan).32x": b"regional-different"})
    write_zip(roms, "[32X] 32xbios.zip", {"bios.bin": b"bios"})
    (roms / "_readme.txt").write_text("ignore")
    source = tmp_path / "ra.json"
    catalogue(source, good)
    rows = audit32.audit(roms, source)
    assert len(rows) == 2
    matched = next(row for row in rows if row["status"] == "EXACT_RA")
    other = next(row for row in rows if row["status"] == "SOFT_PASS_VARIANT")
    assert matched["status"] == "EXACT_RA"
    assert matched["display_title"] == "After Burner Complete"
    assert matched["title_source"] == "RetroAchievements hash"
    assert matched["ra_md5"] == hashlib.md5(good).hexdigest()
    assert other["status"] == "SOFT_PASS_VARIANT"
    assert "USA" in other["local_verified_variant"]
    assert other["ra_game_id"] == ""
    assert other["suggested_ra_game_id"] == 101


def test_unmatched_and_ambiguous_zip_are_read_only(tmp_path):
    root = tmp_path / "32x"
    root.mkdir()
    write_zip(root, "[32X] Mystery (Europe).zip", {"Mystery.32x": b"unknown"})
    write_zip(root, "[32X] Several (World).zip",
              {"one.32x": b"a", "two.32x": b"b"})
    good = b"known"
    source = tmp_path / "ra.json"
    catalogue(source, good)
    before = {x.name: x.read_bytes() for x in root.iterdir()}
    rows = audit32.audit(root, source)
    assert sorted(x["status"] for x in rows) == ["REVIEW", "UNMATCHED"]
    assert {x.name: x.read_bytes() for x in root.iterdir()} == before


def test_title_candidates_are_not_claimed_as_hash_matches(tmp_path):
    folder = tmp_path / "32x"
    folder.mkdir()
    write_zip(folder, "[32X] Doom (Europe).zip", {"Doom.32x": b"unknown"})
    source = tmp_path / "ra.json"
    catalogue(source, b"different", include_other=True)
    row = audit32.audit(folder, source)[0]
    assert row["status"] == "ALTERNATIVE_REVIEW"
    assert row["title_source"] == "RetroAchievements title candidate"
    assert row["ra_game_id"] == ""
    assert row["suggested_ra_game_id"] == 102
    assert row["ra_supported_md5"] == ""


def test_reviewed_hack_and_prototype_identity_does_not_grant_hash_match(tmp_path):
    root = tmp_path / "32x"
    root.mkdir()
    cases = [
        ("[32X] Doom (Europe) [Patch Ressurrection v3.1].zip", 18179),
        ("[32X] Pinocchio 32X Working (patched).zip", 16800),
        ("[32X] Soulstar X (USA) (Proto).zip", 15989),
    ]
    for index, (filename, _) in enumerate(cases):
        write_zip(root, filename, {"game.32x": ("unregistered%d" % index).encode()})
    catalogue_path = tmp_path / "ra.json"
    games = [
        {"ID": 12777, "ConsoleID": 10, "Title": "Doom",
         "NumAchievements": 59, "Hashes": ["a" * 32]},
        {"ID": 18179, "ConsoleID": 10, "Title": "~Hack~ Doom 32X: Resurrection",
         "NumAchievements": 117, "Hashes": ["b" * 32]},
        {"ID": 16800, "ConsoleID": 10, "Title": "~Prototype~ Pinocchio",
         "NumAchievements": 27, "Hashes": ["c" * 32]},
        {"ID": 15989, "ConsoleID": 10, "Title": "~Prototype~ Soul Star X | Soulstar X",
         "NumAchievements": 6, "Hashes": ["d" * 32]},
    ]
    catalogue_path.write_text(json.dumps(games))
    rows = {row["filename"]: row for row in audit32.audit(root, catalogue_path)}
    for filename, game_id in cases:
        assert rows[filename]["status"] == "ALTERNATIVE_REVIEW"
        assert rows[filename]["suggested_ra_game_id"] == game_id
        assert rows[filename]["ra_game_id"] == ""
        assert rows[filename]["ra_supported_md5"]
    assert rows[cases[0][0]]["suggested_ra_game_id"] != 12777


def test_reviewed_identity_soft_passes_only_with_real_verified_zip(tmp_path):
    root = tmp_path / "32x"
    root.mkdir()
    supported = b"verified"
    write_zip(root, "[32X] Soul Star X (Proto) (supported).zip", {"game.32x": supported})
    write_zip(root, "[32X] Soulstar X (USA) (Proto).zip", {"game.32x": b"other"})
    source = tmp_path / "ra.json"
    source.write_text(json.dumps([{
        "ID": 15989, "ConsoleID": 10, "Title": "~Prototype~ Soul Star X | Soulstar X",
        "NumAchievements": 6, "Hashes": [hashlib.md5(supported).hexdigest()]
    }]))
    rows = audit32.audit(root, source)
    assert sorted(row["status"] for row in rows) == ["EXACT_RA", "SOFT_PASS_VARIANT"]
    other = next(row for row in rows if row["status"] == "SOFT_PASS_VARIANT")
    assert "supported" in other["local_verified_variant"]


def test_multi_region_labels_do_not_collapse_to_first_country():
    assert audit32.filename_region("Virtua Fighter (JU).zip") == "Japan, USA"
    assert audit32.filename_region("NBA Jam (JUE).zip") == "Japan, USA, Europe"
    assert audit32.filename_region("Metal Head (Japan, USA).zip") == "Japan, USA"
    assert audit32.filename_region("Tempo (Unknown).zip") == ""


def test_loose_rom_is_not_claimed_as_a_verified_zip(tmp_path):
    folder = tmp_path / "32x"
    folder.mkdir()
    (folder / "Virtua Racing Deluxe (Japan).32x").write_bytes(b"example-rom")
    source = tmp_path / "ra.json"
    catalogue(source, b"other")
    assert audit32.audit(folder, source) == []
