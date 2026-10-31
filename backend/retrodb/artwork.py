"""Cache-first game artwork and metadata from RetroAchievements and PSBBN.

Art is optional; a provider failure must never break the game details page.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from retrodb.database import get_session
from retrodb.models import LibraryItem, Platform

router = APIRouter(include_in_schema=False)
CACHE = Path("/var/cache/retrodb/artwork")
RA_CACHE = CACHE / "ra"
PSBBN_CACHE = CACHE / "psbbn"
PS3_MOUNT = Path("/mnt/retrodb-retronas")
RA_TTL = 30 * 86400
FAIL_TTL = 86400
SERIAL = re.compile(r"^(?:SLUS|SLES|SCES|SCUS|SLPS|SLPM|SCAJ|SCPS|SLKA|SCKA|SCED|SCZS)_[0-9]{3}\.[0-9]{2}$")
RA_IMG = re.compile(r"^/Images/[A-Za-z0-9_-]{1,30}\.png$")
PSBBN_REPO = "https://raw.githubusercontent.com/CosmicScale/psbbn-art-database/main/art"

def serial_key(filename: str) -> str | None:
    match = re.search(r"(SLUS|SLES|SCES|SCUS|SLPS|SLPM|SCAJ|SCPS|SLKA|SCKA|SCED|SCZS)[_. -]*([0-9]{3})[. -]*([0-9]{2})", filename, re.I)
    if not match:
        return None
    return f"{match.group(1).upper()}_{match.group(2)}.{match.group(3)}"

def ra_image(path: object) -> str | None:
    if isinstance(path, str) and RA_IMG.fullmatch(path):
        return "https://media.retroachievements.org" + path
    return None

def _cache_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data), encoding="utf-8")
        temp.replace(path)
    except OSError:
        pass

def game_metadata(game_id: int | None) -> dict:
    if not game_id or game_id < 1:
        return {}
    path = RA_CACHE / f"{game_id}.json"
    old = {}
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - path.stat().st_mtime < RA_TTL:
            return old
    except (OSError, ValueError):
        pass
    key = os.environ.get("RETRODB_RA_API_KEY", "").strip()
    if not key:
        return old
    try:
        with httpx.Client(timeout=5, follow_redirects=False) as client:
            response = client.get("https://retroachievements.org/API/API_GetGameExtended.php",
                                  params={"i": game_id, "y": key},
                                  headers={"User-Agent": "RetroDB/0.1"})
            response.raise_for_status()
            obj = response.json()
        if not isinstance(obj, dict) or str(obj.get("ID")) != str(game_id):
            return old
        allowed = ("Title", "ImageIcon", "ImageBoxArt", "ImageTitle", "ImageIngame",
                   "Publisher", "Developer", "Genre", "Released", "ReleasedAtGranularity")
        data = {k: obj.get(k) for k in allowed}
        _cache_json(path, data)
        return data
    except (httpx.HTTPError, ValueError, OSError):
        return old

@router.get("/art/psbbn/{serial}", include_in_schema=False)
def psbbn_art(serial: str):
    if not SERIAL.fullmatch(serial):
        raise HTTPException(404, "Artwork unavailable")
    path = PSBBN_CACHE / f"{serial}.png"
    if path.is_file() and path.stat().st_size > 0:
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    absent = PSBBN_CACHE / f"{serial}.missing"
    try:
        if absent.exists() and time.time() - absent.stat().st_mtime < FAIL_TTL:
            raise HTTPException(404, "No PSBBN artwork for this release")
    except OSError:
        pass
    try:
        with httpx.Client(timeout=5, follow_redirects=False) as client:
            response = client.get(f"{PSBBN_REPO}/{serial}.png",
                                  headers={"User-Agent": "RetroDB/0.1"})
            response.raise_for_status()
            content = response.content
        if not (content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) < 4_000_000):
            raise ValueError("Unexpected image payload")
        PSBBN_CACHE.mkdir(parents=True, exist_ok=True)
        temp = PSBBN_CACHE / f"{serial}.download"
        temp.write_bytes(content)
        temp.replace(path)
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
    except (httpx.HTTPError, OSError, ValueError):
        try:
            PSBBN_CACHE.mkdir(parents=True, exist_ok=True)
            absent.touch()
        except OSError:
            pass
        raise HTTPException(404, "No PSBBN artwork for this release")


@router.get("/art/ps3/{item_id}", include_in_schema=False)
def ps3_sidecar_art(item_id: int, db: Session = Depends(get_session)):
    """Serve only a matching PNG sidecar of an indexed PS3 ISO, never arbitrary paths."""
    item = db.get(LibraryItem, item_id)
    if item is None or item.is_missing or item.extension.casefold() != "iso":
        raise HTTPException(404, "PS3 artwork unavailable")
    platform = db.get(Platform, item.platform_id)
    if platform is None or platform.slug != "playstation-3":
        raise HTTPException(404, "PS3 artwork unavailable")
    root = PS3_MOUNT
    try:
        mounted_root = root.resolve(strict=True)
        # The scanner records relative paths; use its inventory, not user-supplied filenames.
        iso = (root / item.relative_path).resolve(strict=True)
        if not iso.is_relative_to(mounted_root / "roms/sony/playstation3/iso"):
            raise HTTPException(404, "PS3 artwork unavailable")
        art = iso.with_suffix(".png")
        if art.is_symlink():
            raise HTTPException(404, "PS3 artwork unavailable")
        art = art.resolve(strict=True)
        if not art.is_relative_to(mounted_root / "roms/sony/playstation3/iso"):
            raise HTTPException(404, "PS3 artwork unavailable")
        if not art.is_file() or not 8 <= art.stat().st_size <= 8_000_000:
            raise HTTPException(404, "PS3 artwork unavailable")
        with art.open("rb") as picture:
            if picture.read(8) != b"\x89PNG\r\n\x1a\n":
                raise HTTPException(404, "PS3 artwork unavailable")
    except (OSError, ValueError):
        raise HTTPException(404, "PS3 artwork unavailable")
    return FileResponse(art, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600"})

RA_KINDS = {"icon", "box", "title", "ingame"}

@router.get("/art/ra/{game_id}/{kind}", include_in_schema=False)
def cached_ra_art(game_id: int, kind: str):
    if game_id < 1 or kind not in RA_KINDS:
        raise HTTPException(404, "Artwork unavailable")
    path = RA_CACHE / str(game_id) / (kind + ".png")
    if not path.is_file() or not path.stat().st_size:
        raise HTTPException(404, "Artwork not cached yet")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

def art_location(game_id: int | None, kind: str, provider_path: object) -> str | None:
    remote = ra_image(provider_path)
    if not remote:
        return None
    if game_id and kind in RA_KINDS:
        path = RA_CACHE / str(game_id) / (kind + ".png")
        if path.is_file() and path.stat().st_size:
            return f"/art/ra/{game_id}/{kind}"
    return remote
