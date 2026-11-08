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
