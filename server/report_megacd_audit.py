#!/usr/bin/env python3
"""Read-only Sega CD folder inventory; safe staging of simple raw-sector merges."""
import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

FILE = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))\s+BINARY\s*$', re.I)
TRACK = re.compile(r'^\s*TRACK\s+(\d+)\s+(MODE1/2352|AUDIO|MODE1/2048)\s*$', re.I)
INDEX = re.compile(r'^(\s*INDEX\s+\d+\s+)(\d+):(\d{2}):(\d{2})\s*$', re.I)
HASH = re.compile(r'(?<![0-9a-f])([0-9a-f]{32})(?![0-9a-f])', re.I)
FIELDS = ("title", "folder", "filename", "tracks", "files", "size_bytes", "serial",
          "status", "ra_hash", "ra_game_id", "ra_title", "ra_status", "reason",
          "collection_status", "candidate_ra_id", "local_alternative")

def parse(cue):
    if cue.is_symlink():
        raise ValueError("Symlink CUE")
    lines = cue.read_bytes().decode("utf-8-sig").splitlines()
    blocks = []
    current = None
    track = None
    last_track = 0
    for line in lines:
        keyword = line.strip().split(maxsplit=1)[0].upper() if line.strip() else ""
        if keyword == "FILE":
            m = FILE.fullmatch(line)
            if not m:
                raise ValueError("Unsupported FILE type")
            name = m[1] or m[2]
            if not name or any(c in name for c in '/\\:') or Path(name).suffix.lower() != ".bin":
                raise ValueError("Unsafe or non-BIN reference")
            path = cue.parent / name
            if path.is_symlink() or not path.is_file() or name not in {p.name for p in cue.parent.iterdir()}:
                raise ValueError("Missing or unsafe BIN: " + name)
            if any(b["path"] == path for b in blocks):
                raise ValueError("Repeated FILE reference")
            current = {"path": path, "lines": [], "tracks": []}
            blocks.append(current)
            track = None
        elif keyword == "TRACK":
            m = TRACK.fullmatch(line)
            if not current or not m or int(m[1]) != last_track + 1:
                raise ValueError("Invalid or unsupported TRACK")
            last_track += 1
            track = {"mode": m[2].upper(), "indexes": []}
            current["tracks"].append(track)
            current["lines"].append(line)
        elif keyword == "INDEX":
            m = INDEX.fullmatch(line)
            if not track or not m or int(m[3]) >= 60 or int(m[4]) >= 75:
                raise ValueError("Invalid INDEX")
            index_no = int(line.split()[1])
            frame = (int(m[2])*60 + int(m[3]))*75 + int(m[4])
            track["indexes"].append((index_no, frame))
            current["lines"].append(line)
        elif current:
            current["lines"].append(line)
    if not blocks:
        raise ValueError("No FILE references")
    for b in blocks:
        if not b["tracks"]:
            raise ValueError("FILE has no tracks")
        widths = {2048 if t["mode"] == "MODE1/2048" else 2352 for t in b["tracks"]}
        if len(widths) != 1:
            raise ValueError("Mixed sector widths in one BIN")
        b["width"] = widths.pop()
        size = b["path"].stat().st_size
        if not size or size % b["width"]:
            raise ValueError("BIN not aligned to sector size")
        b["frames"] = size // b["width"]
        previous = -1
        for t in b["tracks"]:
            if not any(i == 1 for i, _ in t["indexes"]):
                raise ValueError("TRACK missing INDEX 01")
            for _, frame in t["indexes"]:
                if frame < previous or frame >= b["frames"]:
                    raise ValueError("INDEX outside BIN or out of order")
                previous = frame
    return lines, blocks

def serial(blocks):
    first = blocks[0]
    track = first["tracks"][0]
    if track["mode"] == "AUDIO":
        return ""
    start = next(f for i, f in track["indexes"] if i == 1)
    with first["path"].open("rb") as f:
        f.seek(start * first["width"] + (16 if first["width"] == 2352 else 0))
        header = f.read(512)
    if not header.startswith(b"SEGADISCSYSTEM"):
        return ""
    return header[0x180:0x18e].decode("ascii", errors="replace").strip()

def catalogue(path):
    if not path or not path.is_file():
        return None
    result = {}
    for g in json.loads(path.read_text()):
        if int(g.get("ConsoleID", 9)) != 9:
            continue
        for h in g.get("Hashes", []):
            if isinstance(h, str) and HASH.fullmatch(h):
                result.setdefault(h.lower(), []).append(g)
    return result

def ra_hash(cue, hasher):
    try:
        p = subprocess.run([str(hasher), "9", str(cue)], capture_output=True, text=True, timeout=180)
        matches = HASH.findall(p.stdout)
        return matches[-1].lower() if p.returncode == 0 and matches else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""

def inventory(root, hasher=None, lookup=None):
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Mega CD root unavailable")
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or folder.is_symlink() or folder.name.startswith((".", "OLD_")):
            continue
        cues = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".cue")
        bins = {p.name for p in folder.iterdir() if p.suffix.lower() == ".bin"}
        if not cues and not bins:
            continue
        for cue in cues or [None]:
            row = dict.fromkeys(FIELDS, "")
            row.update(title=folder.name, folder=folder.name, filename=cue.name if cue else "",
                       status="REVIEW", ra_status="NOT_CHECKED")
            try:
                if not cue or len(cues) != 1:
                    raise ValueError("Expected exactly one CUE per disc folder")
                _, blocks = parse(cue)
                names = {b["path"].name for b in blocks}
                if names != bins:
                    raise ValueError("Orphaned BIN files")
                row.update(tracks=sum(len(b["tracks"]) for b in blocks), files=len(blocks),
                           size_bytes=sum(b["path"].stat().st_size for b in blocks),
                           serial=serial(blocks), status="VALID")
                if len(blocks) > 1 or cue.stem != folder.name or blocks[0]["path"].stem != folder.name:
                    row["status"] = "TIDY_CANDIDATE"
                if hasher:
                    h = ra_hash(cue, hasher)
                    row["ra_hash"] = h
                    row["ra_status"] = "HASH_ERROR" if not h else "NOT_CHECKED"
                    if h and lookup is not None:
                        games = lookup.get(h, [])
                        row["ra_status"] = "UNMATCHED"
                        if len(games) == 1:
                            game = games[0]
                            row.update(ra_game_id=game["ID"], ra_title=game["Title"],
                                       ra_status="SUPPORTED" if int(game.get("NumAchievements") or 0) > 0 else "NO_SET")
                        elif games:
                            row["ra_status"] = "AMBIGUOUS"
            except (ValueError, OSError, UnicodeError) as exc:
                row.update(status="REVIEW", reason=str(exc))
            yield row

def title_key(title):
    title = re.sub(r"\s*\([^()]*\)", "", title)
    title = re.sub(r"^(.+?), (The|A|An)$", r"\2 \1", title, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", title.casefold())

# Reviewed release aliases are suggestions, never verified hash matches.
ALIASES = {"battlefrenzy": "bloodshot", "beastii": "shadowofthebeastii",
           "blackholeassault": "blackholeassault"}

def reconcile(rows, lookup):
    def key(title):
        k = title_key(title)
        return ALIASES.get(k, k)
    games = {}
    for group in (lookup or {}).values():
        for g in group:
            for title in str(g.get("Title", "")).split("|"):
                games.setdefault(key(title), {})[str(g["ID"])] = g
    for row in rows:
        row.update(collection_status=row["ra_status"], candidate_ra_id="", local_alternative="")
        if row["ra_status"] != "UNMATCHED":
            continue
        k = key(row["title"])
        local = [r for r in rows if r["ra_status"] in ("SUPPORTED", "NO_SET")
                 and key(r["title"].split(" ~ ")[0]) == k]
        ids = {str(r["ra_game_id"]) for r in local}
        if len(ids) == 1:
            alt = sorted(local, key=lambda r: (r["ra_status"] != "SUPPORTED", r["folder"]))[0]
            row.update(collection_status="SOFT_PASS" if alt["ra_status"] == "SUPPORTED" else "SOFT_PASS_NO_SET",
                       candidate_ra_id=alt["ra_game_id"], local_alternative=alt["folder"],
                       reason="Another local release has an exact registered RA hash; this image remains unmatched")
        else:
            candidates = games.get(k, {})
            if len(candidates) == 1:
                ident, game = next(iter(candidates.items()))
                row.update(collection_status="ALTERNATIVE_REQUIRED" if int(game.get("NumAchievements") or 0) else "TITLE_NO_SET",
                           candidate_ra_id=ident,
                           reason="Catalogue title candidate only; local hash not registered")
            else:
                row.update(collection_status="REVIEW",
                           reason="No unique title candidate in cached registered-hash catalogue; check alternate titles or missing listing")
    return rows

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--hasher", type=Path)
    p.add_argument("--ra-catalogue", type=Path)
    a = p.parse_args()
    lookup = catalogue(a.ra_catalogue)
    rows = reconcile(list(inventory(a.root, a.hasher, lookup)), lookup)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print(f"[OK] Mega CD: {len(rows)} disc inventory records; archives ignored")
    for key in ("status", "ra_status", "collection_status"):
        print("  " + ", ".join(f"{k}: {v}" for k,v in sorted(Counter(r[key] for r in rows).items())))
    print(f"[READY] {a.output}")

if __name__ == "__main__":
    main()
