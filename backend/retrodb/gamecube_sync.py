"""Publish GameCube ISO inventory; never modify ROMs."""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import os
import re
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from retrodb.cli import load_environment_file
from retrodb.database import get_engine
from retrodb.models import CollectionSource, LibraryItem, Platform

ROOT_RELATIVE = Path("roms/nintendo/gamecube/iso")


def sync(audit_path: Path, mount_root: Path) -> tuple[int, int]:
    with audit_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"source", "format", "filename", "status", "size_bytes", "ra_hash",
                    "ra_game_id", "ra_title", "ra_status", "title"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("GameCube audit missing required columns")
        records = [row for row in reader if row["status"] in ("VALID", "TIDY_CANDIDATE")]
    paths = []
    for row in records:
        relative = Path(row["source"])
        filename = row["filename"]
        if (relative.is_absolute() or len(relative.parts) != 1 or
                any(p.startswith((".", "OLD_", "NEW_")) or "\\" in p or ":" in p for p in relative.parts)
                or relative.name != filename or row["format"] not in ("iso",)
                or relative.suffix.lower() != "." + row["format"]):
            raise ValueError("Unsafe GameCube audit path")
        if row["ra_status"] not in {"SUPPORTED", "NO_SET", "UNMATCHED", "AMBIGUOUS", "HASH_ERROR", "NOT_CHECKED"}:
            raise ValueError("Unknown RA status")
        if row["ra_status"] in {"SUPPORTED", "NO_SET"} and (
                not row["ra_game_id"].isdigit() or not re.fullmatch(r"[0-9a-fA-F]{32}", row["ra_hash"])):
            raise ValueError("Invalid verified RA identity")
        if int(row["size_bytes"]) <= 0:
            raise ValueError("Invalid disc size")
        paths.append(relative.as_posix())
    if len(paths) != len({p.casefold() for p in paths}):
        raise ValueError("Duplicate GameCube paths")

    mount_root = mount_root.resolve()
    scan_root = mount_root / ROOT_RELATIVE
    if not os.path.ismount(mount_root) or not scan_root.is_dir():
        raise RuntimeError("RetroNAS read-only mount not available")
    # Preflight verifies the entire audit before making any database writes.
    stat_map = {}
    for row, path_text in zip(records, paths):
        path = scan_root / path_text
        if any((scan_root / Path(*Path(path_text).parts[:i])).is_symlink() for i in range(1, len(Path(path_text).parts)+1)) or not path.is_file() or not path.resolve().is_relative_to(scan_root.resolve()):
            raise ValueError(f"Nintendo GameCube ROM missing or unsafe: {path_text}")
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
        platform = session.scalar(select(Platform).where(Platform.slug == "gamecube"))
        if platform is None:
            next_id = (session.scalar(select(func.max(Platform.id))) or 0) + 1
            platform = Platform(id=next_id, slug="gamecube", name="Nintendo GameCube",
                                manufacturer="Nintendo", generation=6,
                                release_date=date(2001, 9, 14))
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
                                   extension=row["format"], size_bytes=int(row["size_bytes"]),
                                   modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                                   last_seen_at=now, is_missing=False)
                session.add(item)
            item.platform_id = platform.id
            item.filename = row["filename"]
            item.extension = row["format"]
            item.size_bytes = int(row["size_bytes"])
            item.modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            item.last_seen_at = now
            item.is_missing = False
            status = row["ra_status"]
            item.ra_hash = row["ra_hash"].lower() or None
            item.ra_game_id = int(row["ra_game_id"]) if status in ("SUPPORTED", "NO_SET") else None
            item.ra_game_title = (row["ra_title"] if item.ra_game_id else row["title"])[:500]
            item.ra_match_status = ("matched" if item.ra_game_id else
                                    "review" if status in ("AMBIGUOUS", "HASH_ERROR", "NOT_CHECKED") else "unmatched")
            detail = f'GameCube ID: {row.get("disc_id", "")}; Region: {row.get("region", "")}; Disc: {row.get("disc_number", "")}; Revision: {row.get("revision", "")}; ' + (row.get("reason") or "")
            if row.get("collection_status"):
                detail += "; Collection status: " + row["collection_status"]
            if row.get("candidate_ra_id"):
                detail += "; Suggested RA ID: " + row["candidate_ra_id"]
            if row.get("local_alternative"):
                detail += "; Local alternative: " + row["local_alternative"]
            item.ra_hash_error = detail.strip("; ")[:500] or None
            item.ra_hashed_at = now if item.ra_hash else None
            count += 1
        # Mark removed GameCube discs missing, without touching the Sony platforms.
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
    print(f"[OK] Nintendo GameCube portal sync: {count} discs indexed, {missing} removed discs marked missing.")
    print("[INFO] ROM collection remained read-only; only RetroDB database metadata updated.")


if __name__ == "__main__":
    main()
