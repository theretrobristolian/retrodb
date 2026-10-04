"""Read-only collection inventory scanning."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, field
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
PLATFORM_LABELS = {"playstation": "PlayStation", "playstation-2": "PlayStation 2"}
GAME_EXTENSIONS = {".bin", ".ccd", ".chd", ".cso", ".cue", ".img", ".iso", ".mdf", ".mds", ".pbp", ".zso"}

class LibraryScanError(RuntimeError):
    pass

@dataclass
class PlatformScanSummary:
    slug: str
    label: str
    path: Path
    exists: bool = True
    files: int = 0
    added: int = 0
    updated: int = 0
    missing: int = 0
    bytes_total: int = 0
    folders: Counter[str] = field(default_factory=Counter)
    folder_bytes: Counter[str] = field(default_factory=Counter)
    extensions: Counter[str] = field(default_factory=Counter)
    skipped_extensions: Counter[str] = field(default_factory=Counter)
    skipped_other: int = 0

@dataclass(frozen=True)
class ScanSummary:
    root: Path
    platforms: tuple[PlatformScanSummary, ...]

    @property
    def files(self) -> int:
        return sum(item.files for item in self.platforms)

    @property
    def bytes_total(self) -> int:
        return sum(item.bytes_total for item in self.platforms)

    @property
    def added(self) -> int:
        return sum(item.added for item in self.platforms)

    @property
    def updated(self) -> int:
        return sum(item.updated for item in self.platforms)

    @property
    def missing(self) -> int:
        return sum(item.missing for item in self.platforms)

def _top_folder(path: Path, scan_root: Path) -> str:
    relative = path.relative_to(scan_root)
    return relative.parts[0] if len(relative.parts) > 1 else "(root)"

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
    summaries: list[PlatformScanSummary] = []
    for platform_slug, relative_root in PLATFORM_PATHS.items():
        scan_root = root / relative_root
        summary = PlatformScanSummary(
            slug=platform_slug,
            label=PLATFORM_LABELS[platform_slug],
            path=scan_root,
            exists=scan_root.is_dir(),
        )
        summaries.append(summary)
        platform = session.scalar(select(Platform).where(Platform.slug == platform_slug))
        if platform is None:
            raise LibraryScanError(f"Platform is missing from the database: {platform_slug}")
        if not summary.exists:
            continue
        for directory, directory_names, filenames in os.walk(scan_root, followlinks=False):
            directory_path = Path(directory)
            directory_names[:] = [name for name in directory_names if not (directory_path / name).is_symlink()]
            for filename in filenames:
                path = directory_path / filename
                extension = path.suffix.casefold() or "(none)"
                if extension not in GAME_EXTENSIONS:
                    summary.skipped_extensions[extension.lstrip(".")] += 1
                    continue
                try:
                    stat = path.stat(follow_symlinks=False)
                except OSError:
                    summary.skipped_other += 1
                    continue
                if path.is_symlink() or not path.is_file():
                    summary.skipped_other += 1
                    continue
                relative_path = path.relative_to(root).as_posix()
                existing = session.scalar(select(LibraryItem).where(
                    LibraryItem.source_id == source.id,
                    LibraryItem.relative_path == relative_path,
                ))
                modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                values = dict(platform_id=platform.id, filename=filename,
                    extension=extension.lstrip("."), size_bytes=stat.st_size,
                    modified_at=modified_at, last_seen_at=scan_started, is_missing=False)
                if existing is None:
                    session.execute(insert(LibraryItem).values(source_id=source.id, relative_path=relative_path, **values))
                    summary.added += 1
                else:
                    if existing.size_bytes != stat.st_size or existing.modified_at != modified_at or existing.is_missing:
                        summary.updated += 1
                    for key, value in values.items():
                        setattr(existing, key, value)
                summary.files += 1
                summary.bytes_total += stat.st_size
                summary.extensions[extension.lstrip(".")] += 1
                summary.folders[_top_folder(path, scan_root)] += 1
                summary.folder_bytes[_top_folder(path, scan_root)] += stat.st_size
        result = session.execute(update(LibraryItem).where(
            LibraryItem.source_id == source.id,
            LibraryItem.platform_id == platform.id,
            LibraryItem.last_seen_at < scan_started,
            LibraryItem.is_missing.is_(False),
        ).values(is_missing=True))
        summary.missing = result.rowcount or 0
    source.last_scanned_at = scan_started
    session.commit()
    return ScanSummary(root=root, platforms=tuple(summaries))
