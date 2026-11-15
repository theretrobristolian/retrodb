#!/usr/bin/env python3
"""Preview or apply conservative Sega 32X ZIP filename normalisation.

Target: <game title> (<region>).zip (No-Intro-inspired presentation, not a
claim that the ROM was verified by No-Intro). Only the ZIP's filename changes;
the internal ROM entry and its bytes are intentionally left untouched.

All proposals use the existing 32X audit (single-ROM ZIP and streamed RA MD5).
A fresh audit is required at apply time; all destination collisions, including
case-insensitive ones, are rejected before any file is renamed. Case-only
changes are treated as already valid to avoid CIFS case-alias overwrites.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

from report_32x_audit import audit, filename_region

LANGUAGES = re.compile(
    r"^(?:en|fr|de|es|it|pt|nl|ja|jp|sv|no|da|fi|ru|ko|zh)"
    r"(?:\s*[,;+/]\s*(?:en|fr|de|es|it|pt|nl|ja|jp|sv|no|da|fi|ru|ko|zh))*$",
    re.I,
)
# These qualifiers describe distinct ROM revisions, unreleased versions or
# modifications. We cannot drop them without potentially hiding differences.
SPECIAL = re.compile(
    r"\b(?:proto(?:type)?|beta|alpha|demo|sample|hack|patch(?:ed)?|"
    r"translation|translated|unl(?:icensed)?|rev(?:ision)?|"
    r"bad dump|overdump|alt(?:ernate)?|pirate|homebrew|"
    r"working|fixed)\b",
    re.I,
)
UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def canonical_name(filename: str, verified_title: str = "", verified_region: str = "") -> tuple[str, str]:
    """Return (target name, review reason). Never guess a missing region."""
    if not filename.lower().endswith(".zip"):
        return "", "Not a ZIP"
    stem = Path(filename).stem
    stem = re.sub(r"^\s*\[32x\]\s*", "", stem, flags=re.I).strip()
    if SPECIAL.search(stem):
        return "", "Modified, revised or prototype ROM requires manual naming review"
    # Strip only suffix metadata; keep parenthesised words inside actual titles.
    while True:
        match = re.search(r"\s*\(([^()]*)\)\s*$", stem)
        if not match:
            break
        value = match.group(1).strip()
        if SPECIAL.search(value):
            return "", "Revision, hack or prototype requires manual naming review"
        if filename_region("(" + value + ")") or LANGUAGES.fullmatch(value):
            stem = stem[:match.start()].strip()
            continue
        break
    # A title backed by an exact registered RA hash is preferred when it is a
    # normal retail title, not an RA-labelled hack or prototype.
    title = stem
    if verified_title and not SPECIAL.search(verified_title):
        candidate = re.sub(r"^\s*~[^~]+~\s*", "", verified_title).strip()
        # Colons and slashes in catalogue names are formatting punctuation,
        # but not portable ZIP filenames on FAT/SMB/Windows.
        candidate = re.sub(r"\s*[:/|]\s*", " - ", candidate)
        if candidate and not UNSAFE_FILENAME.search(candidate):
            title = candidate
    source_region = filename_region(filename)
    region = source_region or verified_region
    if source_region and verified_region:
        source_parts = {part.strip() for part in source_region.split(",")}
        verified_parts = {part.strip() for part in verified_region.split(",")}
        if source_parts == verified_parts:
            region = verified_region  # Official No-Intro-like region ordering.
        else:
            return "", "Filename region conflicts with exact registered ROM hash region"
    if not region:
        return "", "No explicit source or verified-hash region"
    if not title or title in {".", ".."} or UNSAFE_FILENAME.search(title):
        return "", "Invalid or unsafe game title"
    if SPECIAL.search(title):
        return "", "Special build name requires manual review"
    # Windows / SMB / FAT-compatible conservative names.
    title = re.sub(r"\s+", " ", title).strip(" .")
    if not title or len(title) > 170:
        return "", "Title is empty or too long"
    return f"{title} ({region}).zip", ""


def registered_hash_regions(hash_dir: Path | None, game_id: str, md5: str) -> str:
    """Fallback to the name registered for THIS hash, never a different variant."""
    if not hash_dir or not game_id or not md5:
        return ""
    path = hash_dir / f"{game_id}.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    if not isinstance(rows, list):
        return ""
    regions = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        registered = str(row.get("MD5") or row.get("Hash") or "").lower()
        if registered != md5.lower():
            continue
        region = filename_region(str(row.get("Name") or row.get("Description") or ""))
        if region:
            regions.add(region)
    return regions.pop() if len(regions) == 1 else ""


def plan(root: Path, catalogue: Path, hash_dir: Path | None = None) -> list[dict[str, str]]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Sega 32X library is unavailable or a symbolic link")
    records = audit(root, catalogue, hash_dir)
    proposals = []
    for row in records:
        old = row["relative_path"]
        archive = root / old
        record = dict(status="REVIEW", source=old, target="", region=row["region"],
                      audit_status=row["status"], reason="")
        if archive.is_symlink() or not archive.is_file():
            record["reason"] = "Source is unavailable or is a symbolic link"
        elif not row.get("rom_member"):
            record["reason"] = row.get("reason") or "ZIP has no single validated ROM member"
        elif (row["status"] in ("EXACT_RA", "EXACT_NO_SET")
              and SPECIAL.search(str(row.get("ra_title") or ""))):
            record["reason"] = "Verified RA identity is a prototype, hack or special build"
        else:
            exact = row["status"] in ("EXACT_RA", "EXACT_NO_SET")
            trusted_region = registered_hash_regions(
                hash_dir, str(row["ra_game_id"]), str(row["ra_md5"])
            ) if exact else ""
            target_name, reason = canonical_name(
                archive.name, row["ra_title"] if exact else "", trusted_region
            )
            if not target_name:
                record["reason"] = reason
            else:
                proposed = (Path(old).parent / target_name).as_posix()
                record["region"] = filename_region(archive.name) or trusted_region
                record["target"] = proposed
                record["status"] = ("VALID" if old.casefold() == proposed.casefold()
                                    else "RENAME_CANDIDATE")
        proposals.append(record)
    # Never overwrite even if destination is one of the sources in this batch.
    # Doing so creates an order-dependent rename. Require explicit resolution.
    occupied: dict[str, set[str]] = {}
    for file in root.rglob("*"):
        if file.is_file():
            occupied.setdefault(file.relative_to(root).as_posix().casefold(), set()).add(
                file.relative_to(root).as_posix()
            )
    destinations: dict[str, list[dict[str, str]]] = {}
    for row in proposals:
        if row["status"] != "RENAME_CANDIDATE":
            continue
        key = row["target"].casefold()
        destinations.setdefault(key, []).append(row)
        competing = occupied.get(key, set()) - {row["source"]}
        if competing:
            row["status"] = "REVIEW_COLLISION"
            row["reason"] = "Target already exists (case-insensitive comparison)"
    for proposals_same_name in destinations.values():
        if len(proposals_same_name) > 1:
            for row in proposals_same_name:
                row["status"] = "REVIEW_COLLISION"
                row["reason"] = "Multiple archives would receive the same name"
    return proposals


def apply(root: Path, rows: list[dict[str, str]], journal: Path) -> int:
    """Rename only outer ZIPs with a write-ahead, resumable-by-hand journal."""
    candidates = [row for row in rows if row["status"] == "RENAME_CANDIDATE"]
    if journal.exists():
        raise ValueError("Journal already exists; inspect it before continuing")
    if journal.is_symlink():
        raise ValueError("Journal must not be a symbolic link")
    journal.parent.mkdir(parents=True, exist_ok=True)
    # Recheck every source and destination immediately before writing.
    for row in candidates:
        src = root / row["source"]
        dst = root / row["target"]
        if (src.is_symlink() or not src.is_file() or dst.exists() or dst.is_symlink()
                or src.parent != dst.parent):
            raise ValueError(f"Source or destination changed: {row['source']}")
    summary = {"schema": 1, "operations": [
        {"source": row["source"], "target": row["target"], "state": "pending"}
        for row in candidates
    ]}
    def record():
        temporary = journal.with_name(journal.name + ".tmp")
        temporary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, journal)
    if not candidates:
        return 0
    record()
    applied = 0
    for entry in summary["operations"]:
        source = root / entry["source"]
        dest = root / entry["target"]
        try:
            if source.is_symlink() or not source.is_file() or dest.exists() or dest.is_symlink():
                raise ValueError("Source or destination changed")
            os.rename(source, dest)
            entry["state"] = "done"
            applied += 1
            record()
        except (OSError, ValueError):
            entry["state"] = "failed"
            record()
            raise RuntimeError(
                f"Stopped after {applied} renames; inspect journal before retry: {journal}"
            )
    return applied


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "apply"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ra-catalogue", type=Path, required=True)
    parser.add_argument("--ra-hashes-dir", type=Path)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    if args.action == "apply" and (args.confirm != "RENAME 32X" or not args.journal):
        parser.error("Applying requires --journal and --confirm 'RENAME 32X'")
    rows = plan(args.root, args.ra_catalogue, args.ra_hashes_dir)
    counts = Counter(row["status"] for row in rows)
    print(f"Sega 32X: {len(rows)} ZIPs inspected")
    for status in ("VALID", "RENAME_CANDIDATE", "REVIEW", "REVIEW_COLLISION"):
        if counts.get(status):
            print(f"  {status}: {counts[status]}")
    for row in rows:
        if row["status"] == "RENAME_CANDIDATE":
            print(f"  RENAME  {row['source']}  ->  {row['target']}")
        elif row["status"].startswith("REVIEW"):
            print(f"  REVIEW  {row['source']}: {row['reason']}")
    if args.action == "preview":
        print("[INFO] Preview only: no ZIPs or internal ROMs modified.")
        return 0
    count = apply(args.root, rows, args.journal)
    print(f"[OK] Renamed {count} ZIPs; the internal ROM filenames and contents are unchanged.")
    if count:
        print("[INFO] Re-run Sega 32X audit to refresh the web catalogue's filenames.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        sys.exit(f"[ERROR] {exc}")
