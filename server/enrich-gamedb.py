#!/usr/bin/env python3
"""Enrich indexed PS1/PS2 releases from LizardByte GameDB static JSON.

Default dry-run. --apply writes only unambiguous, exact title + platform matches.
No ROM files or SQL records are modified. Manual --item-id/--game-id supports
ambiguous edition names with operator verification.
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
from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from retrodb.database import get_engine
from retrodb.models import LibraryItem, Platform
from retrodb.providers.lizardbyte import CACHE
from retrodb.web_ui import name

BASE = "https://app.lizardbyte.dev/GameDB"
PLATFORMS = {"playstation": 7, "playstation-2": 8}
ENV = Path("/etc/retrodb/retrodb.env")

def environment():
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k in ("RETRODB_DATABASE_URL", "RETRODB_ENV") and k not in os.environ:
            bits = shlex.split(v.strip())
            if len(bits) == 1:
                os.environ[k] = bits[0]

def norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s).casefold())

def bucket(s):
    parts = re.sub(r"[^a-z0-9 ]+", "", str(s).lower()).strip()
    if not parts:
        return "@"
    if len(parts) == 1 or parts[1] == " ":
        return parts[0]
    return parts[:2]

def get_json(client, uri):
    response = client.get(BASE + uri, timeout=20)
    if response.status_code in (403, 429):
        raise RuntimeError(f"GameDB HTTP {response.status_code}; stop and retry later")
    response.raise_for_status()
    return response.json()

def game_platforms(raw):
    values = raw.get("platforms", [])
    return {int(x.get("id") if isinstance(x, dict) else x) for x in values
            if isinstance(x, int) or (isinstance(x, dict) and str(x.get("id", "")).isdigit())}

def safe_record(raw, platform, title):
    if not isinstance(raw, dict) or PLATFORMS[platform] not in game_platforms(raw):
        return None
    ages = []
    for a in raw.get("age_ratings", []):
        if not isinstance(a, dict):
            continue
        org = a.get("organization")
        rating = a.get("rating_category")
        org = org.get("name") if isinstance(org, dict) else None
        rating = rating.get("rating") if isinstance(rating, dict) else None
        if org in ("ESRB", "PEGI", "CERO", "BBFC") and rating is not None:
            ages.append({"system": org, "rating": str(rating)[:16]})
    modes = sorted({m["name"][:80] for m in raw.get("game_modes", [])
                    if isinstance(m, dict) and isinstance(m.get("name"), str)})
    releases = []
    for row in raw.get("release_dates", []):
        if not isinstance(row, dict):
            continue
        p = row.get("platform")
        p = p.get("id") if isinstance(p, dict) else p
        if str(p) != str(PLATFORMS[platform]):
            continue
        region = row.get("release_region")
        region = region.get("region") if isinstance(region, dict) else None
        year = row.get("y")
        if isinstance(year, int) and 1970 <= year <= 2100:
            releases.append({"region": region, "year": year})
    return {
        "source": "lizardbyte-gamedb", "game_id": int(raw["id"]),
        "matched_title": title, "name": str(raw.get("name") or "")[:250],
        "age_ratings": ages, "game_modes": modes, "release_dates": releases,
        "genres": [str(v["name"])[:80] for v in raw.get("genres", [])
                   if isinstance(v, dict) and isinstance(v.get("name"), str)],
    }

def mark_review(item_id, title, reason, candidates):
    """Keep unresolved matches out of automatic batches; preserve manual review."""
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / f"{item_id}.review.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "status": "needs-review", "title": title, "reason": reason,
        "candidates": candidates[:50],
    }), encoding="utf-8")
    tmp.replace(target)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Write cached matches (otherwise preview only)")
    ap.add_argument("--limit", type=int, default=25, help="Max library items processed")
    ap.add_argument("--item-id", type=int, help="Enrich a particular library record")
    ap.add_argument("--game-id", type=int, help="Exact GameDB game ID; requires --item-id")
    args = ap.parse_args()
    if not 1 <= args.limit <= 100 or (args.game_id and not args.item_id):
        ap.error("--limit must be 1..100; --game-id requires --item-id")
    if os.geteuid() == 0:
        ap.error("Run as the retrodb service user, not root")
    environment()
    with Session(get_engine()) as db:
        rows = db.execute(select(LibraryItem, Platform.slug)
                          .join(Platform, LibraryItem.platform_id == Platform.id)
                          .where(LibraryItem.is_missing.is_(False))
                          .order_by(LibraryItem.id)).all()
    pending = [(item, slug) for item, slug in rows
               if slug in PLATFORMS and (args.item_id == item.id or
                   (args.item_id is None and not (CACHE / f"{item.id}.json").exists()
                    and not (CACHE / f"{item.id}.review.json").exists()))]
    pending = pending[:args.limit]
    print(f"Uncached candidates: {len(pending)} in this batch. apply={args.apply}")
    if not pending:
        return 0
    buckets = {}
    completed = 0
    review = 0
    with httpx.Client(headers={"User-Agent": "RetroDB-GameDB-enrichment/0.1"}, follow_redirects=False) as client:
        for item, platform in pending:
            title = name(item, platform)
            try:
                if args.game_id:
                    ids = [args.game_id]
                else:
                    b = bucket(title)
                    if b not in buckets:
                        buckets[b] = get_json(client, f"/buckets/{b}.json")
                        time.sleep(0.5)
                    entries = buckets[b]
                    ids = [int(id_) for id_, v in entries.items()
                           if isinstance(v, dict) and norm(v.get("name", "")) == norm(title)]
                if len(ids) != 1:
                    print(f"REVIEW {item.id} {title}: {len(ids)} exact title candidates")
                    if args.apply:
                        mark_review(item.id, title, "ambiguous" if ids else "no-exact-match", ids)
                        review += 1
                    continue
                raw = get_json(client, f"/games/{ids[0]}.json")
                if not args.game_id and norm(raw.get("name", "")) != norm(title):
                    print(f"REVIEW {item.id} {title}: returned title differs")
                    if args.apply:
                        mark_review(item.id, title, "title-mismatch", ids)
                        review += 1
                    continue
                record = safe_record(raw, platform, title)
                if not record:
                    print(f"REVIEW {item.id} {title}: platform mismatch")
                    if args.apply:
                        mark_review(item.id, title, "platform-mismatch", ids)
                        review += 1
                    continue
                print(f"MATCH {item.id} {title} -> GameDB {ids[0]}, ratings={len(record['age_ratings'])}, modes={record['game_modes']}")
                if args.apply:
                    CACHE.mkdir(parents=True, exist_ok=True)
                    target = CACHE / f"{item.id}.json"
                    temp = target.with_suffix(".tmp")
                    temp.write_text(json.dumps(record), encoding="utf-8")
                    temp.replace(target)
                    completed += 1
                time.sleep(0.5)
            except RuntimeError as exc:
                print(f"STOP: {exc}", file=sys.stderr)
                return 2
            except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError) as exc:
                print(f"SKIP {item.id}: {type(exc).__name__}")
    print(f"Completed: {completed}; marked for manual review: {review}. Re-run --apply to continue.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
