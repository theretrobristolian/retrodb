#!/usr/bin/env python3
"""Read-only OPL old-format ISO rename proposal from a RetroDB audit CSV."""
import argparse
import csv
import re
import unicodedata
from collections import Counter
from pathlib import Path

# OPL old naming: SLES_123.45.Title.iso, 32 characters for the title.
# Reserve space in OPL's displayed title for the dynamic ' [RA]' badge.
TITLE_LIMIT = 27
SERIAL = re.compile(r"^([A-Z]{4})-([0-9]{3})([0-9]{2})$")
NONPRINT = re.compile(r"[^A-Za-z0-9 ()\[\]_-]+")

def clean_title(value):
    # Transliterate diacritics BEFORE stripping punctuation: Ōkami -> Okami.
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.replace("&", " and ")
    value = value.replace("'", "")
    value = NONPRINT.sub(" ", value)
    return " ".join(value.split()).strip(" ._-")


def compact_title(value):
    """Preserve the distinctive game, series and volume rather than truncating blindly."""
    sega = re.match(
        r"^Sega Ages 2500 Series Vol\\.?\\s*(\\d+)\\s*:\\s*(.+)$",
        value, re.IGNORECASE
    )
    if sega:
        number, game = sega.groups()
        value = f"Sega Ages {number} {game}"
        if len(value) > TITLE_LIMIT:
            value = re.sub(r"\\bIII\\b", "3", value)
            value = re.sub(r"\\bII\\b", "2", value)
    # Prefer complete words, but retain a full series volume or sequel marker.
    if len(value) <= TITLE_LIMIT:
        return value
    words = value.split()
    chosen = []
    for word in words:
        candidate = " ".join(chosen + [word])
        if len(candidate) > TITLE_LIMIT:
            break
        chosen.append(word)
    if chosen:
        result = " ".join(chosen)
        # Avoid leaving a dangling series designator, e.g. "Vol".
        if result.split()[-1].casefold() in {"vol", "volume", "series", "ser"}:
            result = " ".join(result.split()[:-1])
        if result:
            return result
    return value[:TITLE_LIMIT].rstrip(" ._-")


def propose(rows):
    results = []
    for row in rows:
        path = row.get("path", "")
        if row.get("platform") != "Sony PlayStation 2" or not path.lower().endswith(".iso"):
            continue
        current = Path(path)
        serial = row.get("local_serial", "").upper().strip()
        title = (row.get("gamedb_title") or "").strip()
        record = {
            "Current relative path": path,
            "Current filename": current.name,
            "Disc ID": serial,
            "GameDB title": title,
            "Proposed filename": "",
            "Proposed relative path": "",
            "Display preview with RA": "",
            "Title truncated": "NO",
            "Status": "",
            "Notes": "",
        }
        match = SERIAL.fullmatch(serial)
        if not match:
            record["Status"] = "REVIEW"
            record["Notes"] = "Disc serial unavailable or not in the standard PS2 pattern"
        elif not title:
            record["Status"] = "REVIEW"
            record["Notes"] = "No GameDB title; do not guess from file name"
        else:
            prefix = f"{match[1]}_{match[2]}.{match[3]}"
            cleaned = clean_title(title)
            if not cleaned:
                record["Status"] = "REVIEW"
                record["Notes"] = "GameDB title became empty after sanitisation"
            else:
                trimmed = compact_title(cleaned)
                record["Title truncated"] = "YES" if trimmed != cleaned else "NO"
                proposed = f"{prefix}.{trimmed}.iso"
                target = str(current.with_name(proposed))
                record["Proposed filename"] = proposed
                record["Proposed relative path"] = target
                record["Display preview with RA"] = trimmed + " [RA]"
                record["Status"] = "UNCHANGED" if proposed == current.name else "PROPOSED"
                if trimmed != cleaned:
                    record["Notes"] = "Game title shortened to reserve five display characters for [RA]"
        results.append(record)

    # Reject target collisions, including case-only differences on SMB shares.
    targets = Counter(r["Proposed relative path"].casefold() for r in results
                      if r["Proposed relative path"])
    current_paths = {r["Current relative path"].casefold() for r in results}
    for record in results:
        target = record["Proposed relative path"]
        if not target:
            continue
        if targets[target.casefold()] > 1:
            record["Status"] = "COLLISION"
            record["Notes"] = "More than one source ISO proposes the same destination; do not rename"
        elif target.casefold() in current_paths and target.casefold() != record["Current relative path"].casefold():
            record["Status"] = "COLLISION"
            record["Notes"] = "Destination filename already belongs to another ISO in this audit"
        elif target.casefold() == record["Current relative path"].casefold() and target != record["Current relative path"]:
            record["Status"] = "REVIEW"
            record["Notes"] = "Case-only rename; review SMB filesystem behaviour"
    return results

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_csv", type=Path)
    parser.add_argument("output_csv", type=Path)
    args = parser.parse_args()
    with args.audit_csv.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or not {"path", "platform", "local_serial", "gamedb_title"}.issubset(rows[0]):
        parser.error("Expected a current RetroDB compatibility audit CSV")
    proposals = propose(rows)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "Current relative path", "Current filename", "Disc ID", "GameDB title",
            "Proposed filename", "Proposed relative path", "Display preview with RA",
            "Title truncated", "Status", "Notes"])
        writer.writeheader()
        writer.writerows(proposals)
    counts = Counter(row["Status"] for row in proposals)
    print(f"[OK] Read-only OPL rename proposals: {args.output_csv}")
    print(" ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    print("[SAFE] No RetroNAS files were renamed, moved or modified.")

if __name__ == "__main__":
    main()
