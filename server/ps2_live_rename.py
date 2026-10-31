#!/usr/bin/env python3
"""Build PS2 OPL rename proposals from the live read-only RetroNAS inventory."""
import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from retrodb.providers.gamedb import load
from report_opl_rename import propose

SERIAL = re.compile(r"(?<![A-Z0-9])([A-Z]{4})[-_. ]?(\d{3})[-_. ]?(\d{2})(?!\d)", re.I)
CACHE = Path("/var/cache/retrodb/providers/gamedb")
FIELDS = ("Current relative path", "Current filename", "Disc ID", "GameDB title",
          "Proposed filename", "Proposed relative path", "Display preview with RA",
          "Title truncated", "Status", "Notes", "Duplicate recommendation",
          "SHA256", "Disc inspection")


def inventory(root, titles):
    collection = root / "roms/sony/playstation2"
    if not collection.is_dir() or collection.is_symlink():
        raise RuntimeError(f"PS2 ROM directory unavailable: {collection}")
    rows = []
    files = sorted(p for p in collection.rglob("*")
                   if p.suffix.lower() == ".iso" and p.is_file() and not p.is_symlink()
                   and not p.name.casefold().startswith("old_"))
    for file in files:
        match = SERIAL.search(file.name)
        serial = (f"{match[1].upper()}-{match[2]}{match[3]}" if match else "")
        rows.append(dict(path=file.relative_to(root).as_posix(),
                         platform="Sony PlayStation 2", local_serial=serial,
                         gamedb_title=titles.get(serial, "")))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    titles = load(CACHE, "playstation-2")
    if not titles:
        parser.error("PS2 GameDB catalogue unavailable; refresh first")
    rows = inventory(args.root, titles)
    if not rows:
        parser.error("No PS2 ISOs found; refusing empty rename proposal overwrite")
    proposals = propose(rows, verify_root=args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(proposals)
    from collections import Counter
    counts = Counter(row["Status"] for row in proposals)
    print(f"[PS2] Fresh read-only inventory: {len(rows)} ISO files", flush=True)
    print(f"[PS2] Proposals: {counts['PROPOSED']} eligible | {counts['UNCHANGED']} unchanged | "
          f"{counts['REVIEW']} review | {counts['COLLISION']} collisions", flush=True)
    print(f"[PS2] Current proposal CSV: {args.output}", flush=True)


if __name__ == "__main__":
    main()
