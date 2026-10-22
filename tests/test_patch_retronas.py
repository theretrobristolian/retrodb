"""Local-filesystem regression checks for the single-ISO RetroNAS patch action."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server import patch_retronas as deploy


def fixture(tmp_path, monkeypatch, region="USA"):
    nas = tmp_path / "nas"
    iso = nas / "roms" / "dvd" / "SLUS_972.65.Jak II.iso"
    iso.parent.mkdir(parents=True)
    iso.write_bytes(b"clean source")
    work = tmp_path / "work"
    work.mkdir()
    plan = [{
        "ra_game_id": "3062",
        "title": "Jak II (USA) (Debug Patch)",
        "platform": "Sony PlayStation 2",
        "local_path": "roms/dvd/SLUS_972.65.Jak II.iso",
        "local_region": region,
        "required_region": "USA",
        "expected_ra_hash": "a" * 32,
    }]
    prepared = [{
        "title": plan[0]["title"],
        "state": "clean-base-verified-ready-to-patch",
        "candidate_path": str(iso),
        "collection_source": str(iso),
    }]
    (work / "patch-plan.json").write_text(json.dumps(plan))
    (work / "patch-prepare.json").write_text(json.dumps(prepared))
    patch = tmp_path / "source.xdelta"
    patch.write_bytes(b"xdelta")
    monkeypatch.setattr(deploy, "_current_xdelta", lambda *args: patch)
    monkeypatch.setattr(deploy, "_source_requirements", lambda *args: {"md5": "unused"})
    monkeypatch.setattr(deploy, "_validate_source", lambda *args: (True, "md5", "verified"))
    monkeypatch.setattr(deploy, "hash_file", lambda hasher, console, path: (
        "a" * 32 if Path(path).read_bytes() == b"patched source" else "b" * 32
    ))
    def fake_xdelta(command, **kwargs):
        Path(command[-1]).write_bytes(b"patched source")
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(deploy.subprocess, "run", fake_xdelta)
    args = SimpleNamespace(workspace=work, mount=nas, read_mount=nas,
                           game_id="3062", journal=tmp_path / "journal.json",
                           hasher=tmp_path / "hasher", dry_run=False)
    return args, iso


def test_success_retains_original_backup(tmp_path, monkeypatch):
    args, iso = fixture(tmp_path, monkeypatch)
    deploy.deploy(args)
    assert iso.read_bytes() == b"patched source"
    assert iso.with_name("OLD_" + iso.name).read_bytes() == b"clean source"
    assert json.loads(args.journal.read_text())["state"] == "verified-on-retronas"


def test_dry_run_writes_no_backup(tmp_path, monkeypatch):
    args, iso = fixture(tmp_path, monkeypatch)
    args.dry_run = True
    deploy.deploy(args)
    assert iso.read_bytes() == b"clean source"
    assert not iso.with_name("OLD_" + iso.name).exists()


def test_region_mismatch_refused_before_any_write(tmp_path, monkeypatch):
    args, iso = fixture(tmp_path, monkeypatch, region="Europe")
    with pytest.raises(deploy.PatchError, match="region mismatch"):
        deploy.deploy(args)
    assert iso.read_bytes() == b"clean source"
    assert not args.journal.exists()


def test_existing_backup_is_never_overwritten(tmp_path, monkeypatch):
    args, iso = fixture(tmp_path, monkeypatch)
    iso.with_name("OLD_" + iso.name).write_bytes(b"existing archive")
    with pytest.raises(deploy.PatchError, match="already exists"):
        deploy.deploy(args)
    assert iso.read_bytes() == b"clean source"
    assert iso.with_name("OLD_" + iso.name).read_bytes() == b"existing archive"
