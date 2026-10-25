"""Prefetch/cache regression checks without contacting RetroAchievements."""
import json
import importlib.util
from pathlib import Path

from retrodb import artwork

def test_local_art_preferred_with_remote_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(artwork, "RA_CACHE", tmp_path)
    path = tmp_path / "123" / "icon.png"
    source = "/Images/117775.png"
    assert artwork.art_location(123, "icon", source) == "https://media.retroachievements.org" + source
    path.parent.mkdir()
    path.write_bytes(b"\x89PNG\r\n\x1a\nbytes")
    assert artwork.art_location(123, "icon", source) == "/art/ra/123/icon"
    assert artwork.art_location(123, "evil", source).startswith("https://")
    assert artwork.art_location(123, "icon", "https://bad.example/icon") is None

def test_cached_art_route_rejects_invalid_kind(tmp_path, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(artwork, "RA_CACHE", tmp_path)
    try:
        artwork.cached_ra_art(123, "../foo")
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        assert False, "Invalid artwork type was accepted"

def test_batch_script_cache_is_resumable(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("prefetch_artwork", Path(__file__).resolve().parents[1] / "server" / "prefetch-artwork.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "RA_CACHE", tmp_path)
    metadata = {"ImageIcon": "/Images/117775.png", "ImageBoxArt": "/Images/064215.png"}
    (tmp_path / "33.json").write_text(json.dumps(metadata))
    data, fresh = script.cached_metadata(33)
    assert fresh and data == metadata
    assert script.artwork_path(33, "icon") == tmp_path / "33" / "icon.png"
