"""Import read-only Wii disc inventory into RetroDB's existing library.

A Wii disc ID / RA catalogue title IS NOT a verified RA content hash.
No achievement badge is granted by this module.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import os
from pathlib import Path
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from retrodb.cli import load_environment_file
from retrodb.database import get_engine
from retrodb.models import CollectionSource, LibraryItem, Platform

ROOT_RELATIVE = Path("roms/nintendo/wii")
ID = re.compile(r"^[A-Z0-9]{6}$")
NAME = re.compile(r"^(.+?) \[([A-Z0-9]{6})\]$", re.I)
STATES = {"IDENTIFIED", "TITLE_CANDIDATE", "AMBIGUOUS_TITLE", "REVIEW"}
EXTENSIONS = {".wbfs", ".iso", ".rvz"}


def image_size(path: Path) -> int:
    size = path.stat().st_size
    if path.suffix.lower() == ".wbfs":
        pattern = re.compile(re.escape(path.stem) + r"\.wbf[1-9][0-9]*$", re.I)
        size += sum(part.stat().st_size for part in path.parent.iterdir()
                    if pattern.fullmatch(part.name) and not part.is_symlink() and part.is_file())
    return size


def sync(audit_path: Path, mount_root: Path) -> tuple[int, int]:
    with audit_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"relative_path", "filename", "disc_id", "title", "status",
                    "ra_game_id", "ra_title", "reason"}
        if not required.issubset(set(reader.fieldnames or ())):
            raise ValueError("Wii audit is missing required columns")
        records = list(reader)
    paths = []
    for row in records:
        relative = Path(row["relative_path"])
        if (relative.is_absolute() or ".." in relative.parts
                or len(relative.parts) != 2 or relative.name != row["filename"]
                or relative.suffix.lower() not in EXTENSIONS
                or row["status"] not in STATES):
            raise ValueError("Unsafe Wii audit path/status")
        folder = NAME.fullmatch(relative.parent.name)
        disc_id = relative.stem.upper()
        if row["status"] != "REVIEW" and (not folder or not ID.fullmatch(disc_id)
                                           or disc_id != folder.group(2).upper()
                                           or row["disc_id"] != disc_id):
            raise ValueError("Wii disc ID mismatch")
        if row["status"] == "REVIEW" and row["disc_id"]:
            raise ValueError("Unvalidated Wii disc ID must be blank")
        paths.append(relative.as_posix())
    if len({path.casefold() for path in paths}) != len(paths):
        raise ValueError("Duplicate Wii paths")

    mount_root = mount_root.resolve()
    scan_root = mount_root / ROOT_RELATIVE
    if not os.path.ismount(mount_root) or not scan_root.is_dir():
        raise RuntimeError("RetroNAS collection mount is unavailable")
    stat_map = {}
    size_map = {}
    for path_text in paths:
        path = scan_root / path_text
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(scan_root.resolve()):
            raise ValueError(f"Wii disc missing or unsafe: {path_text}")
        stat_map[path_text] = path.stat()
        size_map[path_text] = image_size(path)
        if stat_map[path_text].st_size <= 0:
            # An empty entry may be listed for REVIEW, but should never index
            # as a playable disc.
            raise ValueError(f"Wii disc image is empty: {path_text}")

    now = datetime.now(timezone.utc)
    with Session(get_engine()) as session:
        source = session.scalar(select(CollectionSource).where(CollectionSource.slug == "retronas"))
        if source is None:
            source = CollectionSource(slug="retronas", name="RetroNAS",
                                      root_path=str(mount_root), read_only=True)
            session.add(source)
            session.flush()
        platform = session.scalar(select(Platform).where(Platform.slug == "wii"))
        if platform is None:
            next_id = (session.scalar(select(func.max(Platform.id))) or 0) + 1
            platform = Platform(id=next_id, slug="wii", name="Nintendo Wii",
                                manufacturer="Nintendo", generation=7,
                                release_date=date(2006, 11, 19))
            session.add(platform)
            session.flush()
        # Reuse a unique existing row after a *folder-only rename*. Wii WBFS
        # basename, size and mtime remain identical; preserve library item IDs
        # rather than creating a new row and marking the old one missing.
        previous_items = session.scalars(select(LibraryItem).where(
            LibraryItem.source_id == source.id,
            LibraryItem.platform_id == platform.id,
            LibraryItem.is_missing.is_(False))).all()
        incoming = {(ROOT_RELATIVE / p).as_posix() for p in paths}
        seen = set()
        reused = set()
        for row, relative in zip(records, paths):
            db_path = (ROOT_RELATIVE / relative).as_posix()
            seen.add(db_path)
            stat = stat_map[relative]
            size = size_map[relative]
            item = session.scalar(select(LibraryItem).where(
                LibraryItem.source_id == source.id,
                LibraryItem.relative_path == db_path))
            if item is None and row["disc_id"]:
                candidates = [
                    old for old in previous_items
                    if old.id not in reused
                    and old.relative_path not in incoming
                    and old.filename.casefold() == row["filename"].casefold()
                    and old.size_bytes in (size, stat.st_size)
                    and abs(old.modified_at.timestamp() - stat.st_mtime) < 0.01
                    and old.relative_path.startswith(ROOT_RELATIVE.as_posix() + "/")
                    and not (mount_root / old.relative_path).exists()
                ]
                if len(candidates) == 1:
                    item = candidates[0]
                    reused.add(item.id)
                    item.relative_path = db_path
            if item is None:
                item = LibraryItem(source_id=source.id, platform_id=platform.id,
                                   relative_path=db_path, filename=row["filename"],
                                   extension=Path(relative).suffix.lstrip(".").lower(),
                                   size_bytes=size,
                                   modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                                   last_seen_at=now, is_missing=False)
                session.add(item)
            item.platform_id = platform.id
            item.filename = row["filename"]
            item.extension = Path(relative).suffix.lstrip(".").lower()
            item.size_bytes = size
            item.modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            item.last_seen_at = now
            item.is_missing = False
            # Explicitly clear previous speculative matching data, if any.
            item.ra_hash = None
            item.ra_hashed_at = None
            item.ra_game_id = None
            item.ra_match_status = "review" if row["status"] in ("TITLE_CANDIDATE", "AMBIGUOUS_TITLE", "REVIEW") else "unmatched"
            item.ra_game_title = (row["ra_title"] or row["title"])[:500] or None
            reason = row["reason"]
            if row["status"] == "TITLE_CANDIDATE" and str(row["ra_game_id"]).isdigit():
                reason += "; Suggested RA ID: " + str(row["ra_game_id"])
            if row["disc_id"]:
                reason += "; Wii disc ID: " + row["disc_id"]
            item.ra_hash_error = reason[:500] or None
        existing = session.scalars(select(LibraryItem).where(
            LibraryItem.source_id == source.id,
            LibraryItem.platform_id == platform.id,
            LibraryItem.is_missing.is_(False))).all()
        missing = 0
        for item in existing:
            if item.relative_path not in seen:
                item.is_missing = True
                missing += 1
        session.commit()
    return len(records), missing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--mount-root", required=True, type=Path)
    parser.add_argument("--env-file", type=Path, default=Path("/etc/retrodb/retrodb.env"))
    args = parser.parse_args()
    load_environment_file(args.env_file)
    total, missing = sync(args.audit, args.mount_root)
    print(f"[OK] Wii library sync: {total} images indexed, {missing} old paths marked missing")
    print("[INFO] No RA hashes verified; no gold badges assigned. ROMs unchanged.")


if __name__ == "__main__":
    main()
