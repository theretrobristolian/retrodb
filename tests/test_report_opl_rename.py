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
