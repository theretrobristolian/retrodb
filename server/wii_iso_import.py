#!/usr/bin/env python3
"""Preview and safely import loose Wii ISO files into disc-ID folders.

Only the six-byte disc ID and Wii magic at offset 0x18 are read. The ISO
contents are never rewritten or copied; the move must remain on one mount.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys
import uuid

from report_wii_audit import gametdb_titles
from wii_rename import FOLDER, ID, desired_title

WII_MAGIC = bytes.fromhex("5d1c9ea3")


def disc_id(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".iso":
        raise ValueError("Not a regular ISO")
    if path.stat().st_size < 0x20:
        raise ValueError("ISO too small for a Wii header")
    with path.open("rb") as handle:
        header = handle.read(0x20)
    try:
        name = header[:6].decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("Invalid Wii disc ID encoding") from None
    if not ID.fullmatch(name) or header[0x18:0x1c] != WII_MAGIC:
        raise ValueError("Invalid Wii disc ID or Wii magic")
    return name


def plan(root: Path, gametdb: Path | None = None) -> list[dict]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Wii collection unavailable or symbolic link")
    titles = gametdb_titles(gametdb)
    folders: dict[str, list[Path]] = {}
    for child in root.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        match = FOLDER.fullmatch(child.name)
        if match:
            folders.setdefault(match.group(2).upper(), []).append(child)
    rows = []
    for src in sorted(root.iterdir()):
        if src.is_symlink() or not src.is_file() or src.suffix.lower() != ".iso":
            continue
        row = dict(source=src.name, target="", disc_id="", status="REVIEW", reason="")
        try:
            ident = disc_id(src)
            row["disc_id"] = ident
            existing = folders.get(ident, [])
            if len(existing) > 1:
                raise ValueError("Multiple folders with the same disc ID")
            if existing:
                folder = existing[0]
                if folder.is_symlink():
                    raise ValueError("Unsafe destination folder")
            else:
                official = titles.get(ident, "")
                if not official:
                    raise ValueError("No exact GameTDB title; cannot create folder automatically")
                title, origin = desired_title("", official)
                if origin != "GameTDB disc ID":
                    raise ValueError("GameTDB title cannot form a safe folder")
                folder = root / f"{title} [{ident}]"
                if folder.name.casefold() in {x.name.casefold() for x in root.iterdir()}:
                    raise ValueError("Destination folder occupied by another entry")
            target = folder / (ident + ".iso")
            if folder.exists():
                if not folder.is_dir() or folder.is_symlink():
                    raise ValueError("Destination isn't a regular directory")
                if any(f.name.casefold() == target.name.casefold() for f in folder.iterdir()):
                    raise ValueError("Destination ISO already exists")
            row.update(status="IMPORT_CANDIDATE", target=target.relative_to(root).as_posix(),
                       reason="Existing disc-ID folder" if existing else "Create GameTDB disc-ID folder",
                       size=src.stat().st_size, mtime_ns=src.stat().st_mtime_ns)
        except (OSError, ValueError) as exc:
            row["reason"] = str(exc)
        rows.append(row)
    return rows


def apply(root: Path, rows: list[dict], journal: Path, gametdb: Path | None = None) -> int:
    if journal.exists() or journal.is_symlink():
        raise ValueError("Import journal already exists")
    candidates = [r for r in rows if r["status"] == "IMPORT_CANDIDATE"]
    if not candidates:
        return 0
    current = {r["source"]: r for r in plan(root, gametdb)}
    for row in candidates:
        live = current.get(row["source"])
        if not live or any(live.get(k) != row.get(k) for k in
                           ("status", "disc_id", "target", "size", "mtime_ns")):
            raise ValueError("Incoming ISO changed since preview: " + row["source"])
    # Never silently overwrite a target, including case-insensitive CIFS aliases.
    target_keys = [r["target"].casefold() for r in candidates]
    if len(target_keys) != len(set(target_keys)):
        raise ValueError("Several incoming ISO files target the same destination")
    journal.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema": 1, "operation": "wii-iso-import", "operations": [
        {"source": r["source"], "target": r["target"], "disc_id": r["disc_id"],
         "state": "pending", "created_folder": False} for r in candidates]}
    def save():
        temporary = journal.with_name(journal.name + ".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, journal)
    save()
    completed = 0
    for op in data["operations"]:
        src = root / op["source"]
        dest = root / op["target"]
        try:
            live = {r["source"]: r for r in plan(root, gametdb)}.get(op["source"])
            expected = next(r for r in candidates if r["source"] == op["source"])
            if not live or any(live.get(k) != expected.get(k) for k in
                               ("status", "disc_id", "target", "size", "mtime_ns")):
                raise ValueError("Source or destination changed")
            if not dest.parent.exists():
                op["state"] = "creating-folder"
                save()
                dest.parent.mkdir()  # Only one level below collection root.
                op["created_folder"] = True
                save()
            op["state"] = "moving"
            save()  # Journal before the atomic rename.
            os.rename(src, dest)
            op["state"] = "done"
            save()
            completed += 1
        except (OSError, ValueError) as exc:
            op["state"] = "failed"
            save()
            raise RuntimeError(f"ISO import stopped after {completed}; inspect {journal}: {exc}") from exc
    return completed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "apply"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--gametdb-cache", type=Path)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    if args.action == "apply" and (not args.journal or args.confirm != "IMPORT WII"):
        parser.error("Apply requires --journal and --confirm 'IMPORT WII'")
    rows = plan(args.root, args.gametdb_cache)
    print(f"[WII ISO] {len(rows)} loose ISO(s) scanned")
    for status, n in sorted(Counter(r["status"] for r in rows).items()):
        print(f"  {status}: {n}")
    for row in rows:
        if row["status"] == "IMPORT_CANDIDATE":
            print(f"  IMPORT {row['source']} [{row['disc_id']}] -> {row['target']} ({row['reason']})")
        else:
            print(f"  REVIEW {row['source']}: {row['reason']}")
    if args.action == "preview":
        print("[INFO] Preview only. No Wii ISO was moved or modified.")
        return 0
    count = apply(args.root, rows, args.journal, args.gametdb_cache)
    print(f"[OK] Imported {count} Wii ISO(s) without modifying their contents.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        sys.exit(f"[ERROR] {exc}")
