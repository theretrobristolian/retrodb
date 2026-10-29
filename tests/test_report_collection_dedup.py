"""Ensure report-only duplicate accounting never hides verified multi-disc releases."""
import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "report_excel", Path(__file__).resolve().parents[1] / "server" / "report_excel.py"
)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def entry(name, game_id, state):
    row = [name, name + ".iso", "SLUS-12345", state, "NO", "reason",
           game_id, "", "", "", name, "", "standard", "COUNT"]
    return row


def test_noncompatible_duplicate_excluded_when_verified_release_present():
    pal = entry("007 PAL", "20816", "NO")
    ntsc = entry("007 USA", "20816", "YES")
    result = report.apply_collection_dedup([pal, ntsc])
    assert result[0][13].startswith("EXCLUDE")
    assert result[1][13] == "COUNT — verified"
    assert len([r for r in result if not r[13].startswith("EXCLUDE")]) == 1


def test_two_verified_discs_remain_counted():
    disc_one = entry("Devil May Cry 2 Disc 1", "7153", "YES")
    disc_two = entry("Devil May Cry 2 Disc 2", "7153", "YES")
    assert all(not r[13].startswith("EXCLUDE")
               for r in report.apply_collection_dedup([disc_one, disc_two]))


def test_unverified_pairs_and_unknown_ids_remain_counted():
    rows = [entry("PAL", "3062", "NO"), entry("USA", "3062", "NO"),
            entry("Game A", "", "UNKNOWN"), entry("Game B", "", "UNKNOWN")]
    assert all(not r[13].startswith("EXCLUDE")
               for r in report.apply_collection_dedup(rows))

def test_no_set_is_not_counted_as_ra_ready():
    data = {
        "status": "unmatched", "path": "PS2/Endgame.iso",
        "ra_game_title": "", "recommended_ra_title": "",
        "gamedb_title": "Endgame", "local_friendly_title": "Endgame",
        "preferred_patch_url": "", "local_serial": "SLES-12345",
        "ra_game_id": "", "recommended_ra_game_id": "",
        "preferred_release_name": "", "local_region": "Europe",
        "alternative_candidates": "", "disc_classification": "standard",
        "ra_set_status": "NO_SET", "no_set_ra_game_id": 123,
    }
    row = report.row_for(data)
    assert row[3] == "NO SET"
    assert row[14] == "NO_SET"


def test_no_set_rows_stay_in_effective_denominator():
    good = entry("Game US", "1234", "YES")
    no_set = entry("Endgame", "", "NO SET")
    rows = report.apply_collection_dedup([good, no_set])
    assert len([r for r in rows if not r[13].startswith("EXCLUDE")]) == 2


def test_patch_availability_does_not_imply_source_compatibility():
    data = {
        "status": "unmatched", "path": "PS2/SCES_524.60.Jak 3.iso",
        "local_serial": "SCES-52460", "local_region": "Europe",
        "gamedb_title": "Jak 3", "recommended_ra_title": "Jak 3 (USA)",
        "recommended_ra_game_id": "3065", "ra_game_id": "",
        "preferred_release_name": "Jak 3 (USA) (Debug Patch)",
        "preferred_region": "USA",
        "preferred_patch_url": "https://github.com/RetroAchievements/RAPatches/",
        "ra_set_status": "HAS_SET", "release_guidance": "",
        "alternative_candidates": "",
    }
    row = report.row_for(data)
    assert row[4] == "NO"
    assert row[18] == "AVAILABLE"
    assert "REGION MISMATCH" in row[20]
    assert "do not apply" in row[5]
    assert row[19].startswith("Debug")


def test_source_verified_changes_patch_to_ready_but_not_ra_compatible():
    data = {
        "status": "unmatched", "path": "PS2/SLUS_211.20.Psychonauts.iso",
        "local_serial": "SLUS-21120", "local_region": "USA",
        "gamedb_title": "Psychonauts", "recommended_ra_title": "Psychonauts (USA)",
        "recommended_ra_game_id": "3100", "ra_game_id": "",
        "preferred_release_name": "Psychonauts (USA) (Anti-Cheat)",
        "preferred_region": "USA", "preferred_patch_url": "https://github.com/RetroAchievements/RAPatches/",
        "ra_set_status": "HAS_SET", "release_guidance": "", "alternative_candidates": "",
    }
    source = "/mnt/retrodb-retronas/PS2/SLUS_211.20.Psychonauts.iso"
    row = report.row_for(data, {(source, data["recommended_ra_title"])})
    assert (row[3], row[4], row[18], row[19]) == ("NO", "YES", "READY", "Anti-cheat")


def test_gt2_arcade_not_excluded_by_verified_simulation():
    arcade = entry("GT2 Arcade", "11278", "NO")
    arcade[2] = "SCUS-94455"
    simulation = entry("GT2 Simulation Rev 2", "11278", "YES")
    simulation[2] = "SCUS-94488"
    result = report.apply_collection_dedup([arcade, simulation])
    assert result[0][13] == "COUNT"
    assert result[1][13] == "COUNT — verified"


def test_different_serials_under_same_ra_id_not_deduplicated():
    first = entry("Driver 2 Disc 1", "11588", "YES")
    first[2] = "SLUS-01161"
    second = entry("Driver 2 Disc 2", "11588", "NO")
    second[2] = "SLUS-01318"
    assert report.apply_collection_dedup([first, second])[1][13] == "COUNT"
