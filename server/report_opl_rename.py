#!/usr/bin/env python3
"""Read-only OPL old-format ISO rename proposal from a RetroDB audit CSV."""
import argparse
import csv
import hashlib
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
        r"^Sega Ages 2500 Series Vol\.?\s*(\d+)\s*:\s*(.+)$",
        value, re.IGNORECASE
    )
    if sega:
        number, game = sega.groups()
        value = f"Sega Ages {number} {game}"
        if len(value) > TITLE_LIMIT:
            value = re.sub(r"\bIII\b", "3", value)
            value = re.sub(r"\bII\b", "2", value)
    value = clean_title(value)
    # Prefer a meaningful edition over a dangling article after truncation.
    if re.match(r"^Hyper Street Fighter II The Anniversary Edition$", value, re.I):
        return "Hyper Street Fighter II Anniv"
    # Shorten known verbose branding, retaining meaningful edition information.
    if len(value) > TITLE_LIMIT:
        value = re.sub(r"\bAnniversary\b", "Anniv", value, flags=re.I)
        value = re.sub(r"\bRevenge of Jesse James\b", "Jesse James", value, flags=re.I)
        value = re.sub(r"\bThe King of Fighters\b", "KOF", value, flags=re.I)
        value = re.sub(r"\bExtreme Offroad Edition\b", "Offroad Ed", value, flags=re.I)
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


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4194304), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_iso(root, relative):
    """Read a bounded first 8 MiB looking for SYSTEM.CNF/BOOT2 metadata.

    This is a heuristic preliminary inspection, not a full ISO9660 parser.
    Never trust filename/serial alone and never label a disc positively.
    """
    try:
        base = root.resolve()
        file = (base / relative).resolve(strict=True)
        if not file.is_relative_to(base):
            return "ERROR: source escaped read-only mount"
        with file.open("rb") as stream:
            data = stream.read(8 * 1024 * 1024)
        if len(data) < 32774 or data[32769:32774] != b"CD001":
            return "INCONCLUSIVE: ISO9660 primary descriptor not at standard sector"
        boot_ids = sorted(set(re.findall(
            rb"BOOT2?\s*=\s*(?:cdrom0?:)?[\\\\/]*([A-Z]{4}[_\\.-][0-9]{3}[_\\.-][0-9]{2})",
            data, flags=re.I,
        )))
        if boot_ids:
            ids = ", ".join(value.decode("ascii", "replace") for value in boot_ids)
            return "BOOT ID CANDIDATE: " + ids + " — confirm from SYSTEM.CNF"
        if b"SYSTEM.CNF" in data.upper():
            return "SYSTEM.CNF referenced; boot ID not recovered in bounded scan"
        return "INCONCLUSIVE: no boot metadata located in first 8 MiB"
    except (OSError, ValueError) as exc:
        return f"ERROR: {type(exc).__name__}: {exc}"


def propose(rows, verify_root=None):
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
            "Duplicate recommendation": "",
            "SHA256": "",
            "Disc inspection": "",
        }
        match = SERIAL.fullmatch(serial)
        if current.stem.casefold().endswith("no disc"):
            record["Status"] = "REVIEW"
            record["Notes"] = "Possible PS2 Network Adapter setup disc: confirm ISO identity before renaming"
        elif not match:
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
                trimmed = compact_title(title)
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
            record["Status"] = "PROPOSED"
            record["Notes"] = "Case-only rename; eventual executor should use temporary intermediate name"
    if verify_root:
        for row in results:
            if row["Status"] == "REVIEW" and row["Current filename"].lower().endswith(".no disc.iso"):
                row["Disc inspection"] = inspect_iso(verify_root, row["Current relative path"])
        groups = {}
        for row in results:
            if row["Status"] == "COLLISION":
                groups.setdefault(row["Proposed relative path"].casefold(), []).append(row)
        base = verify_root.resolve()
        for group in groups.values():
            for row in group:
                try:
                    candidate = (base / row["Current relative path"]).resolve(strict=True)
                    if not candidate.is_relative_to(base):
                        raise ValueError("Outside permitted mount")
                    row["SHA256"] = sha256_file(candidate)
                except (OSError, ValueError) as exc:
                    row["Duplicate recommendation"] = f"UNVERIFIED — {type(exc).__name__}: {exc}"
            values = [row["SHA256"] for row in group]
            if len(values) > 1 and all(values):
                verdict = ("IDENTICAL SHA256 — manual removal candidate; retain one"
                           if len(set(values)) == 1 else
                           "DIFFERENT SHA256 — preserve and investigate")
                for row in group:
                    row["Duplicate recommendation"] = verdict
    return results

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_csv", type=Path)
    parser.add_argument("output_csv", type=Path)
    parser.add_argument("--verify-root", type=Path, help="Read-only root for hashing collision candidates")
    args = parser.parse_args()
    with args.audit_csv.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or not {"path", "platform", "local_serial", "gamedb_title"}.issubset(rows[0]):
        parser.error("Expected a current RetroDB compatibility audit CSV")
    proposals = propose(rows, args.verify_root)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "Current relative path", "Current filename", "Disc ID", "GameDB title",
            "Proposed filename", "Proposed relative path", "Display preview with RA",
            "Title truncated", "Status", "Notes", "Duplicate recommendation", "SHA256", "Disc inspection"])
        writer.writeheader()
        writer.writerows(proposals)
    counts = Counter(row["Status"] for row in proposals)
    print(f"[OK] Read-only OPL rename proposals: {args.output_csv}")
    print(" ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    print("[SAFE] No RetroNAS files were renamed, moved or modified.")

if __name__ == "__main__":
    main()
