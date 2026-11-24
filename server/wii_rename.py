#!/usr/bin/env python3
"""Preview/confirm Nintendo Wii folder-only renames without touching WBFS contents.

The exact six-character Wii disc ID remains the folder suffix. Prefer an
optional local GameTDB disc-ID title, otherwise conservatively normalise
ALL-CAPS names. Mixed-case names without metadata are not rewritten.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections import Counter
from pathlib import Path

from report_wii_audit import gametdb_titles

FOLDER = re.compile(r"^(.+?)\s*\[([A-Z0-9]{6})\]$", re.I)
ID = re.compile(r"^[A-Z0-9]{6}$")
IMAGE_EXT = {".wbfs", ".iso", ".rvz"}
INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Keep well-known abbreviations recognisable when an old catalogue is ALL CAPS.
ACRONYMS = {"wii": "Wii", "wiifit": "WiiFit", "nba": "NBA", "nfl": "NFL",
            "nhl": "NHL", "mlb": "MLB", "wwe": "WWE", "ufc": "UFC",
            "fifa": "FIFA", "lego": "LEGO", "csi": "CSI", "usa": "USA",
            "uk": "UK", "ds": "DS", "3d": "3D", "2d": "2D",
            "vs": "vs", "ii": "II", "iii": "III", "iv": "IV"}
SMALL = {"and", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "vs"}
SHORT_WORDS = {"A", "I"}


def title_case(text: str) -> str:
    """Conservative title-casing; no guesses about editions or abbreviations."""
    words = text.lower().split()
    result = []
    for position, word in enumerate(words):
        left = re.match(r"^\W*", word).group()
        right = re.search(r"\W*$", word).group()
        if len(left) + len(right) >= len(word):
            result.append(word)  # Standalone "&", "-", etc. must not duplicate.
            continue
        core = word[len(left):len(word)-len(right) if right else None]
        key = core.lower()
        if key in ACRONYMS:
            adjusted = ACRONYMS[key]
        elif key in SMALL and 0 < position < len(words)-1:
            adjusted = core.lower()
        elif key in {"a", "i"}:
            adjusted = key.upper()
        else:
            adjusted = core.capitalize()
        result.append(left + adjusted + right)
    return " ".join(result)


def desired_title(source: str, official: str = "") -> tuple[str, str]:
    """Return safe display title and source, or a reason for manual review."""
    if official.strip():
        result = official.strip()
        source_type = "GameTDB disc ID"
    elif source.upper() == source and any(c.isalpha() for c in source):
        result = title_case(source)
        source_type = "ALL-CAPS formatting"
    else:
        return source, "Mixed-case name preserved (no exact GameTDB title)"
    # Windows/SMB folder-safe punctuation. Don't strip edition text.
    result = re.sub(r"\s*[:/|]\s*", " - ", result)
    result = re.sub(r"\s+", " ", result).strip(" .")
    if not result or len(result) > 180 or INVALID.search(result):
        return source, "Invalid or unsafe proposed title"
    return result, source_type


def plan(root: Path, gametdb: Path | None = None) -> list[dict[str, str]]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Wii collection unavailable or symbolic link")
    titles = gametdb_titles(gametdb)
    entries = []
    for folder in sorted(root.iterdir()):
        if folder.is_symlink() or not folder.is_dir():
            continue
        match = FOLDER.fullmatch(folder.name)
        if not match:
            entries.append({"status": "REVIEW", "source": folder.name, "target": "",
                            "disc_id": "", "reason": "Folder has no [DISC_ID] suffix"})
            continue
        current, disc_id = match.group(1).strip(), match.group(2).upper()
        files = list(folder.iterdir())
        if any(entry.is_symlink() for entry in files):
            reason = "Symbolic link inside game folder"
        else:
            images = [entry for entry in files if entry.is_file() and entry.suffix.lower() in IMAGE_EXT]
            if len(images) != 1:
                reason = "Expected exactly one primary Wii image"
            elif images[0].stem.upper() != disc_id:
                reason = "Folder and image disc IDs disagree"
            elif images[0].stat().st_size == 0:
                reason = "Empty Wii disc image"
            else:
                reason = ""
        row = {"status": "REVIEW", "source": folder.name, "target": "",
               "disc_id": disc_id, "reason": reason}
        if not reason:
            title, origin = desired_title(current, titles.get(disc_id, ""))
            dest = f"{title} [{disc_id}]"
            if origin.startswith("Invalid"):
                row["reason"] = origin
            elif dest == folder.name:
                row["status"] = "VALID"
                row["reason"] = "Already named consistently"
            elif INVALID.search(dest) or dest in {".", ".."}:
                row["reason"] = "Unsafe destination name"
            else:
                row.update(status="RENAME_CANDIDATE", target=dest, reason=origin)
        entries.append(row)

    # SMB shares are commonly case-insensitive. Do not overwrite case aliases,
    # swap two directories or permit two sources to converge on one target.
    occupied = {}
    for child in root.iterdir():
        occupied.setdefault(child.name.casefold(), set()).add(child.name)
    target_counts = Counter(r["target"].casefold() for r in entries
                            if r["status"] == "RENAME_CANDIDATE")
    for row in entries:
        if row["status"] != "RENAME_CANDIDATE":
            continue
        others = occupied.get(row["target"].casefold(), set()) - {row["source"]}
        if others or target_counts[row["target"].casefold()] > 1:
            row["status"] = "REVIEW_COLLISION"
            row["reason"] = "Destination exists or multiple folders propose the same name"
    return entries


def apply(root: Path, rows: list[dict[str, str]], journal: Path,
          gametdb: Path | None = None) -> int:
    if journal.exists() or journal.is_symlink():
        raise ValueError("Refusing to overwrite an existing journal")
    candidates = [row for row in rows if row["status"] == "RENAME_CANDIDATE"]
    if not candidates:
        return 0
    # Verify the complete plan before starting. Re-run this validation on the
    # writable mount, never trust only the preview from the read-only mount.
    live = plan(root, gametdb)
    by_src = {row["source"]: row for row in live}
    # A locally cached GameTDB title may produce different suggestions from
    # an all-caps fallback. Permit only the target explicitly previewed.
    for row in candidates:
        src, dest = root / row["source"], root / row["target"]
        current = by_src.get(row["source"])
        if (current is None or current["status"] != "RENAME_CANDIDATE"
                or current["target"] != row["target"]
                or src.is_symlink() or not src.is_dir()
                or src.parent != dest.parent or row["disc_id"] != current["disc_id"]
                or dest.is_symlink()
                or (dest.exists() and not src.samefile(dest))):
            raise ValueError("Folder changed or destination occupied: " + row["source"])
        if not FOLDER.fullmatch(row["target"]) or FOLDER.fullmatch(row["target"]).group(2).upper() != row["disc_id"]:
            raise ValueError("Unsafe destination disc ID")
    journal.parent.mkdir(parents=True, exist_ok=True)
    summary = {"schema": 1, "operation": "wii-folder-rename",
               "operations": [{"source": r["source"], "target": r["target"], "state": "pending",
                               "intermediate": ""} for r in candidates]}
    def record():
        temporary = journal.with_name(journal.name + ".tmp")
        temporary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, journal)
    record()
    renamed = 0
    for item in summary["operations"]:
        src, dest = root / item["source"], root / item["target"]
        try:
            if src.is_symlink() or not src.is_dir() or (dest.exists() and not src.samefile(dest)):
                raise ValueError("Source or destination changed")
            if src.name.casefold() == dest.name.casefold():
                # On case-insensitive SMB, a direct case-only rename may be a
                # no-op. Use a unique intermediate folder on the SAME share.
                # Record it BEFORE moving so an interruption can be recovered.
                intermediate = root / (".retrodb-wii-rename-" + uuid.uuid4().hex)
                if intermediate.exists() or intermediate.is_symlink():
                    raise ValueError("Intermediate folder already exists")
                item["intermediate"] = intermediate.name
                item["state"] = "moving-to-intermediate"
                record()
                os.rename(src, intermediate)
                item["state"] = "at-intermediate"
                record()
                if dest.exists() or dest.is_symlink():
                    raise ValueError("Destination unexpectedly occupied")
                os.rename(intermediate, dest)
            else:
                os.rename(src, dest)  # Folder only; WBFS bytes unchanged.
            item["state"] = "done"
            renamed += 1
            record()
        except (OSError, ValueError) as exc:
            item["state"] = "failed"
            record()
            raise RuntimeError(f"Rename stopped after {renamed}; inspect {journal}: {exc}")
    return renamed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "apply"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--gametdb-cache", type=Path)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    if args.action == "apply" and (not args.journal or args.confirm != "RENAME WII"):
        parser.error("Apply requires --journal and --confirm 'RENAME WII'")
    rows = plan(args.root, args.gametdb_cache)
    print(f"[WII] {len(rows)} folders scanned")
    for state, count in sorted(Counter(r["status"] for r in rows).items()):
        print(f"  {state}: {count}")
    for row in rows:
        if row["status"] == "RENAME_CANDIDATE":
            print(f"  RENAME {row['source']} -> {row['target']} ({row['reason']})")
        elif row["status"].startswith("REVIEW"):
            print(f"  REVIEW {row['source']}: {row['reason']}")
    if args.action == "preview":
        print("[INFO] Preview only. No Wii folder or image changed.")
        return 0
    count = apply(args.root, rows, args.journal, args.gametdb_cache)
    print(f"[OK] Renamed {count} Wii folders. Internal disc files remain untouched.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, RuntimeError) as exc:
        sys.exit(f"[ERROR] {exc}")
