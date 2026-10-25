#!/usr/bin/env python3
"""Conservative resumable RetroAchievements prefetch for RetroDB's indexed games.

Run as the retrodb service account, not root. Defaults to a 25-game batch with
12 seconds between RA API requests. Stops on rate limiting instead of retry storms.
"""
from __future__ import annotations
import argparse
import json
import os
import random
import re
import shlex
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from retrodb.artwork import RA_CACHE, RA_TTL, ra_image
from retrodb.database import get_engine
from retrodb.models import LibraryItem
from sqlalchemy import select

ENV_FILE = Path("/etc/retrodb/retrodb.env")
IMAGE_KINDS = {"icon": "ImageIcon", "box": "ImageBoxArt", "title": "ImageTitle", "ingame": "ImageIngame"}
API = "https://retroachievements.org/API/API_GetGameExtended.php"
ALLOWED = ("Title", "ImageIcon", "ImageBoxArt", "ImageTitle", "ImageIngame",
           "Publisher", "Developer", "Genre", "Released", "ReleasedAtGranularity")

def read_env():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z_0-9]*", key):
            continue
        try:
            parts = shlex.split(val, comments=False, posix=True)
        except ValueError:
            continue
        if len(parts) == 1:
            os.environ.setdefault(key, parts[0])
        elif not val.strip():
            os.environ.setdefault(key, "")

def cached_metadata(game_id):
    path = RA_CACHE / f"{game_id}.json"
    try:
        val = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(val, dict):
            return val, (time.time() - path.stat().st_mtime < RA_TTL)
    except (OSError, ValueError):
        pass
    return {}, False

def fetch_metadata(client, game_id, key):
    response = client.get(API, params={"i": game_id, "y": key})
    if response.status_code in (429, 403):
        retry = response.headers.get("Retry-After")
        raise RuntimeError(f"RA API HTTP {response.status_code}; STOP. Retry-After: {retry or 'unspecified'}")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or str(data.get("ID")) != str(game_id):
        raise ValueError("Unexpected RA response")
    selected = {k: data.get(k) for k in ALLOWED}
    RA_CACHE.mkdir(parents=True, exist_ok=True)
    path = RA_CACHE / f"{game_id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(selected), encoding="utf-8")
    tmp.replace(path)
    return selected

def artwork_path(game_id, kind):
    return RA_CACHE / str(game_id) / (kind + ".png")

def fetch_images(client, game_id, metadata, *, dry_run=False):
    count = 0
    for kind, key in IMAGE_KINDS.items():
        url = ra_image(metadata.get(key))
        if not url:
            continue
        target = artwork_path(game_id, kind)
        if target.is_file() and target.stat().st_size:
            continue
        if dry_run:
            count += 1
            continue
        try:
            r = client.get(url)
            if r.status_code in (429, 403):
                raise RuntimeError(f"Image CDN HTTP {r.status_code}; STOP")
            r.raise_for_status()
            payload = r.content
            if not (8 < len(payload) <= 4_000_000 and payload.startswith(b"\x89PNG\r\n\x1a\n")):
                raise ValueError("Invalid or oversized PNG")
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(payload)
            tmp.replace(target)
            count += 1
            time.sleep(1)
        except (httpx.HTTPError, ValueError) as exc:
            print(f"    image {kind}: skipped ({type(exc).__name__})", flush=True)
    return count

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=25, help="Max distinct game IDs processed this run (default: 25)")
    p.add_argument("--delay", type=float, default=12, help="Seconds between RA API requests (minimum: 10)")
    p.add_argument("--dry-run", action="store_true", help="Show batch without any network calls or writes")
    p.add_argument("--refresh", action="store_true", help="Re-fetch metadata that is already cached and fresh")
    args = p.parse_args()
    if not 1 <= args.limit <= 100 or args.delay < 10:
        p.error("limit must be 1..100 and delay must be >= 10 seconds")
    if os.geteuid() == 0:
        p.error("Run as the retrodb service account, not root")
    read_env()
    key = os.environ.get("RETRODB_RA_API_KEY", "").strip()
    if not key and not args.dry_run:
        p.error("Missing RETRODB_RA_API_KEY in the service env")
    with get_engine().connect() as db:
        ids = sorted({int(id_) for id_ in db.scalars(
            select(LibraryItem.ra_game_id).where(
                LibraryItem.ra_game_id.is_not(None),
                LibraryItem.ra_game_id > 0,
                LibraryItem.is_missing.is_(False))).all()})
    pending = []
    for game_id in ids:
        data, fresh = cached_metadata(game_id)
        missing_images = any(
            ra_image(data.get(field)) and not artwork_path(game_id, kind).is_file()
            for kind, field in IMAGE_KINDS.items())
        if args.refresh or not fresh or missing_images:
            pending.append((game_id, not fresh or args.refresh))
    chosen = pending[:args.limit]
    print(f"Unique indexed RA games: {len(ids)} | pending: {len(pending)} | batch: {len(chosen)}")
    print(f"API spacing: {args.delay:g}s | dry-run: {args.dry_run} | refresh: {args.refresh}")
    if args.dry_run:
        print("Batch IDs:", ", ".join(str(i) for i, _ in chosen) or "(none)")
        return
    downloaded = 0
    fetched = 0
    errors = 0
    last_call = 0.0
    with httpx.Client(timeout=15, follow_redirects=False, headers={"User-Agent": "RetroDB artwork-prefetch/0.1"}) as client:
        for idx, (game_id, needs_api) in enumerate(chosen, 1):
            print(f"[{idx}/{len(chosen)}] RA game {game_id}", flush=True)
            data, fresh = cached_metadata(game_id)
            if needs_api:
                remaining = args.delay - (time.monotonic() - last_call) if last_call else 0
                if remaining > 0:
                    time.sleep(remaining)
                last_call = time.monotonic()
                try:
                    data = fetch_metadata(client, game_id, key)
                    fetched += 1
                except RuntimeError as exc:
                    print(str(exc), file=sys.stderr)
                    print("Stopped safely. Re-run later; cached entries remain intact.")
                    return 2
                except (httpx.HTTPError, ValueError, OSError) as exc:
                    errors += 1
                    print(f"    metadata: {type(exc).__name__}; continuing", flush=True)
                    continue
            try:
                downloaded += fetch_images(client, game_id, data)
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                return 2
    print(f"Batch finished. Metadata fetched: {fetched}; images cached: {downloaded}; metadata failures: {errors}.")
    print("Re-run the same command to continue with the next pending games.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
