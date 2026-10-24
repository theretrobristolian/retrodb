"""Cross-platform Action Required export checks."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("report_excel", Path(__file__).resolve().parents[1] / "server" / "report_excel.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def entry(filename, status, gameid="", decision="COUNT", patchable="NO"):
    row = ["Test Game", filename, "SLUS-12345", status, patchable, "Review release", gameid, "", "USA", "", "", "", "standard", decision]
    return row + [""] * (len(module.COLS) - len(row))


def test_actions_include_incompatible_and_unknown_but_not_no_set_or_verified():
    entries = [entry("a.iso", "UNKNOWN"), entry("b.iso", "NO"),
               entry("c.iso", "ERROR"), entry("d.iso", "NO SET"), entry("e.iso", "YES")]
    actions = module.action_rows(entries, "Sony PlayStation 2")
    assert {row[2] for row in actions} == {"a.iso", "b.iso", "c.iso"}
    assert all(row[0] == "Sony PlayStation 2" for row in actions)


def test_excludes_duplicate_when_verified_copy_covers_its_ra_id():
    entries = [entry("supported.iso", "YES", "7788"),
               entry("wrong-release.iso", "NO", "7788", "EXCLUDE — compatible copy present")]
    assert module.action_rows(entries, "Sony PlayStation 2") == []


def test_action_sheet_has_identity_and_hash_evidence_columns():
    assert "Platform" in module.ACTION_COLS
    assert "Recommended release" in module.ACTION_COLS
    assert "Local RA hash" in module.ACTION_COLS
    assert "File path" in module.ACTION_COLS


def test_bartis_patch_variant_is_actionable_even_when_not_preferred():
    import tempfile
    import json
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "patch-prepare.json"
        rom = "/mnt/retrodb-retronas/roms/sony/playstation2/dvd/SLUS_202.30.Max Payne.iso"
        source.write_text(json.dumps([{
            "collection_source": rom, "candidate_path": rom,
            "state": "clean-base-verified-ready-to-patch",
            "ra_game_id": "19129",
            "patch_url": "https://github.com/RetroAchievements/RAPatches/raw/main/PS2/Fix/19129-MaxPayne-AntiCheat.zip",
            "required_release": "Max Payne (USA) (Anti-Cheat) (Bartis1989)"
        }]))
        verified = module.patch_sources(source)
        audit = {"platform": "Sony PlayStation 2",
                 "path": "roms/sony/playstation2/dvd/SLUS_202.30.Max Payne.iso",
                 "status": "unmatched", "error": "", "ra_set_status": "HAS_SET",
                 "local_serial": "SLUS-20230",
                 "gamedb_title": "Max Payne", "local_friendly_title": "Max Payne",
                 "preferred_patch_url": "", "recommended_ra_title": "Max Payne",
                 "recommended_ra_game_id": "19129", "ra_game_id": "",
                 "preferred_release_name": "Max Payne (USA) (Cheat Removal Patch)",
                 "local_region": "USA", "preferred_region": "USA",
                 "preferred_ra_labels": "redump", "release_guidance": "",
                 "ra_game_title": "", "identity_resolution": "",
                 "alternative_candidates": "", "identity_review_reason": "",
                 "no_set_ra_game_id": "", "disc_classification": "standard"}
        row = module.row_for(audit, verified)
        assert row[4] == "YES"
        assert "Bartis1989" in row[7]
        assert "exact local source checksum verified" in row[5]
