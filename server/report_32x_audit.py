#!/usr/bin/env python3
"""Read-only Sega 32X ZIP audit using official RetroAchievements ROM MD5s.

The entire ZIP is never hashed: the selected ROM member is streamed to MD5.
No file is renamed, extracted to disk, modified or deleted.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import zipfile

MAX_ROM = 64 * 1024 * 1024
ROM_SUFFIXES = {".32x", ".bin", ".md", ".smd", ".gen"}
HASH = re.compile(r"^[a-fA-F0-9]{32}$")
FIELDS = [
    "status", "filename", "relative_path", "display_title", "title_source",
    "region", "rom_member", "rom_size_bytes", "ra_md5", "ra_game_id",
    "ra_title", "ra_achievements", "suggested_ra_game_id",
    "suggested_ra_title", "suggested_release", "suggested_region",
    "suggestion_evidence", "local_verified_variant",
    "ra_supported_md5", "reason",
]

def title_key(title):
    value = unicodedata.normalize("NFKD", str(title)).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"\[[^\]]*\]", " ", value)
    value = re.sub(r"\((?:USA|Europe|Japan|World|Asia|Brazil|Australia|En|Proto|Rev[^)]*)\)", " ", value, flags=re.I)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return " ".join(value.split())

def filename_title(name):
    value = re.sub(r"^\s*\[32X\]\s*", "", Path(name).stem, flags=re.I)
    value = re.sub(r"\s*\([^)]*\)", "", value).strip()
    return value or Path(name).stem

def filename_region(name):
    """Preserve explicit single/multiple region labels, never infer from RA."""
    aliases = {"usa": "USA", "u": "USA", "europe": "Europe",
               "e": "Europe", "japan": "Japan", "j": "Japan",
               "world": "World", "asia": "Asia", "brazil": "Brazil",
               "australia": "Australia"}
    regions = []
    for group in re.findall(r"\(([^()]*)\)", name):
        for token in re.split(r"[,/]", group):
            token = token.strip().lower()
            names = {"ju": ("Japan", "USA"), "jue": ("Japan", "USA", "Europe")}.get(token)
            if names is None:
                names = (aliases[token],) if token in aliases else ()
            for region in names:
                if region not in regions:
                    regions.append(region)
    return ", ".join(regions)



def load_catalogue(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("RetroAchievements catalogue must be a JSON game list")
    games, by_hash, by_title = {}, {}, defaultdict(list)
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        try:
            gid = int(entry["ID"])
            title = str(entry["Title"]).strip()
            count = int(entry.get("NumAchievements") or 0)
            system = int(entry.get("ConsoleID") or 10)
        except (ValueError, TypeError, KeyError):
            continue
        if system != 10 or not title or not title_key(title):
            continue
        row = (gid, title, count)
        games[gid] = row
        by_title[title_key(title)].append(row)
        for h in entry.get("Hashes", []):
            if isinstance(h, str) and HASH.fullmatch(h):
                by_hash.setdefault(h.lower(), row)
    if not games:
        raise ValueError("No official Sega 32X games in catalogue")
    return by_hash, by_title, games

# Curated identity aliases, linked to the official RA game IDs. These suggest
# an identity only; no alias can manufacture an exact ROM hash match.
# Sources: retroachievements.org/game/{id}, as reviewed for these releases.
REVIEWED_IDENTITIES = (
    (re.compile(r"doom.*ress?urrection|doom.*resurrection", re.I), 18179),
    (re.compile(r"pinocchio", re.I), 16800),
    (re.compile(r"soul\s*star\s*x|soulstar\s*x", re.I), 15989),
    (re.compile(r"virtua\s+racing\s+deluxe", re.I), 11823),
)


def candidate_by_identity(filename, stem, by_id, by_title):
    # A reviewed hack/prototype MUST be resolved before generic Doom matching.
    for pattern, game_id in REVIEWED_IDENTITIES:
        if pattern.search(filename):
            entry = by_id.get(game_id)
            if entry:
                return [entry], "Reviewed title alias (RA game/%s)" % game_id
    return list(dict.fromkeys(by_title.get(title_key(stem), []))), "Exact normalised title"


def rom_hash(path):
    """Return (ROM member name, size, MD5). Raise on ambiguous/invalid ZIPs."""
    with zipfile.ZipFile(path) as archive:
        candidates = [
            x for x in archive.infolist()
            if not x.is_dir() and not x.filename.startswith("__MACOSX/")
            and not x.filename.startswith("/")
            and ".." not in Path(x.filename).parts
            and Path(x.filename).suffix.lower() in ROM_SUFFIXES
        ]
        if len(candidates) != 1:
            raise ValueError(f"Expected one 32X ROM member; found {len(candidates)}")
        info = candidates[0]
        if not (0 < info.file_size <= MAX_ROM):
            raise ValueError("Invalid or oversized 32X ROM member")
        h = hashlib.md5()
        total = 0
        with archive.open(info) as handle:
            while chunk := handle.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ROM:
                    raise ValueError("32X ROM exceeds read limit")
                h.update(chunk)
        if total != info.file_size:
            raise ValueError("Truncated ZIP member")
        return info.filename, info.file_size, h.hexdigest()

def hash_descriptions(hash_dir, game_id):
    if not hash_dir:
        return []
    source = hash_dir / f"{game_id}.json"
    if not source.is_file():
        return []
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [(str(x.get("Name") or x.get("Description") or ""), str(x.get("MD5") or x.get("Hash") or "").lower())
            for x in payload if isinstance(x, dict)]

def audit(root, catalogue, hash_dir=None):
    if not root.is_dir():
        raise FileNotFoundError(f"32X collection directory unavailable: {root}")
    by_hash, by_title, by_id = load_catalogue(catalogue)
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".zip":
            continue
        if "bios" in path.stem.casefold() or path.name.startswith("._"):
            continue
        stem = filename_title(path.name)
        region = filename_region(path.name)
        row = {field: "" for field in FIELDS}
        row.update(filename=path.name, relative_path=path.relative_to(root).as_posix(),
                   display_title=stem, title_source="filename (unverified)", region=region,
                   status="REVIEW", reason="")
        try:
            member, size, md5 = rom_hash(path)
            row.update(rom_member=member, rom_size_bytes=size, ra_md5=md5)
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
            row.update(status="REVIEW", reason=str(exc)[:200])
            rows.append(row)
            continue
        match = by_hash.get(md5)
        if match:
            gid, title, count = match
            row.update(display_title=title, title_source="RetroAchievements hash",
                       ra_game_id=gid, ra_title=title, ra_achievements=count,
                       status="EXACT_RA" if count else "EXACT_NO_SET")
        else:
            matches, identity_evidence = candidate_by_identity(path.name, stem, by_id, by_title)
            if len(matches) == 1:
                gid, title, count = matches[0]
                row.update(display_title=title, title_source="RetroAchievements title candidate",
                           suggested_ra_game_id=gid, suggested_ra_title=title,
                           status="ALTERNATIVE_REVIEW" if count else "NO_SET_CANDIDATE",
                           reason=identity_evidence + "; local ROM hash not registered")
                descriptions = hash_descriptions(hash_dir, gid)
                # Metadata gives supported names, but never invent a downloadable URL.
                if descriptions:
                    row["suggested_release"] = "; ".join(name for name, _ in descriptions[:4] if name)[:500]
                    row["suggestion_evidence"] = "Registered RetroAchievements hash release descriptions"
                    for name, _ in descriptions:
                        candidate = filename_region(name)
                        if candidate and candidate != region:
                            row["suggested_region"] = candidate
                            break
                if count:
                    row["ra_supported_md5"] = "; ".join(
                        sorted(h for h, mapped in by_hash.items() if mapped[0] == gid))[:512]
            elif len(matches) > 1:
                row.update(status="AMBIGUOUS_TITLE", reason="Multiple official RA titles share this filename title")
            else:
                row.update(status="UNMATCHED", reason="MD5 absent from RA catalogue; no unique title match")
        rows.append(row)

    # A verified compatible ROM already in this collection is an actionable soft pass.
    matched_by_title = defaultdict(list)
    for row in rows:
        if row["status"] == "EXACT_RA" and row["ra_game_id"]:
            matched_by_title[str(row["ra_game_id"])].append(row)
    for row in rows:
        if row["status"] != "ALTERNATIVE_REVIEW":
            continue
        variants = matched_by_title.get(str(row["suggested_ra_game_id"]), [])
        if variants:
            row["status"] = "SOFT_PASS_VARIANT"
            row["local_verified_variant"] = "; ".join(x["relative_path"] for x in variants)
            row["reason"] = "This ZIP is not RA hash-matched; compatible same-game ZIP exists locally"
    return rows

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ra-catalogue", type=Path, required=True)
    parser.add_argument("--ra-hashes-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = audit(args.root, args.ra_catalogue, args.ra_hashes_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK] Sega 32X: audited {len(rows)} game ZIPs -> {args.output}")
    for state, count in sorted(Counter(row["status"] for row in rows).items()):
        print(f"  {state}: {count}")
    loose = sorted(p.relative_to(args.root).as_posix()
                   for p in args.root.rglob("*")
                   if p.is_file() and not p.is_symlink() and
                   p.suffix.lower() in ROM_SUFFIXES and
                   "bios" not in p.stem.casefold())
    if loose:
        print(f"[WARN] {len(loose)} loose ROM(s) excluded from ZIP audit:")
        for entry in loose[:20]:
            print(f"  [LOOSE] {entry}")
        if len(loose) > 20:
            print(f"  ... and {len(loose) - 20} more")
        print("[INFO] Archive single ROMs as ZIPs and re-run to include them; files unchanged.")
    print("[INFO] Only supported ROM members were hashed. TXT and BIOS ZIPs ignored.")
    print("[INFO] No ROMs, names, or archive contents were modified.")

if __name__ == "__main__":
    main()
