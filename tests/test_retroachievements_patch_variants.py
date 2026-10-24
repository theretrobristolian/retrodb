"""Patch discovery must inspect all official RA patch versions for a game."""
import json
from pathlib import Path
from retrodb.retroachievements_patches import _patch_rows


def test_nonpreferred_bartis_patch_variant_is_discovered(tmp_path):
    cache = tmp_path / "cache"
    (cache / "games").mkdir(parents=True)
    (cache / "games" / "19129.json").write_text(json.dumps([
        {"Name": "Max Payne (USA) (Cheat Removal Patch)",
         "MD5": "3d20201061a2f53ad2b079e69b94a7f5", "Labels": ["redump"]},
        {"Name": "Max Payne (USA) (Anti-Cheat) (Bartis1989)",
         "MD5": "dd5f58908acd8062a13551de7a1d5fbe",
         "Labels": ["redump", "rapatches"],
         "PatchUrl": "https://github.com/RetroAchievements/example/releases/download/19129/patch.zip"},
    ]))
    import csv
    report = tmp_path / "audit.csv"
    with report.open("w", newline="") as fp:
        fields = ["recommended_ra_game_id", "recommended_ra_title", "preferred_ra_hash",
                  "preferred_ra_labels", "path", "platform", "local_region"]
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"recommended_ra_game_id": "19129",
                         "recommended_ra_title": "Max Payne",
                         "preferred_ra_hash": "3d20201061a2f53ad2b079e69b94a7f5",
                         "preferred_ra_labels": "redump",
                         "path": "roms/sony/playstation2/dvd/SLUS_202.30.Max Payne.iso",
                         "platform": "Sony PlayStation 2", "local_region": "USA"})
    result = _patch_rows(report, cache)
    assert len(result) == 1
    assert result[0]["preferred_ra_hash"] == "dd5f58908acd8062a13551de7a1d5fbe"
    assert "Bartis1989" in result[0]["preferred_release_name"]
    assert result[0]["preferred_patch_url"].startswith("https://github.com/")
