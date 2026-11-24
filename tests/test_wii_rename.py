"""Wii folder renamer: preview-first, disc ID safety and WBFS preservation."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("wii_rename", ROOT / "wii_rename.py")
rename = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rename)
from report_wii_audit import gametdb_titles


def make_game(root, title="TRAUMA TEAM", disc_id="SK3EEB"):
    folder = root / f"{title} [{disc_id}]"
    folder.mkdir()
    image = folder / f"{disc_id}.wbfs"
    image.write_bytes(b"WBFS_CONTENT_UNCHANGED")
    (folder / "notes.txt").write_text("Sidecar must stay")
    return folder


def test_title_case_all_caps_and_id_preservation(tmp_path):
    make_game(tmp_path, "SUPER MONKEY BALL BANANA BLITZ", "RSME8P")
    make_game(tmp_path, "TRAUMA TEAM", "SK3EEB")
    rows = rename.plan(tmp_path)
    assert [r["target"] for r in rows] == [
        "Super Monkey Ball Banana Blitz [RSME8P]",
        "Trauma Team [SK3EEB]",
    ]
    assert all(r["status"] == "RENAME_CANDIDATE" for r in rows)


def test_preserve_mixed_case_without_authoritative_metadata(tmp_path):
    make_game(tmp_path, "Trauma Center SO", "RKDEEB")
    row = rename.plan(tmp_path)[0]
    assert row["status"] == "VALID"
    assert not row["target"]


def test_exact_gametdb_id_overrides_incorrect_and_allcaps_title(tmp_path):
    make_game(tmp_path, "TRAUMA CENTER NEW BLOOD", "RK2EEB")
    db = tmp_path / "wiitdb.txt"
    db.write_text("TITLES = https://www.gametdb.com\nRK2EEB = Trauma Center: New Blood\n")
    assert gametdb_titles(db)["RK2EEB"] == "Trauma Center: New Blood"
    row = rename.plan(tmp_path, db)[0]
    assert row["target"] == "Trauma Center - New Blood [RK2EEB]"
    assert row["reason"] == "GameTDB disc ID"


def test_folder_only_move_preserves_wbfs_and_sidecar_bytes(tmp_path):
    src = make_game(tmp_path)
    before = (src / "SK3EEB.wbfs").read_bytes()
    rows = rename.plan(tmp_path)
    journal = tmp_path.parent / "wii-rename-journal.json"
    assert rename.apply(tmp_path, rows, journal) == 1
    dest = tmp_path / "Trauma Team [SK3EEB]"
    assert not src.exists()
    assert (dest / "SK3EEB.wbfs").read_bytes() == before
    assert (dest / "notes.txt").read_text() == "Sidecar must stay"
    assert json.loads(journal.read_text())["operations"][0]["state"] == "done"
    assert rename.plan(tmp_path)[0]["status"] == "VALID"


def test_collision_never_overwrites_target(tmp_path):
    make_game(tmp_path)
    target = tmp_path / "Trauma Team [SK3EEB]"
    target.mkdir()
    rows = rename.plan(tmp_path)
    source = next(r for r in rows if r["source"] == "TRAUMA TEAM [SK3EEB]")
    assert source["status"] == "REVIEW_COLLISION"
    assert not (target / "SK3EEB.wbfs").exists()
    assert rename.apply(tmp_path, rows, tmp_path.parent / "none.json") == 0


def test_wrong_disc_id_and_multiple_images_require_review(tmp_path):
    folder = make_game(tmp_path)
    (folder / "SK3EEE.iso").write_bytes(b"another-image")
    row = rename.plan(tmp_path)[0]
    assert row["status"] == "REVIEW"
    assert "one primary" in row["reason"]


def test_recheck_detects_removed_source_after_preview(tmp_path):
    src = make_game(tmp_path)
    proposal = rename.plan(tmp_path)
    (src / "SK3EEB.wbfs").unlink()
    with pytest.raises(ValueError):
        rename.apply(tmp_path, proposal, tmp_path.parent / "do-not-create.json")


def test_gametdb_txt_format_with_wrong_id_is_ignored(tmp_path):
    make_game(tmp_path)
    db = tmp_path / "wii.txt"
    db.write_text("ZZZZZZ = Wrong Title\n")
    row = rename.plan(tmp_path, db)[0]
    assert row["target"] == "Trauma Team [SK3EEB]"


def test_folder_symlink_never_traversed(tmp_path):
    outside = tmp_path.parent / "external-game"
    outside.mkdir(exist_ok=True)
    (tmp_path / "Fake [ABCDEFG]").symlink_to(outside, target_is_directory=True)
    assert rename.plan(tmp_path) == []


def test_case_only_change_not_applied_over_smb(tmp_path):
    make_game(tmp_path, "trauma team", "SK3EEB")
    row = rename.plan(tmp_path)[0]
    assert row["status"] == "VALID"


def test_existing_journal_prevents_repeat(tmp_path):
    make_game(tmp_path)
    journal = tmp_path.parent / "existing.json"
    journal.write_text("{}")
    with pytest.raises(ValueError, match="journal"):
        rename.apply(tmp_path, rename.plan(tmp_path), journal)

def test_menu_integrates_wii_and_32x_without_duplicate_more_options():
    menu = (ROOT / 'manager.sh').read_text(encoding='utf-8')
    assert 'step "9/10" "Audit Sega 32X' in menu
    assert 'step "10/10" "Audit Nintendo Wii' in menu
    assert "echo ' 11) Audit Sega 32X" not in menu
    assert "echo ' 12) Audit Nintendo Wii" not in menu
    assert '5) run wii_rename' in menu
