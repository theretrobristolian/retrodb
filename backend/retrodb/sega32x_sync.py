"""Synchronise a completed, read-only Sega 32X ZIP audit into RetroDB portal.

Only database records are changed. ZIPs on RetroNAS remain read-only.
Verified RA IDs and gold badges are assigned only to exact content hashes.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from retrodb.cli import load_environment_file
from retrodb.database import get_engine
from retrodb.models import CollectionSource, LibraryItem, Platform

ACCEPTED = {
    "EXACT_RA", "EXACT_NO_SET", "SOFT_PASS_VARIANT",
    "ALTERNATIVE_REVIEW", "NO_SET_CANDIDATE", "UNMATCHED",
    "AMBIGUOUS_TITLE", "REVIEW",
}
ROOT_RELATIVE = Path("roms/sega/32x")


def sync(audit_path: Path, mount_root: Path) -> tuple[int, int]:
    with audit_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"relative_path", "status", "ra_md5", "ra_game_id", "ra_title",
                    "display_title", "filename"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Sega 32X audit is missing required columns")
        records = list(reader)
    if not all(row["status"] in ACCEPTED for row in records):
        raise ValueError("Unknown Sega 32X audit status; no database changes made")
    paths = []
    for row in records:
        relative = Path(row["relative_path"])
        if (relative.is_absolute() or ".." in relative.parts or not relative.parts or
                relative.suffix.casefold() != ".zip" or relative.name != row["filename"] or
                "bios" in relative.name.casefold()):
            raise ValueError("Unsafe or non-ROM Sega 32X audit path")
        paths.append(relative.as_posix())
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate Sega 32X audit paths")

    mount_root = mount_root.resolve()
    scan_root = mount_root / ROOT_RELATIVE
    if not os.path.ismount(mount_root) or not scan_root.is_dir():
        raise RuntimeError("RetroNAS read-only mount not available")
    # Preflight verifies the entire audit before making any database writes.
    stat_map = {}
    for row, path_text in zip(records, paths):
        path = scan_root / path_text
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(scan_root.resolve()):
            raise ValueError(f"Sega 32X ROM missing or unsafe: {path_text}")
        stat_map[path_text] = path.stat()

    count = 0
    now = datetime.now(timezone.utc)
    with Session(get_engine()) as session:
        source = session.scalar(select(CollectionSource).where(CollectionSource.slug == "retronas"))
        if source is None:
            source = CollectionSource(slug="retronas", name="RetroNAS",
                                      root_path=str(mount_root), read_only=True)
            session.add(source)
            session.flush()
        platform = session.scalar(select(Platform).where(Platform.slug == "sega-32x"))
        if platform is None:
            next_id = (session.scalar(select(func.max(Platform.id))) or 0) + 1
            platform = Platform(id=next_id, slug="sega-32x", name="Sega 32X",
                                manufacturer="Sega", generation=4,
                                release_date=date(1994, 11, 21))
            session.add(platform)
            session.flush()
        seen = set()
        for row, relative in zip(records, paths):
            db_path = (ROOT_RELATIVE / relative).as_posix()
            seen.add(db_path)
            stat = stat_map[relative]
            item = session.scalar(select(LibraryItem).where(
                LibraryItem.source_id == source.id,
                LibraryItem.relative_path == db_path))
            if item is None:
                item = LibraryItem(source_id=source.id, platform_id=platform.id,
                                   relative_path=db_path, filename=row["filename"],
                                   extension="zip", size_bytes=stat.st_size,
                                   modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                                   last_seen_at=now, is_missing=False)
                session.add(item)
            item.platform_id = platform.id
            item.filename = row["filename"]
            item.extension = "zip"
            item.size_bytes = stat.st_size
            item.modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            item.last_seen_at = now
            item.is_missing = False
            status = row["status"]
            item.ra_hash = row["ra_md5"].lower() or None
            # Only official exact hashes get a verified RA ID / gold badge.
            item.ra_game_id = int(row["ra_game_id"]) if status.startswith("EXACT_") and row["ra_game_id"].isdigit() else None
            item.ra_game_title = (row["ra_title"] if item.ra_game_id else
                                  row.get("suggested_ra_title") or row["display_title"] or None)
            item.ra_match_status = ("matched" if item.ra_game_id else
                                    "review" if status in ("SOFT_PASS_VARIANT", "ALTERNATIVE_REVIEW",
                                                           "NO_SET_CANDIDATE", "AMBIGUOUS_TITLE", "REVIEW")
                                    else "unmatched")
            detail = row.get("reason") or ""
            if row.get("local_verified_variant"):
                detail += "; Compatible alternate ZIP: " + row["local_verified_variant"]
            if row.get("suggested_ra_game_id"):
                detail += "; Suggested RA ID: " + row["suggested_ra_game_id"]
            item.ra_hash_error = detail.strip("; ")[:500] or None
            item.ra_hashed_at = now if item.ra_hash else None
            count += 1
        # Mark removed 32X ZIPs missing, without touching the Sony platforms.
        from sqlalchemy import update
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
    return count, missing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--mount-root", required=True, type=Path)
    parser.add_argument("--env-file", type=Path,
                        default=Path("/etc/retrodb/retrodb.env"))
    args = parser.parse_args()
    load_environment_file(args.env_file)
    count, missing = sync(args.audit, args.mount_root)
    print(f"[OK] Sega 32X portal sync: {count} ZIPs indexed, {missing} removed ZIPs marked missing.")
    print("[INFO] ROM collection remained read-only; only RetroDB database metadata updated.")


if __name__ == "__main__":
    main()
