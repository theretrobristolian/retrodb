#!/usr/bin/env python3
"""Read-only Nintendo Wii WBFS inventory and conservative RA title suggestions.

Disc IDs identify releases but DO NOT establish RetroAchievements hash support.
No WBFS disc image is hashed as a normal file or modified.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT_PARTS = ("roms", "nintendo", "wii")
ID = re.compile(r"^[A-Z0-9]{6}$")
FOLDER = re.compile(r"^(.+?)\s*\[([A-Za-z0-9]{6})\]$")
FIELDS = ("status", "relative_path", "filename", "disc_id", "title",
          "title_source", "region", "size_bytes", "ra_game_id",
          "ra_title", "ra_achievements", "reason")
REGIONS = {"E": "USA", "P": "Europe", "J": "Japan", "K": "Korea",
           "D": "Germany", "F": "France", "I": "Italy", "S": "Spain",
           "H": "Netherlands", "U": "Australia", "A": "World"}


def title_key(value: str) -> str:
    title = str(value).casefold()
    title = re.sub(r"^(?:the|a)\s+", "", title)
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return " ".join(title.split())


def game_catalogue(path: Path | None) -> dict[str, list[tuple[int, str, int]]]:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Wii RetroAchievements catalogue must be a list")
    index: dict[str, list[tuple[int, str, int]]] = {}
    for game in payload:
        if not isinstance(game, dict):
            continue
        try:
            if int(game.get("ConsoleID", 19)) != 19:
                continue
            ident = int(game["ID"])
            title = str(game["Title"]).strip()
            count = int(game.get("NumAchievements", 0))
        except (ValueError, TypeError, KeyError):
            continue
        if not title:
            continue
        key = title_key(title)
        if key:
            index.setdefault(key, []).append((ident, title, count))
    return index


def gametdb_titles(path: Path | None) -> dict[str, str]:
    """Optional cached GameTDB XML or English title table, indexed by Wii ID."""
    if path is None or not path.is_file():
        return {}
    if path.suffix.lower() == ".txt":
        names = {}
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if " = " not in line:
                continue
            disc_id, title = line.split(" = ", 1)
            disc_id, title = disc_id.strip().upper(), title.strip()
            if ID.fullmatch(disc_id) and disc_id != "TITLES" and title and len(title) <= 250:
                names[disc_id] = title
        return names
    titles = {}
    # Safe, streaming XML; do not download/parse an untrusted URL directly.
    for _, element in ET.iterparse(path, events=("end",)):
        if element.tag != "game":
            continue
        serial = (element.findtext("id") or "").strip().upper()
        # GameTDB normally stores titles inside language-labelled locale
        # elements, not directly under <game>.
        title = (element.findtext("./locale[@lang='EN']/title")
                 or element.findtext("./locale[@lang='en']/title")
                 or element.findtext("title") or "").strip()
        if ID.fullmatch(serial) and title and len(title) <= 250:
            titles[serial] = title
        element.clear()
    return titles


def audit(root: Path, ra_catalogue: Path | None = None,
          gametdb_cache: Path | None = None) -> list[dict[str, str | int]]:
    if not root.is_dir() or root.is_symlink():
        raise FileNotFoundError(f"Wii directory unavailable: {root}")
    ra_index = game_catalogue(ra_catalogue)
    titles = gametdb_titles(gametdb_cache)
    records: list[dict[str, str | int]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in (".wbfs", ".iso", ".rvz"):
            continue
        relative = path.relative_to(root)
        # The supported Wii layout is strictly one game directory deep.
        # Ignore extra nested tools/backups rather than publishing unsafe paths.
        if len(relative.parts) != 2:
            continue
        # A folder and a file must independently agree on the complete disc ID.
        match = FOLDER.fullmatch(path.parent.name)
        disk_id = path.stem.upper()
        folder_id = match.group(2).upper() if match else ""
        folder_title = match.group(1).strip() if match else ""
        status = "REVIEW"
        reason = ""
        if not match:
            reason = "Expected Game Name [DISC_ID] folder"
        elif not ID.fullmatch(disk_id):
            reason = "Image filename is not a six-character disc ID"
        elif disk_id != folder_id:
            reason = "Folder disc ID and image filename differ"
        elif path.stat().st_size == 0:
            reason = "Empty disc image"
        else:
            status = "IDENTIFIED"
        title = titles.get(disk_id) if status == "IDENTIFIED" else None
        title = title or folder_title or path.stem
        source = "GameTDB disc ID" if disk_id in titles and status == "IDENTIFIED" else "folder"
        ra_id: int | str = ""
        ra_name = ""
        achievements: int | str = ""
        if status == "IDENTIFIED":
            candidates = ra_index.get(title_key(title), [])
            if len(candidates) == 1:
                ra_id, ra_name, achievements = candidates[0]
                status = "TITLE_CANDIDATE"
                reason = "RA title candidate only; WBFS content hash not verified"
            elif len(candidates) > 1:
                status = "AMBIGUOUS_TITLE"
                reason = "Several RA titles match; needs review"
            else:
                reason = "Disc ID identified; no unique RA title match (not proof of no achievements)"
        records.append({
            "status": status,
            "relative_path": relative.as_posix(), "filename": path.name,
            "disc_id": disk_id if status != "REVIEW" else "",
            "title": title, "title_source": source,
            "region": REGIONS.get(disk_id[3], "Unknown") if len(disk_id) == 6 else "Unknown",
            "size_bytes": path.stat().st_size,
            "ra_game_id": ra_id, "ra_title": ra_name,
            "ra_achievements": achievements, "reason": reason,
        })
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ra-catalogue", type=Path)
    parser.add_argument("--gametdb-cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = audit(args.root, args.ra_catalogue, args.gametdb_cache)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    from collections import Counter
    print(f"[OK] Nintendo Wii: {len(rows)} disc image(s) -> {args.output}")
    for state, count in sorted(Counter(str(row["status"]) for row in rows).items()):
        print(f"  {state}: {count}")
    print("[INFO] RA title candidates are UNVERIFIED. No WBFS content hash was computed.")
    print("[INFO] ROMs and RetroNAS files remained read-only.")


if __name__ == "__main__":
    main()
