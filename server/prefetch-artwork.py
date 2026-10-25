#!/usr/bin/env python3
"""Conservative resumable RetroAchievements prefetch for RetroDB's indexed games.

Run as the retrodb service account, not root. Defaults to a 25-game batch with
12 seconds between RA API requests. Stops on rate limiting instead of retry storms.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from retrodb.artwork import RA_CACHE, RA_TTL, ra_image
from retrodb.database import get_engine
from retrodb.models import LibraryItem, Platform
from sqlalchemy import select

ENV_FILE = Path("/etc/retrodb/retrodb.env")
IMAGE_KINDS = {"icon": "ImageIcon", "box": "ImageBoxArt", "title": "ImageTitle", "ingame": "ImageIngame"}
API = "https://retroachievements.org/API/API_GetGameExtended.php"
BULK_API = "https://retroachievements.org/API/API_GetGameList.php"
SYSTEMS = {"playstation": 12, "playstation-2": 21}
BULK_TTL = 30 * 86400
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

def bulk_catalogue(client, platform_slug, key):
    """Store complete per-console catalogue for 30 days; one request per system."""
    system_id = SYSTEMS[platform_slug]
    cache = RA_CACHE / f"catalogue-{system_id}.json"
    try:
        stored = json.loads(cache.read_text(encoding="utf-8"))
        if isinstance(stored, list) and time.time() - cache.stat().st_mtime < BULK_TTL:
            return stored, False
    except (OSError, ValueError):
        pass
    r = client.get(BULK_API, params={"i": system_id, "f": 0, "h": 0, "y": key},
                   timeout=60)
    if r.status_code in (429, 403):
        raise RuntimeError(f"RA bulk HTTP {r.status_code}; STOP. Retry-After: {r.headers.get('Retry-After','unspecified')}")
    r.raise_for_status()
    records = r.json()
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise ValueError("Invalid RA console list response")
    RA_CACHE.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(records), encoding="utf-8")
    tmp.replace(cache)
    return records, True

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
        if target.with_suffix(".missing").is_file():
            continue
        if dry_run:
            count += 1
            continue
        try:
            r = client.get(url)
            if r.status_code in (429, 403):
                raise RuntimeError(f"Image CDN HTTP {r.status_code}; STOP")
            if r.status_code == 404:
                marker = target.with_suffix(".missing")
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.touch()
                continue
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
    p.add_argument("--mode", choices=("icons", "full"), default="icons", help="icons: bulk console list and local icons; full: extended metadata and all art")
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
        records = db.execute(
            select(LibraryItem.ra_game_id, Platform.slug)
            .join(Platform, LibraryItem.platform_id == Platform.id)
            .where(LibraryItem.ra_game_id.is_not(None),
                   LibraryItem.ra_game_id > 0, LibraryItem.is_missing.is_(False))).all()
    per_system = {}
    for game_id, slug in records:
        if slug in SYSTEMS:
            per_system.setdefault(slug, set()).add(int(game_id))
    ids = sorted(set().union(*per_system.values())) if per_system else []
    pending = []
    for game_id in ids:
        data, fresh = cached_metadata(game_id)
        if args.mode == "icons":
            missing = (not artwork_path(game_id, "icon").is_file() and
                       not (RA_CACHE / str(game_id) / "icon.missing").is_file())
            if missing:
                pending.append(game_id)
        else:
            detailed = data.get("_source") != "bulk"
            missing = any(ra_image(data.get(field)) and not artwork_path(game_id, kind).is_file()
                          for kind, field in IMAGE_KINDS.items())
            if args.refresh or not fresh or not detailed or missing:
                pending.append(game_id)
    chosen = pending[:args.limit]
    print(f"Unique indexed RA games: {len(ids)} | pending ({args.mode}): {len(pending)} | batch: {len(chosen)}")
    print(f"Mode: {args.mode} | API spacing: {args.delay:g}s | dry-run: {args.dry_run}")
    if args.dry_run:
        print("Batch IDs:", ", ".join(map(str, chosen)) or "(none)")
        print("Catalogues needed:", ", ".join(s for s in per_system if any(i in per_system[s] for i in chosen)) or "(none)")
        return 0
    downloaded = fetched = errors = 0
    with httpx.Client(timeout=15, follow_redirects=False,
                      headers={"User-Agent": "RetroDB artwork-prefetch/0.2"}) as client:
        bulk = {}
        if args.mode == "icons":
            for slug in per_system:
                if not any(i in per_system[slug] for i in chosen):
                    continue
                try:
                    rows, requested = bulk_catalogue(client, slug, key)
                    bulk.update({int(row["ID"]): row for row in rows
                                 if isinstance(row.get("ID"), int) or str(row.get("ID", "")).isdigit()})
                    fetched += int(requested)
                    print(f"Catalogue {slug}: {len(rows)} entries ({'fetched' if requested else 'cached'})")
                except RuntimeError as exc:
                    print(str(exc), file=sys.stderr)
                    return 2
                except (httpx.HTTPError, ValueError, OSError) as exc:
                    print(f"Catalogue {slug}: {type(exc).__name__}. Stopping.", file=sys.stderr)
                    return 2
                # Separate any console-wide calls even if they are small.
                if requested and len(per_system) > 1:
                    time.sleep(args.delay)
        last_api = 0.0
        for idx, game_id in enumerate(chosen, 1):
            print(f"[{idx}/{len(chosen)}] RA game {game_id}", flush=True)
            data, fresh = cached_metadata(game_id)
            if args.mode == "icons":
                entry = bulk.get(game_id)
                if not entry or not ra_image(entry.get("ImageIcon")):
                    print("    No bulk icon entry available; skipped")
                    marker = RA_CACHE / str(game_id) / "icon.missing"
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.touch()
                    continue
                if not data:
                    data = {"Title": entry.get("Title"), "ImageIcon": entry["ImageIcon"], "_source": "bulk"}
                    RA_CACHE.mkdir(parents=True, exist_ok=True)
                    target = RA_CACHE / f"{game_id}.json"
                    temp = target.with_suffix(".tmp")
                    temp.write_text(json.dumps(data), encoding="utf-8")
                    temp.replace(target)
                elif not ra_image(data.get("ImageIcon")):
                    data["ImageIcon"] = entry["ImageIcon"]
                    target = RA_CACHE / f"{game_id}.json"
                    temp = target.with_suffix(".tmp")
                    temp.write_text(json.dumps(data), encoding="utf-8")
                    temp.replace(target)
                selected = {"ImageIcon": entry["ImageIcon"]}
            else:
                if args.refresh or not fresh or data.get("_source") == "bulk":
                    remaining = args.delay - (time.monotonic() - last_api) if last_api else 0
                    if remaining > 0:
                        time.sleep(remaining)
                    last_api = time.monotonic()
                    try:
                        data = fetch_metadata(client, game_id, key)
                        fetched += 1
                    except RuntimeError as exc:
                        print(str(exc), file=sys.stderr)
                        return 2
                    except (httpx.HTTPError, ValueError, OSError) as exc:
                        errors += 1
                        print(f"    metadata: {type(exc).__name__}; continuing")
                        continue
                selected = data
            try:
                downloaded += fetch_images(client, game_id, selected)
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                return 2
    print(f"Batch finished. API requests: {fetched}; images cached: {downloaded}; metadata failures: {errors}.")
    print("Re-run to advance through remaining games. --mode full fetches individual extended details.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
