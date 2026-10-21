"""Read-only OPL rename proposal regression checks."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "opl_names", Path(__file__).resolve().parents[1] / "server" / "report_opl_rename.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def sample(path, serial="SLES-12345", title="Example Game"):
    return {"platform": "Sony PlayStation 2", "path": path,
            "local_serial": serial, "gamedb_title": title}

def test_old_naming_and_ra_display_budget():
    row = module.propose([sample("DVD/SLES_123.45.old.ISO".replace(".ISO", ".iso"),
                                title="A Long Name For A PlayStation 2 Game")])[0]
    assert row["Proposed filename"].startswith("SLES_123.45.")
    assert row["Proposed filename"].endswith(".iso")
    assert len(row["Display preview with RA"]) <= 32
    assert row["Title truncated"] == "YES"

def test_regional_serials_remain_separate():
    rows = module.propose([
        sample("DVD/SLES_123.45.Old.iso", "SLES-12345", "Same Game"),
        sample("DVD/SLUS_123.45.Old.iso", "SLUS-12345", "Same Game"),
    ])
    assert all(row["Status"] == "PROPOSED" for row in rows)
    assert rows[0]["Proposed filename"] != rows[1]["Proposed filename"]

def test_collisions_and_no_gamedb_are_not_silently_accepted():
    rows = module.propose([
        sample("DVD/A.iso", title="Same Game"),
        sample("DVD/B.iso", title="Same Game"),
        sample("DVD/C.iso", "SLES-23456", ""),
    ])
    assert [row["Status"] for row in rows] == ["COLLISION", "COLLISION", "REVIEW"]

def test_unicode_titles_transliterate_before_sanitising():
    rows = module.propose([sample("DVD/SLES_544.39.kami.iso", "SLES-54439", "Ōkami")])
    assert rows[0]["Proposed filename"] == "SLES_544.39.Okami.iso"


def test_sega_ages_keeps_volume_and_game_name():
    rows = module.propose([
        sample("DVD/SLPM_624.46.Old.iso", "SLPM-62446",
               "Sega Ages 2500 Series Vol. 10: After Burner II"),
        sample("DVD/SLPM_623.64.Old.iso", "SLPM-62364",
               "Sega Ages 2500 Series Vol. 2: Monaco GP"),
    ])
    for row, number in zip(rows, ("10", "2")):
        assert "Sega Ages " + number in row["Proposed filename"]
        assert len(row["Display preview with RA"]) <= 32
    assert "After Burner 2" in rows[0]["Proposed filename"]
    assert "Monaco GP" in rows[1]["Proposed filename"]

def test_case_only_rename_is_a_normal_proposal():
    rows = module.propose([sample("DVD/SLES_123.45.example game.iso")])
    assert rows[0]["Status"] == "PROPOSED"

def test_no_disc_is_quarantined_from_gamedb_title():
    rows = module.propose([sample("DVD/SLES_528.58.No Disc.iso",
                                  "SLES-52858", "Cocoto Kart Racer")])
    assert rows[0]["Status"] == "REVIEW"
    assert not rows[0]["Proposed filename"]

def test_identical_collision_files_are_manual_duplicate_candidates(tmp_path):
    (tmp_path / "DVD").mkdir()
    for name in ("A.iso", "B.iso"):
        (tmp_path / "DVD" / name).write_bytes(b"same payload")
    rows = module.propose([
        sample("DVD/A.iso", title="Same Game"),
        sample("DVD/B.iso", title="Same Game"),
    ], verify_root=tmp_path)
    assert all(r["Status"] == "COLLISION" for r in rows)
    assert all("IDENTICAL SHA256" in r["Duplicate recommendation"] for r in rows)

def test_different_collision_files_must_not_be_deleted(tmp_path):
    (tmp_path / "DVD").mkdir()
    (tmp_path / "DVD" / "A.iso").write_bytes(b"first")
    (tmp_path / "DVD" / "B.iso").write_bytes(b"second")
    rows = module.propose([
        sample("DVD/A.iso", title="Same Game"),
        sample("DVD/B.iso", title="Same Game"),
    ], verify_root=tmp_path)
    assert all("DIFFERENT SHA256" in r["Duplicate recommendation"] for r in rows)

def test_hyper_street_fighter_keeps_anniversary():
    assert module.compact_title("Hyper Street Fighter II: The Anniversary Edition") == (
        "Hyper Street Fighter II Anniv"
    )

def test_csv_export_uses_excel_utf8_bom(tmp_path):
    import csv
    path = tmp_path / "audit.csv"
    with path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=[
            "platform", "path", "local_serial", "gamedb_title"])
        writer.writeheader()
        writer.writerow(sample("DVD/SLES_123.45.A.iso"))
    output = tmp_path / "export.csv"
    import sys
    original = sys.argv
    try:
        sys.argv = ["report_opl_rename", str(path), str(output)]
        module.main()
    finally:
        sys.argv = original
    assert output.read_bytes().startswith(b"\xef\xbb\xbf")

def test_disc_inspection_reads_system_cnf(tmp_path):
    iso = bytearray(22 * 2048)
    pvd = 16 * 2048
    iso[pvd] = 1
    iso[pvd + 1:pvd + 6] = b"CD001"
    root = pvd + 156
    iso[root + 2:root + 6] = (20).to_bytes(4, "little")
    iso[root + 10:root + 14] = (2048).to_bytes(4, "little")
    directory = 20 * 2048
    name = b"SYSTEM.CNF;1"
    length = 33 + len(name) + (len(name) % 2 == 0)
    iso[directory] = length
    iso[directory + 2:directory + 6] = (21).to_bytes(4, "little")
    payload = b"BOOT2 = cdrom0:\\SLUS_123.45;1\r\n"
    iso[directory + 10:directory + 14] = len(payload).to_bytes(4, "little")
    iso[directory + 32] = len(name)
    iso[directory + 33:directory + 33 + len(name)] = name
    iso[21 * 2048:21 * 2048 + len(payload)] = payload
    path = tmp_path / "Mystery.iso"
    path.write_bytes(iso)
    assert module.inspect_iso(tmp_path, "Mystery.iso") == (
        "SYSTEM.CNF BOOT ID: SLUS_123.45"
    )


def test_curated_opl_display_names_keep_game_identity():
    cases = [["Wacky Races Starring Dastardly & Muttley","Wacky Races Dastardly"],
        ["Ready 2 Rumble Boxing: Round 2","Ready 2 Rumble Round 2"],
        ["18 Wheeler: American Pro Trucker","18 Wheeler Pro Trucker"],
        ["Midnight Club 3: DUB Edition Remix","Midnight Club 3 DUB Remix"],
        ["The Lord of the Rings: The Two Towers","LOTR The Two Towers"],
        ["The Lord of the Rings: The Return of the King","LOTR Return of the King"],
        ["Teenage Mutant Ninja Turtles 3: Mutant Nightmare","TMNT 3 Mutant Nightmare"],
        ["Pinball Hall of Fame: The Williams Collection","Pinball HoF Williams"],
        ["Spider-Man: Web of Shadows: Amazing Allies Edition","Spidey Web of Shadows AA"]]
    for title, expected in cases:
        assert module.compact_title(title) == expected
        assert len(expected) <= module.TITLE_LIMIT


def test_existing_short_titles_remain_intact():
    assert module.compact_title("Guitar Hero: Metallica") == "Guitar Hero Metallica"
    assert module.compact_title("Guitar Hero: Van Halen") == "Guitar Hero Van Halen"


def test_backyard_wrestling_and_arc_pilot_titles():
    cases = [("SLUS-20638", "Backyard Wrestling"),
             ("SCUS-97231", "Arc Lad Twilight Spirits")]
    for serial, title in cases:
        prefix, digits = serial.split("-")
        path = f"DVD/{prefix}_{digits[:3]}.{digits[3:]}.Old.iso"
        row = module.propose([sample(path, serial, "Long game title")])[0]
        assert row["Display preview with RA"] == title + " [RA]"
        assert len(row["Display preview with RA"]) <= 32


def test_second_twenty_title_identity():
    cases = [
        ("SLES-50541", "Capcom vs SNK 2"),
        ("SLUS-21168", "Castlevania Curse Darkness"),
        ("SLUS-21329", "Karaoke Revolution Country"),
    ]
    for serial, expected in cases:
        letters, digits = serial.split("-")
        row = module.propose([sample(
            f"DVD/{letters}_{digits[:3]}.{digits[3:]}.Old.iso",
            serial, "Long verbose catalogue game title"
        )])[0]
        assert row["Display preview with RA"] == expected + " [RA]"
        assert len(row["Display preview with RA"]) <= 32


def test_curated_identity_fixes_for_opl_titles():
    cases = [
        ("Grand Theft Auto: Vice City Stories", "GTA VCS"),
        ("Grand Theft Auto: San Andreas", "GTA San Andreas"),
        ("Lara Croft Tomb Raider: Legend", "Tomb Raider Legend"),
        ("Lara Croft Tomb Raider: Anniversary", "Tomb Raider Anniversary"),
        ("Harry Potter and the Prisoner of Azkaban", "Harry Potter Azkaban"),
        ("Legacy of Kain: Soul Reaver 2", "Soul Reaver 2"),
        ("Resident Evil: Outbreak: File #2", "Resident Evil Outbreak 2"),
        ("WWE SmackDown! Shut Your Mouth", "WWE SmackDown SYM"),
        ("Return to Castle Wolfenstein: Operation Resurrection", "Return Castle Wolfenstein"),
        ("The Suffering: Ties That Bind", "The Suffering 2"),
        ("Tony Hawk's American Wasteland", "Tony Hawks Amer Wasteland"),
    ]
    for source, expected in cases:
        row = module.propose([sample("dvd/SLES_123.45.Old.iso", title=source)])[0]
        assert row["Display preview with RA"] == expected + " [RA]"
        assert len(row["Display preview with RA"]) <= 32
    assert module.compact_title("Hitman 2: Silent Assassin") == "Hitman 2 Silent Assassin"
    assert module.compact_title("Hitman: Blood Money") == "Hitman Blood Money"
