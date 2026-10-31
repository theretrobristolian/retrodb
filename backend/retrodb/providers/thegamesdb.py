"""Opt-in TheGamesDB PS3 metadata cache. No network calls on web requests."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from retrodb.database import get_engine
from retrodb.models import LibraryItem, Platform

CACHE = Path("/var/cache/retrodb/providers/thegamesdb")
API = "https://api.thegamesdb.net/v1.1/Games/ByGameName"
PS3_PLATFORM = 12
FIELDS = "players,publishers,genres,overview,coop,alternates"
IMAGE_LIMIT = 8_000_000


def normalise(value: str) -> str:
    value = re.sub(r"\s*\[(?:BL|BC)[A-Z]{2}\d{5}\]\s*$", "", value, flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def choose_match(title: str, games: list[dict]) -> dict | None:
    """Only exact title/alternative matches on the PS3 platform."""
    wanted = normalise(title)
    matches = []
    for game in games:
        if not isinstance(game, dict) or str(game.get("platform")) != str(PS3_PLATFORM):
            continue
        names = [game.get("game_title", "")]
        alternates = game.get("alternates") or []
        if isinstance(alternates, list):
            names.extend(v if isinstance(v, str) else v.get("name", "") for v in alternates if isinstance(v, (str, dict)))
        if any(normalise(str(v)) == wanted for v in names):
            matches.append(game)
    return matches[0] if len(matches) == 1 else None


def boxart_url(payload: dict, game_id: int) -> str | None:
    included = payload.get("include") or {}
    box = included.get("boxart") or {}
    base = (box.get("base_url") or {}).get("original", "")
    images = (box.get("data") or {}).get(str(game_id), [])
    if not isinstance(images, list):
        return None
    for pic in images:
        if pic.get("type") != "boxart" or pic.get("side") != "front":
            continue
        filename = pic.get("filename", "")
        if (isinstance(base, str) and base.startswith("https://cdn.thegamesdb.net/")
                and isinstance(filename, str) and re.fullmatch(r"[a-zA-Z0-9_./-]{1,250}", filename)
                and ".." not in filename):
            return base.rstrip("/") + "/" + filename.lstrip("/")
    return None


def sync_one(client: httpx.Client, api_key: str, item: LibraryItem) -> str:
    title = re.sub(r"\s*\[(?:BL|BC)[A-Z]{2}\d{5}\]\s*$", "", Path(item.filename).stem, flags=re.I).strip()
    destination = CACHE / f"{item.id}.json"
    if destination.exists():
        return "cached"
    response = client.get(API, params={
        "apikey": api_key, "name": title, "filter[platform]": PS3_PLATFORM,
        "fields": FIELDS, "include": "boxart",
    })
    response.raise_for_status()
    payload = response.json()
    match = choose_match(title, (payload.get("data") or {}).get("games") or [])
    if match is None:
        return "unmatched"
    game_id = int(match["id"])
    picture_url = boxart_url(payload, game_id)
    artwork_filename = ""
    if picture_url:
        try:
            picture = client.get(picture_url)
            picture.raise_for_status()
            data = picture.content
            if 8 <= len(data) <= IMAGE_LIMIT and (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")):
                ext = ".png" if data.startswith(b"\x89PNG") else ".jpg"
                art_path = CACHE / f"{item.id}{ext}"
                art_path.write_bytes(data)
                artwork_filename = art_path.name
        except (httpx.HTTPError, OSError):
            pass
    record = {
        "source": "thegamesdb", "game_id": game_id,
        "title": match.get("game_title"),
        "release_date": match.get("release_date"),
        "players": match.get("players"),
        "publishers": match.get("publishers"),
        "overview": match.get("overview"),
        "genres": match.get("genres"),
        "artwork": artwork_filename,
        "accessories": [],  # Not provided as a structured field by this API.
        "accessories_verified": False,
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(".tmp")
    temp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    temp.replace(destination)
    return "matched"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100 or args.delay < 0.5:
        parser.error("limit must be 1..100, delay at least 0.5")
    key = os.environ.get("RETRODB_THEGAMESDB_API_KEY", "").strip()
    if not key:
        parser.error("RETRODB_THEGAMESDB_API_KEY required")
    CACHE.mkdir(parents=True, exist_ok=True)
    with Session(get_engine()) as db, httpx.Client(timeout=20, follow_redirects=False, headers={"User-Agent": "RetroDB/0.1"}) as client:
        platform = db.scalar(select(Platform).where(Platform.slug == "playstation-3"))
        if platform is None:
            parser.error("PS3 inventory missing; run library scan")
        items = db.scalars(select(LibraryItem).where(
            LibraryItem.platform_id == platform.id, LibraryItem.is_missing.is_(False)
        ).order_by(LibraryItem.id)).all()
        counters = {"matched": 0, "cached": 0, "unmatched": 0, "failed": 0}
        attempted = 0
        for item in items:
            if (CACHE / f"{item.id}.json").exists():
                counters["cached"] += 1
                continue
            if attempted >= args.limit:
                break
            attempted += 1
            try:
                result = sync_one(client, key, item)
            except (httpx.HTTPError, ValueError, OSError) as exc:
                result = "failed"
                print(f"[WARN] {item.filename}: {exc}")
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403, 429):
                    break
            counters[result] += 1
            print(f"{result.upper():9} {item.filename}")
            if attempted < args.limit:
                time.sleep(args.delay)
        print("TheGamesDB PS3 cache:", counters, "| API requests:", attempted)


if __name__ == "__main__":
    main()
