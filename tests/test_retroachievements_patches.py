import csv
from io import BytesIO
import json
import zipfile

import pytest

from retrodb.retroachievements_patches import (
    PatchError,
    _safe_extract_zip,
    create_patch_plan,
    download_patch_archives,
)


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


def test_patch_download_extracts_archive_and_records_guidance(tmp_path, monkeypatch):
    workspace = tmp_path / "patches"
    write_report(tmp_path / "report.csv", "https://github.com/RetroAchievements/RAPatches/raw/main/test.zip")
    create_patch_plan(tmp_path / "report.csv", tmp_path / "cache", workspace)
    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as bundle:
        bundle.writestr("README.txt", "Use the clean USA image")
        bundle.writestr("fix.xdelta", b"patch")

    def fake_download(url, destination):
        destination.write_bytes(payload.getvalue())

    monkeypatch.setattr("retrodb.retroachievements_patches._download_patch", fake_download)
    result = download_patch_archives(workspace)

    assert result.downloaded == 1
    assert result.failed == 0
    details = json.loads((workspace / "patch-download.json").read_text())
    assert details[0]["guidance_files"] == ["extracted/README.txt"]


def test_patch_download_reuses_existing_archive(tmp_path, monkeypatch):
    workspace = tmp_path / "patches"
    write_report(tmp_path / "report.csv", "https://retroachievements.org/test.zip")
    create_patch_plan(tmp_path / "report.csv", tmp_path / "cache", workspace)
    game_dir = next((workspace / "downloads").iterdir())
    game_dir.joinpath("official-patch.zip").write_bytes(b"existing")
    game_dir.joinpath("extracted").mkdir()
    monkeypatch.setattr(
        "retrodb.retroachievements_patches._download_patch",
        lambda *_: pytest.fail("existing download should be reused"),
    )

    result = download_patch_archives(workspace)

    assert result.reused == 1


def test_safe_extract_rejects_zip_traversal(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", "bad")

    with pytest.raises(PatchError, match="Unsafe path"):
        _safe_extract_zip(archive, tmp_path / "out")
