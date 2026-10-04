"""Hash local disc images with rcheevos and match cached RetroAchievements data."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import re
import subprocess
from sqlalchemy import select
from sqlalchemy.orm import Session
from retrodb.models import LibraryItem, Platform

HASH_PATTERN = re.compile(r"\b([0-9a-fA-F]{32})\b")
HASH_TARGET_EXTENSIONS = {"playstation": {"cue"}, "playstation-2": {"iso"}}

class MatchError(RuntimeError):
    pass

@dataclass(frozen=True)
class MatchSummary:
    platform: str
    candidates: int
    matched: int
    unmatched: int
    failed: int
    cached: int

def extract_hash(output: str) -> str:
    matches = HASH_PATTERN.findall(output)
    if not matches:
        raise MatchError("Hasher returned no RetroAchievements hash.")
    return matches[-1].casefold()

def load_hash_catalogue(cache_path: Path) -> tuple[int, dict[str, tuple[int, str]]]:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MatchError(f"Cannot read cached catalogue: {cache_path}") from exc
    if not isinstance(payload, list) or not payload:
        raise MatchError(f"Cached catalogue is empty: {cache_path}")
    index: dict[str, tuple[int, str]] = {}
    console_id = 0
    for game in payload:
        if not isinstance(game, dict):
            continue
        try:
            game_id = int(game["ID"])
            title = str(game["Title"])
            console_id = console_id or int(game["ConsoleID"])
        except (KeyError, TypeError, ValueError):
            continue
        for value in game.get("Hashes", []):
            if isinstance(value, str) and HASH_PATTERN.fullmatch(value):
                index[value.casefold()] = (game_id, title)
    if not console_id or not index:
        raise MatchError(f"Cached catalogue contains no usable hashes: {cache_path}")
    return console_id, index

def hash_file(hasher: Path, console_id: int, path: Path) -> str:
    try:
        result = subprocess.run(
            [str(hasher), str(console_id), str(path)],
            capture_output=True, text=True, timeout=180, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MatchError(type(exc).__name__) from None
    combined = f"{result.stdout}\n{result.stderr}"
    try:
        return extract_hash(combined)
    except MatchError:
        message = combined.strip().splitlines()
        detail = message[-1][:160] if message else f"exit code {result.returncode}"
        raise MatchError(detail) from None

def match_collection(session: Session, root: Path, hasher: Path, cache_dir: Path, report_path: Path) -> tuple[MatchSummary, ...]:
    if not hasher.is_file():
        raise MatchError(f"RAHasher is not installed: {hasher}")
    if not root.is_dir():
        raise MatchError(f"Collection mount is unavailable: {root}")
    report_rows: list[dict[str, object]] = []
    summaries: list[MatchSummary] = []
    for slug, extensions in HASH_TARGET_EXTENSIONS.items():
        platform = session.scalar(select(Platform).where(Platform.slug == slug))
        if platform is None:
            raise MatchError(f"Platform is missing from the database: {slug}")
        console_id, catalogue = load_hash_catalogue(cache_dir / f"{slug}.json")
        items = list(session.scalars(select(LibraryItem).where(
            LibraryItem.platform_id == platform.id,
            LibraryItem.extension.in_(extensions),
            LibraryItem.is_missing.is_(False),
        ).order_by(LibraryItem.relative_path)))
        counts = Counter()
        total = len(items)
        print(f"[+] {platform.name}: {total} disc images to check.")
        for number, item in enumerate(items, start=1):
            path = root / item.relative_path
            if item.ra_hash:
                counts["cached"] += 1
                match = catalogue.get(item.ra_hash)
                if match:
                    item.ra_game_id, item.ra_game_title = match
                    item.ra_match_status = "matched"
                else:
                    item.ra_game_id = None
                    item.ra_game_title = None
                    item.ra_match_status = "unmatched"
            else:
                try:
                    item.ra_hash = hash_file(hasher, console_id, path)
                    match = catalogue.get(item.ra_hash)
                    if match:
                        item.ra_game_id, item.ra_game_title = match
                        item.ra_match_status = "matched"
                    else:
                        item.ra_game_id = None
                        item.ra_game_title = None
                        item.ra_match_status = "unmatched"
                    item.ra_hash_error = None
                except MatchError as exc:
                    item.ra_hash = None
                    item.ra_game_id = None
                    item.ra_game_title = None
                    item.ra_match_status = "failed"
                    item.ra_hash_error = str(exc)[:500]
                item.ra_hashed_at = datetime.now(timezone.utc)
            session.commit()
            counts[item.ra_match_status or "failed"] += 1
            report_rows.append({"platform": platform.name, "status": item.ra_match_status,
                "path": item.relative_path, "ra_hash": item.ra_hash or "",
                "ra_game_id": item.ra_game_id or "", "ra_game_title": item.ra_game_title or "",
                "error": item.ra_hash_error or ""})
            if number % 25 == 0 or number == total:
                print(f"[RUN] {platform.name}: {number}/{total} checked.")
        summaries.append(MatchSummary(platform.name, total, counts["matched"], counts["unmatched"], counts["failed"], counts["cached"]))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["platform", "status", "path", "ra_hash", "ra_game_id", "ra_game_title", "error"])
        writer.writeheader()
        writer.writerows(report_rows)
    temporary.replace(report_path)
    return tuple(summaries)
