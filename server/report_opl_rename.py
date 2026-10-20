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


CURATED_DISPLAY_TITLES = {
    "wacky races starring dastardly and muttley": "Wacky Races Dastardly",
    "ready 2 rumble boxing round 2": "Ready 2 Rumble Round 2",
    "18 wheeler american pro trucker": "18 Wheeler Pro Trucker",
    "gungriffon blaze (enemy awgs disc)": "GunGriffon Blaze",
    "pinball hall of fame the gottlieb collection": "Pinball HoF Gottlieb",
    "pinball hall of fame the williams collection": "Pinball HoF Williams",
    "wrc 3 the official game of the fia world rally championship": "WRC 3 FIA Rally",
    "singstar pop (scus-97580)": "SingStar Pop",
    "blood omen 2 the legacy of kain series": "Blood Omen 2",
    "midnight club 3 dub edition remix": "Midnight Club 3 DUB Remix",
    "gunvari collection time crisis": "Gunvari and Time Crisis",
    "walt disneys the jungle book rhythm n groove": "Jungle Book Rhythm n Groove",
    "the lord of the rings the fellowship of the ring": "LOTR Fellowship of the Ring",
    "the lord of the rings the two towers": "LOTR The Two Towers",
    "the lord of the rings the return of the king": "LOTR Return of the King",
    "the lord of the rings the third age": "LOTR The Third Age",
    "the legend of spyro a new beginning": "Spyro A New Beginning",
    "the legend of spyro the eternal night": "Spyro The Eternal Night",
    "the legend of spyro dawn of the dragon": "Spyro Dawn of the Dragon",
    "spider-man web of shadows amazing allies edition": "Spidey Web of Shadows AA",
    "score international baja 1000 the official game": "SCORE Baja 1000",
    "short track racing trading paint": "Short Track Trading Paint",
    "mtv pimp my ride street racing": "Pimp My Ride Street Racing",
    "transformers revenge of the fallen": "Transformers Revenge Fallen",
    "the secret saturdays beasts of the 5th sun": "Secret Saturdays 5th Sun",
    "teenage mutant ninja turtles": "TMNT",
    "teenage mutant ninja turtles 2 battle nexus": "TMNT 2 Battle Nexus",
    "teenage mutant ninja turtles 3 mutant nightmare": "TMNT 3 Mutant Nightmare",
    "teenage mutant ninja turtles mutant melee": "TMNT Mutant Melee",
    "teenage mutant ninja turtles smash-up": "TMNT Smash-Up",
}

PILOT_DISPLAY_OVERRIDES = {
    "SLUS-20152": "Ace Combat 04 Shat Skies",
    "SLES-54617": "Action Man ATOM",
    "SLES-50282": "Age of Empires II",
    "SLES-50185": "Alone in the Dark New Night",
    "SLUS-21096": "Ape Escape Pumped Primed",
    "SCUS-97231": "Arc Lad Twilight Spirits",
    "SLUS-21043": "Backyard Wrestling 2",
    "SLUS-20638": "Backyard Wrestling",
    "SLES-53481": "10 000 Bullets",
    "SLES-51792": "Aliens vs Predator Extinct"
}

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
    preferred = CURATED_DISPLAY_TITLES.get(value.casefold())
    if preferred:
        return preferred
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
        if result.split()[-1].casefold() in {"vol", "volume", "series", "ser", "the", "of", "and", "a", "for", "starring"}:
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
    """Read ISO9660 root SYSTEM.CNF and its BOOT/BOOT2 ID without writing.

    Supports ordinary 2048-byte-sector ISO images. Unusual disc layouts
    remain inconclusive rather than receiving an invented identification.
    """
    try:
        base = root.resolve()
        file = (base / relative).resolve(strict=True)
        if not file.is_relative_to(base):
            return "ERROR: source escaped read-only mount"
        with file.open("rb") as stream:
            stream.seek(16 * 2048)
            pvd = stream.read(2048)
            if len(pvd) != 2048 or pvd[1:6] != b"CD001" or pvd[0] != 1:
                return "INCONCLUSIVE: standard ISO9660 primary descriptor absent"
            root_record = pvd[156:190]
            root_lba = int.from_bytes(root_record[2:6], "little")
            root_size = int.from_bytes(root_record[10:14], "little")
            if root_lba <= 0 or not 0 < root_size <= 4 * 1024 * 1024:
                return "INCONCLUSIVE: invalid ISO9660 root directory"
            stream.seek(root_lba * 2048)
            directory = stream.read(root_size)
            offset = 0
            cnf = None
            while offset < len(directory):
                length = directory[offset]
                if length == 0:
                    offset = ((offset // 2048) + 1) * 2048
                    continue
                entry = directory[offset:offset + length]
                if len(entry) < 34:
                    break
                name_size = entry[32]
                name = entry[33:33 + name_size].decode("ascii", "replace")
                if name.upper().split(";")[0] == "SYSTEM.CNF":
                    cnf = (int.from_bytes(entry[2:6], "little"),
                           int.from_bytes(entry[10:14], "little"))
                    break
                offset += length
            if cnf is None:
                return "INCONCLUSIVE: SYSTEM.CNF missing from ISO root"
            if cnf[0] <= 0 or not 0 < cnf[1] <= 65536:
                return "INCONCLUSIVE: invalid SYSTEM.CNF extent"
            stream.seek(cnf[0] * 2048)
            config = stream.read(cnf[1]).decode("latin-1", "replace")
        match = re.search(
            r"(?im)^\s*BOOT2?\s*=\s*(?:cdrom0?:)?[\\/]*"
            r"([A-Z]{4}[_\.-]\d{3}[_\.-]\d{2})", config
        )
        if match:
            return "SYSTEM.CNF BOOT ID: " + match.group(1).upper()
        return "SYSTEM.CNF read; BOOT/BOOT2 disc ID not recognised"
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
                trimmed = PILOT_DISPLAY_OVERRIDES.get(serial, compact_title(title))
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
