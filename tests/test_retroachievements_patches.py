import csv
import json

from retrodb.retroachievements_patches import create_patch_plan


def write_report(path, patch_url=""):
    fields = [
        "platform", "path", "local_region", "local_ra_hash",
        "recommended_ra_game_id", "recommended_ra_title",
        "preferred_release_name", "preferred_region", "preferred_ra_hash",
        "preferred_ra_labels", "preferred_patch_url",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "platform": "Sony PlayStation",
            "path": "roms/sony/playstation1/iso/Crash Bash.cue",
            "local_region": "USA",
            "local_ra_hash": "1" * 32,
            "recommended_ra_game_id": "10907",
            "recommended_ra_title": "Crash Bash",
            "preferred_release_name": "Crash Bash (USA) (Menu Glitch Fix)",
            "preferred_region": "USA",
            "preferred_ra_hash": "2" * 32,
            "preferred_ra_labels": "rapatches; redump",
            "preferred_patch_url": patch_url,
        })


def test_patch_plan_creates_guidance_without_copying_roms(tmp_path):
    report = tmp_path / "report.csv"
    write_report(report, "https://retroachievements.org/patches/crash-bash.zip")
    workspace = tmp_path / "patches"

    result = create_patch_plan(report, tmp_path / "cache", workspace)

    assert result.patches == 1
    assert result.official_links == 1
    manifest = json.loads((workspace / "patch-plan.json").read_text())
    assert manifest[0]["expected_ra_hash"] == "2" * 32
    assert list((workspace / "incoming").iterdir()) == []
    readme = next((workspace / "downloads").glob("*/README.md")).read_text()
    assert "RetroNAS mount remains read-only" in readme


def test_patch_plan_rejects_untrusted_patch_url(tmp_path):
    report = tmp_path / "report.csv"
    write_report(report, "https://example.invalid/suspicious.zip")

    result = create_patch_plan(report, tmp_path / "cache", tmp_path / "patches")

    assert result.official_links == 0
