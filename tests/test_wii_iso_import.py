"""Wii ISO intake: internal header identity, no overwrites, journalled moves."""
import json
from pathlib import Path
import sys

import pytest

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from wii_iso_import import plan, apply
from wii_rename import plan as rename_plan
from report_wii_audit import audit as wii_audit


def make_iso(root, name="random-name.iso", ident="RMCP01"):
    header = bytearray(0x100)
    header[:6] = ident.encode("ascii")
    header[0x18:0x1c] = bytes.fromhex("5d1c9ea3")
    p = root / name
    p.write_bytes(bytes(header) + b"PAYLOAD_PRESERVED")
    return p


def titles(tmp_path):
    p = tmp_path.parent / (tmp_path.name + "-titles.txt")
    p.write_text("RMCP01 = Mario Kart Wii\nSK3EEB = Trauma Team\n", encoding="utf-8")
    return p


def test_create_new_gametdb_folder_and_preserve_bytes(tmp_path):
    src = make_iso(tmp_path, "whatever.iso")
    original = src.read_bytes()
    db = titles(tmp_path)
    rows = plan(tmp_path, db)
    assert rows[0]["status"] == "IMPORT_CANDIDATE"
    assert rows[0]["target"] == "Mario Kart Wii [RMCP01]/RMCP01.iso"
    journal = tmp_path.parent / (tmp_path.name + "-import-new.json")
    assert apply(tmp_path, rows, journal, db) == 1
    dest = tmp_path / "Mario Kart Wii [RMCP01]" / "RMCP01.iso"
    assert dest.read_bytes() == original
    assert not src.exists()
    assert json.loads(journal.read_text())["operations"][0]["state"] == "done"
    assert rename_plan(tmp_path, db)[0]["status"] == "VALID"


def test_import_beside_wbfs_without_changing_existing_game(tmp_path):
    folder = tmp_path / "Mario Kart Wii [RMCP01]"
    folder.mkdir()
    (folder / "RMCP01.wbfs").write_bytes(b"ORIGINAL WBFS")
    src = make_iso(tmp_path, "my-pal-game.iso")
    db = titles(tmp_path)
    rows = plan(tmp_path, db)
    assert apply(tmp_path, rows, tmp_path.parent / (tmp_path.name + "-beside.json"), db) == 1
    assert (folder / "RMCP01.wbfs").read_bytes() == b"ORIGINAL WBFS"
    assert (folder / "RMCP01.iso").read_bytes() == src.read_bytes() if src.exists() else (folder / "RMCP01.iso").is_file()
    assert rename_plan(tmp_path, db)[0]["status"] == "VALID"
    assert len(wii_audit(tmp_path, None, db)) == 2


def test_refuse_existing_iso_collision(tmp_path):
    folder = tmp_path / "Mario Kart Wii [RMCP01]"
    folder.mkdir()
    (folder / "RMCP01.iso").write_bytes(b"KEEP")
    src = make_iso(tmp_path)
    rows = plan(tmp_path, titles(tmp_path))
    assert rows[0]["status"] == "REVIEW"
    assert "exists" in rows[0]["reason"]
    assert apply(tmp_path, rows, tmp_path.parent / (tmp_path.name + "-collision.json")) == 0
    assert src.is_file()
    assert (folder / "RMCP01.iso").read_bytes() == b"KEEP"


def test_reject_changed_source_after_preview(tmp_path):
    src = make_iso(tmp_path)
    db = titles(tmp_path)
    rows = plan(tmp_path, db)
    src.write_bytes(src.read_bytes() + b"changed")
    journal = tmp_path.parent / (tmp_path.name + "-changed.json")
    with pytest.raises(ValueError, match="changed"):
        apply(tmp_path, rows, journal, db)
    assert not journal.exists()


def test_invalid_or_uncatalogued_header_never_imported(tmp_path):
    bad = make_iso(tmp_path, "bad.iso", "RMCP01")
    blob = bytearray(bad.read_bytes())
    blob[0x18:0x1c] = b"NOPE"
    bad.write_bytes(blob)
    assert plan(tmp_path, titles(tmp_path))[0]["status"] == "REVIEW"
    bad.unlink()
    make_iso(tmp_path, "unknown.iso", "ZZZZZZ")
    assert plan(tmp_path, titles(tmp_path))[0]["status"] == "REVIEW"


def test_existing_disc_id_folder_not_title_based(tmp_path):
    folder = tmp_path / "An Older Mario Kart Name [RMCP01]"
    folder.mkdir()
    (folder / "RMCP01.wbfs").write_bytes(b"KEEP")
    make_iso(tmp_path)
    rows = plan(tmp_path, titles(tmp_path))
    assert rows[0]["target"] == "An Older Mario Kart Name [RMCP01]/RMCP01.iso"


def test_duplicate_same_id_root_isos_are_rejected_before_journal(tmp_path):
    make_iso(tmp_path, "first.iso")
    make_iso(tmp_path, "second.iso")
    db = titles(tmp_path)
    rows = plan(tmp_path, db)
    journal = tmp_path.parent / (tmp_path.name + "-duplicate.json")
    with pytest.raises(ValueError, match="same destination"):
        apply(tmp_path, rows, journal, db)
    assert not journal.exists()


def test_import_menu_uses_temporary_mount_and_explicit_confirm():
    text = (SERVER / "manager.sh").read_text(encoding="utf-8")
    section = text.split("wii_rename() {", 1)[1].split("wii_audit() {", 1)[0]
    assert 'wii_iso_import.py" preview' in section
    assert 'wii_iso_import.py" apply' in section
    assert '--confirm "IMPORT WII"' in section
    assert 'sudo umount "$PILOT_ROOT"' in section
