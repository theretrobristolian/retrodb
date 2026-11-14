"""Unit tests for the standalone, non-destructive xeRAbora memory-card manager."""
import importlib.util
import os
from pathlib import Path
import stat
import zipfile

import pytest


MODULE = Path(__file__).resolve().parents[1] / "integrations" / "xerabora" / "memcard.py"
spec = importlib.util.spec_from_file_location("xerabora_memcard", MODULE)
memcard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memcard)


def test_rejects_invalid_image_size(tmp_path):
    image = tmp_path / "bad.mc2"
    image.write_bytes(b"not a memory card")
    with pytest.raises(ValueError, match="Unexpected"):
        memcard.validate_image(image)


def test_selects_mc2_from_offline_zip_without_extracting_paths(tmp_path, monkeypatch):
    cache = tmp_path / "private"
    monkeypatch.setattr(memcard, "CACHE", cache)
    archive_path = tmp_path / "FreeMcBoot.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../../evil.mc2", b"A" * (8 * 1024 * 1024))
        archive.writestr("metadata.txt", b"text")
    monkeypatch.setattr(memcard, "ask", lambda *a, **kw: "1")
    selected = memcard.offline_source(str(archive_path))
    assert selected.parent == cache
    assert selected.stat().st_size == 8388608
    assert not (tmp_path / "evil.mc2").exists()


def test_does_not_overwrite_existing_output(tmp_path, monkeypatch):
    src = tmp_path / "original.mc2"
    src.write_bytes(b"0" * (8 * 1024 * 1024))
    out = tmp_path / "existing.mc2"
    out.write_bytes(b"unchanged")
    with pytest.raises(FileExistsError):
        memcard.build_image(src, {}, out)
    assert out.read_bytes() == b"unchanged"


def test_output_directory_retains_existing_share_permissions(tmp_path):
    src = tmp_path / "original.mc2"
    src.write_bytes(b"0" * (8 * 1024 * 1024))
    folder = tmp_path / "shared"
    folder.mkdir()
    folder.chmod(0o775)
    # Test the working copy path with no ELF changes; mymc check is mocked.
    original_mymc = memcard.run_mymc
    memcard.run_mymc = lambda *_: None
    try:
        image = memcard.build_image(src, {}, folder / "patched.mc2")
        assert image.is_file()
        assert stat.S_IMODE(folder.stat().st_mode) == 0o775
    finally:
        memcard.run_mymc = original_mymc


def test_config_file_is_private(tmp_path, monkeypatch):
    monkeypatch.setattr(memcard, "APP", tmp_path / "config")
    monkeypatch.setattr(memcard, "CONFIG", tmp_path / "config" / "config.json")
    memcard.save_config({"host": "192.0.2.15", "username": "ps2"})
    assert stat.S_IMODE(memcard.CONFIG.stat().st_mode) == 0o600
    assert memcard.config()["host"] == "192.0.2.15"

def test_release_identity_rejects_mismatched_elf(tmp_path):
    import hashlib
    folder = tmp_path / "v1.1.0"
    folder.mkdir()
    elf = folder / "OPL-RA.ELF"
    elf.write_bytes(b"older")
    digest = hashlib.sha256(b"expected").hexdigest()
    (folder / "SHA256SUMS").write_text(f"{digest}  OPL-RA.ELF\\n")
    assert memcard.release_identity(folder) is None


def test_verified_card_is_skipped_before_upload(tmp_path, monkeypatch):
    import hashlib
    filename = "OPL-RA.ELF"
    binary = tmp_path / filename
    binary.write_bytes(b"new")
    same = memcard.digest(binary)
    monkeypatch.setattr(memcard, "choose_elfs", lambda: ({filename: binary}, {filename: same}))
    monkeypatch.setattr(memcard, "config", lambda: {
        "host": "192.0.2.100",
        "remote": "/PS2/MemoryCard1/MemoryCard1-1.mc2",
        "output_dir": str(tmp_path / "out"),
    })
    monkeypatch.setattr(memcard, "CACHE", tmp_path / "cache")
    class FakeFTP:
        def close(self): pass
    monkeypatch.setattr(memcard, "ftp_connect", lambda d: FakeFTP())
    monkeypatch.setattr(memcard, "backup_remote", lambda ftp, d, dest: (
        dest.parent.mkdir(parents=True, exist_ok=True),
        dest.write_bytes(b"0" * (8 * 1024 * 1024))))
    monkeypatch.setattr(memcard, "display_image_comparison",
                        lambda image, binaries, reference: {filename: same})
    def forbid_build(*args):
        raise AssertionError("Already-matching ELF must not create or upload an image")
    monkeypatch.setattr(memcard, "build_image", forbid_build)
    memcard.update_ftp()


def test_old_cache_cleanup_preserves_private_backups(tmp_path, monkeypatch):
    import hashlib
    cache = tmp_path / "cache"
    cache.mkdir()
    old = cache / "v1.1.0"
    old.mkdir()
    older = b"older"
    (old / "OPL-RA.ELF").write_bytes(older)
    (old / "SHA256SUMS").write_text(
        hashlib.sha256(older).hexdigest() + "  OPL-RA.ELF\\n")
    latest = cache / "v2.0.0"
    latest.mkdir()
    (latest / "OPL-RA.ELF").write_bytes(b"latest")
    (latest / "SHA256SUMS").write_text(
        hashlib.sha256(b"latest").hexdigest() + "  OPL-RA.ELF\\n")
    backup = cache / "backups"
    backup.mkdir()
    (backup / "keep.mc2").write_bytes(b"private")
    output = cache / "output"
    output.mkdir()
    (output / "keep.mc2").write_bytes(b"patched")
    monkeypatch.setattr(memcard, "CACHE", cache)
    monkeypatch.setattr(memcard, "current_release",
                        lambda: (latest, {"OPL-RA.ELF": memcard.digest(latest / "OPL-RA.ELF")}))
    monkeypatch.setattr("builtins.input", lambda *_: "CLEAN OLD RELEASES")
    memcard.cleanup_old_releases()
    assert not old.exists()
    assert latest.exists()
    assert (backup / "keep.mc2").read_bytes() == b"private"
    assert (output / "keep.mc2").read_bytes() == b"patched"
