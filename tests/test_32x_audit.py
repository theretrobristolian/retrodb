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
