"""Sega 32X outer-ZIP naming: preview, conservative exceptions and safe apply."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

import pytest

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))
spec = importlib.util.spec_from_file_location("sega32x_rename", SERVER / "sega32x_rename.py")
naming = importlib.util.module_from_spec(spec)
spec.loader.exec_module(naming)


def fixture(tmp_path, source="[32X] Knuckles' Chaotix (Japan, USA) (En).zip"):
    root = tmp_path / "32x"
    root.mkdir()
    rom = b"known-registered-rom"
    with zipfile.ZipFile(root / source, "w") as archive:
        archive.writestr("Original Internal Name (En).32x", rom)
    ra = tmp_path / "ra.json"
    ra.write_text(json.dumps([{
        "ID": 88, "Title": "Knuckles' Chaotix",
        "ConsoleID": 10, "NumAchievements": 12,
        "Hashes": [hashlib.md5(rom).hexdigest()],
    }]), encoding="utf-8")
    return root, ra, rom


def test_concise_no_intro_inspired_names():
    target, reason = naming.canonical_name(
        "[32X] Knuckles' Chaotix (Japan, USA) (En).zip", "Knuckles' Chaotix"
    )
    assert target == "Knuckles' Chaotix (Japan, USA).zip"
    assert not reason
    target, reason = naming.canonical_name("Virtua Fighter (JU).zip")
    assert target == "Virtua Fighter (Japan, USA).zip"
    assert not reason
    target, reason = naming.canonical_name("After Burner Complete (USA) (En,Fr).zip")
    assert target == "After Burner Complete (USA).zip"
    assert not reason
    target, reason = naming.canonical_name(
        "[32X] Amazing Spider-Man, The - Web of Fire (USA).zip",
        "The Amazing Spider-Man: Web of Fire",
    )
    assert target == "The Amazing Spider-Man - Web of Fire (USA).zip"
    assert not reason
    target, reason = naming.canonical_name(
        "[32X] Knuckles' Chaotix (U) ~ Chaotix (J).zip",
        "Knuckles' Chaotix",
        "Japan, USA",
    )
    assert target == "Knuckles' Chaotix (Japan, USA).zip"
    assert not reason


@pytest.mark.parametrize("filename", [
    "Doom (Europe) (Rev 1).zip",
    "Soul Star X (USA) (Proto).zip",
    "Doom (USA) (Hack).zip",
    "[32X] Doom (Europe) [Patch Ressurrection v3.1].zip",
    "[32X] Soulstar X (USA) (Proto).zip",
    "Doom.zip",
])
def test_special_variants_and_missing_region_not_renamed(filename):
    assert naming.canonical_name(filename)[0] == ""


def test_preview_does_not_modify_zip_and_apply_only_changes_outer_name(tmp_path):
    root, ra, rom = fixture(tmp_path)
    original = next(root.glob("*.zip"))
    before = original.read_bytes()
    rows = naming.plan(root, ra)
    assert len(rows) == 1
    assert rows[0]["status"] == "RENAME_CANDIDATE"
    assert rows[0]["target"] == "Knuckles' Chaotix (Japan, USA).zip"
    assert original.read_bytes() == before
    journal = tmp_path / "journal.json"
    assert naming.apply(root, rows, journal) == 1
    dest = root / rows[0]["target"]
    assert dest.read_bytes() == before
    assert not original.exists()
    with zipfile.ZipFile(dest) as archive:
        assert archive.namelist() == ["Original Internal Name (En).32x"]
        assert archive.read(archive.namelist()[0]) == rom
    assert json.loads(journal.read_text())["operations"][0]["state"] == "done"
    assert naming.plan(root, ra)[0]["status"] == "VALID"


def test_collision_never_overwrites_an_existing_zip(tmp_path):
    root, ra, _ = fixture(tmp_path)
    destination = root / "Knuckles' Chaotix (Japan, USA).zip"
    destination.write_bytes(b"existing-destination")
    rows = naming.plan(root, ra)
    candidate = next(row for row in rows if row["source"].startswith("[32X]"))
    assert candidate["status"] == "REVIEW_COLLISION"
    assert naming.apply(root, rows, tmp_path / "journal.json") == 0
    assert destination.read_bytes() == b"existing-destination"


def test_rejects_source_changed_after_preview(tmp_path):
    root, ra, _ = fixture(tmp_path)
    rows = naming.plan(root, ra)
    next(root.glob("*.zip")).unlink()
    with pytest.raises(ValueError, match="Source or destination changed"):
        naming.apply(root, rows, tmp_path / "journal.json")


def test_registered_hash_region_used_only_for_exact_rom(tmp_path):
    root, ra, rom = fixture(tmp_path, source="[32X] Knuckles' Chaotix (En).zip")
    hash_dir = tmp_path / "hashes"
    hash_dir.mkdir()
    (hash_dir / "88.json").write_text(json.dumps([{
        "Name": "Knuckles' Chaotix (Japan, USA) (En).32x",
        "MD5": hashlib.md5(rom).hexdigest(),
    }]))
    rows = naming.plan(root, ra, hash_dir)
    assert rows[0]["status"] == "RENAME_CANDIDATE"
    assert rows[0]["target"] == "Knuckles' Chaotix (Japan, USA).zip"
    with zipfile.ZipFile(next(root.glob("*.zip")), "w") as archive:
        archive.writestr("Original Internal Name (En).32x", b"different-unverified")
    rows = naming.plan(root, ra, hash_dir)
    assert rows[0]["status"] == "REVIEW"
    assert "region" in rows[0]["reason"].lower()

def test_hash_region_conflict_requires_review():
    name, reason = naming.canonical_name(
        "Some Game (Europe).zip", "Some Game", "USA",
    )
    assert not name
    assert "conflicts" in reason

