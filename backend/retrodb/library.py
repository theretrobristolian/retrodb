"""Read-only collection inventory scanning."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from retrodb.models import CollectionSource, LibraryItem, Platform

PLATFORM_PATHS = {
    "playstation": Path("roms/sony/playstation1"),
    "playstation-2": Path("roms/sony/playstation2"),
}
GAME_EXTENSIONS = {".bin", ".ccd", ".chd", ".cso", ".cue", ".img", ".iso", ".mdf", ".mds", ".pbp", ".zso"}

class LibraryScanError(RuntimeError):
    pass

@dataclass(frozen=True)
class ScanSummary:
    discovered: int
    added: int
    updated: int
    missing: int
    skipped: int
    bytes_total: int

def scan_retronas(session: Session, root: Path) -> ScanSummary:
    root = root.resolve()
    if not root.is_dir():
        raise LibraryScanError(f"Collection mount is unavailable: {root}")
    if not os.path.ismount(root):
        raise LibraryScanError(f"Refusing to scan because RetroNAS is not mounted at {root}.")
    source = session.scalar(select(CollectionSource).where(CollectionSource.slug == "retronas"))
    if source is None:
        source = CollectionSource(slug="retronas", name="RetroNAS", root_path=str(root), read_only=True)
        session.add(source)
        session.flush()
    else:
        source.root_path = str(root)
    scan_started = datetime.now(timezone.utc)
    discovered = added = changed = skipped = bytes_total = 0
    for platform_slug, relative_root in PLATFORM_PATHS.items():
        platform = session.scalar(select(Platform).where(Platform.slug == platform_slug))
        if platform is None:
            raise LibraryScanError(f"Platform is missing from the database: {platform_slug}")
        scan_root = root / relative_root
        if not scan_root.is_dir():
            print(f"[!] Path not found; skipping {relative_root}.")
            skipped += 1
            continue
        for directory, directory_names, filenames in os.walk(scan_root, followlinks=False):
            directory_path = Path(directory)
            directory_names[:] = [name for name in directory_names if not (directory_path / name).is_symlink()]
            for filename in filenames:
                path = directory_path / filename
                if path.suffix.casefold() not in GAME_EXTENSIONS:
                    skipped += 1
                    continue
                try:
                    stat = path.stat(follow_symlinks=False)
                except OSError:
                    skipped += 1
                    continue
                if path.is_symlink() or not path.is_file():
                    skipped += 1
                    continue
                relative_path = path.relative_to(root).as_posix()
                existing = session.scalar(select(LibraryItem).where(
                    LibraryItem.source_id == source.id,
                    LibraryItem.relative_path == relative_path,
                ))
                modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                values = dict(platform_id=platform.id, filename=filename,
                    extension=path.suffix.casefold().lstrip("."), size_bytes=stat.st_size,
                    modified_at=modified_at, last_seen_at=scan_started, is_missing=False)
                if existing is None:
                    session.execute(insert(LibraryItem).values(source_id=source.id, relative_path=relative_path, **values))
                    added += 1
                else:
                    if existing.size_bytes != stat.st_size or existing.modified_at != modified_at or existing.is_missing:
                        changed += 1
                    for key, value in values.items():
                        setattr(existing, key, value)
                discovered += 1
                bytes_total += stat.st_size
    result = session.execute(update(LibraryItem).where(
        LibraryItem.source_id == source.id,
        LibraryItem.last_seen_at < scan_started,
        LibraryItem.is_missing.is_(False),
    ).values(is_missing=True))
    missing = result.rowcount or 0
    source.last_scanned_at = scan_started
    session.commit()
    return ScanSummary(discovered, added, changed, missing, skipped, bytes_total)
