#!/usr/bin/env python3
"""Conservative Mega CD tidy: stage, verify and retain original directories."""
import argparse
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from report_megacd_audit import parse, inventory, ra_hash, FILE, INDEX

def layout(cue, title):
    lines, blocks = parse(cue)
    if len({b["width"] for b in blocks}) != 1:
        raise ValueError("Mixed sector widths cannot be merged losslessly")
    if not title or any(c in title for c in '<>:"/\\|?*') or title.endswith((" ", ".")):
        raise ValueError("Unsafe target title")
    if any(p.is_symlink() or not p.is_file() for p in cue.parent.iterdir()):
        raise ValueError("Unexpected nested directory or symlink")
    if {p.name for p in cue.parent.iterdir()} != {cue.name, *(b["path"].name for b in blocks)}:
        raise ValueError("Extra files require manual review")
    output = []
    offset = 0
    n = -1
    for line in lines:
        keyword = line.strip().split(maxsplit=1)[0].upper() if line.strip() else ""
        if keyword == "FILE":
            if n >= 0:
                offset += blocks[n]["frames"]
            n += 1
            if n == 0:
                output.append(f'FILE "{title}.bin" BINARY')
            elif blocks[n]["tracks"][0]["indexes"][0][1] != 0:
                raise ValueError("Continuation FILE has unindexed leading sectors")
        elif keyword == "INDEX":
            m = INDEX.fullmatch(line)
            frame = (int(m[2])*60 + int(m[3]))*75 + int(m[4]) + offset
            minute, rest = divmod(frame, 4500)
            second, sector = divmod(rest, 75)
            output.append(f"{m[1]}{minute:02}:{second:02}:{sector:02}")
        elif keyword in {"CDTEXTFILE", "POSTGAP"} or (keyword == "PREGAP" and len(blocks) > 1):
            raise ValueError("External metadata or explicit gaps need manual review")
        elif keyword not in {"", "REM", "TITLE", "PERFORMER", "SONGWRITER", "CATALOG", "TRACK", "FLAGS", "ISRC", "PREGAP"}:
            raise ValueError("Unsupported CUE directive: " + keyword)
        else:
            output.append(line)
    return blocks, "\n".join(output) + "\n"

def canonical_name(title):
    """Normalize inverted articles only; retain all release qualifiers."""
    match = re.fullmatch(r"(.+?), (The|A|An)(\s*(?:\([^()]*\)\s*)*)", title, re.I)
    return (match[2] + " " + match[1] + match[3]).strip() if match else title

def candidates(root):
    for row in inventory(root):
        target = canonical_name(row["folder"])
        if row["status"] != "TIDY_CANDIDATE" and not (row["status"] == "VALID" and target != row["folder"]):
            if row["status"] == "REVIEW":
                print(f"REVIEW {row['folder']}: {row['reason']}")
            continue
        cue = root / row["folder"] / row["filename"]
        try:
            blocks, text = layout(cue, target)
            if target != row["folder"] and ((root / target).exists() or (root / target).is_symlink()):
                raise ValueError("Canonical folder already exists")
        except (ValueError, OSError) as exc:
            print(f"REVIEW {row['folder']}: {exc}")
            continue
        yield cue, blocks, text

def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def write_verified(blocks, target):
    expected = []
    with target.open("xb") as out:
        for b in blocks:
            h = hashlib.sha256()
            size = 0
            with b["path"].open("rb") as src:
                for chunk in iter(lambda: src.read(1024*1024), b""):
                    out.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
            if size != b["frames"] * b["width"]:
                raise ValueError("Source changed during copy")
            expected.append((size, h.hexdigest()))
        out.flush()
        os.fsync(out.fileno())
    with target.open("rb") as f:
        for size, checksum in expected:
            h = hashlib.sha256()
            left = size
            while left:
                chunk = f.read(min(left, 1024*1024))
                if not chunk:
                    raise ValueError("Truncated merged BIN")
                h.update(chunk)
                left -= len(chunk)
            if h.hexdigest() != checksum:
                raise ValueError("Merged track checksum mismatch")
        if f.read(1):
            raise ValueError("Unexpected trailing bytes")
    for b, (_, checksum) in zip(blocks, expected):
        if digest(b["path"]) != checksum:
            raise ValueError("Original BIN changed during verification")

def record(journal, data):
    with journal.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data) + "\n")
        f.flush()
        os.fsync(f.fileno())

def apply(root, cue, blocks, text, hasher, journal):
    folder = cue.parent
    title = canonical_name(folder.name)
    destination = root / title
    token = uuid.uuid4().hex
    stage = root / (".megacd-stage-" + token)
    backup = root / ("OLD_" + folder.name)
    if backup.exists() or backup.is_symlink():
        # Preserve original split-track backups from previous verified merges.
        backup = root / ("OLD_" + folder.name + "-tidy-" + token)
    if destination != folder and (destination.exists() or destination.is_symlink()):
        raise ValueError("Destination collision")
    original_cue = digest(cue)
    before = ra_hash(cue, hasher)
    if not before:
        raise ValueError("Original RA hash unavailable")
    record(journal, dict(state="planned", folder=str(folder), destination=str(destination), stage=str(stage), backup=str(backup)))
    stage.mkdir()
    merged = stage / (title + ".bin")
    new_cue = stage / (title + ".cue")
    write_verified(blocks, merged)
    with new_cue.open("x", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    _, output = parse(new_cue)
    expected = []
    offset = 0
    for b in blocks:
        for t in b["tracks"]:
            expected.append((t["mode"], [(i, v+offset) for i,v in t["indexes"]]))
        offset += b["frames"]
    actual = [(t["mode"], t["indexes"]) for b in output for t in b["tracks"]]
    if expected != actual or digest(cue) != original_cue or ra_hash(new_cue, hasher) != before:
        raise ValueError("CUE layout or RA hash verification failed")
    record(journal, dict(state="verified", folder=str(folder), destination=str(destination), stage=str(stage), backup=str(backup), ra_hash=before))
    if backup.exists() or backup.is_symlink():
        raise ValueError("Backup collision")
    folder.rename(backup)
    record(journal, dict(state="original_retained", folder=str(folder), destination=str(destination), stage=str(stage), backup=str(backup)))
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination collision")
    stage.rename(destination)
    record(journal, dict(state="done", folder=str(folder), destination=str(destination), backup=str(backup), ra_hash=before))
    print("DONE", destination.name, "| original retained:", backup.name)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["preview", "apply"])
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--hasher", type=Path, default=Path("/opt/retrodb-tools/RAHasher"))
    p.add_argument("--journal", type=Path)
    p.add_argument("--confirm")
    a = p.parse_args()
    if not a.root.is_dir() or a.root.is_symlink():
        p.error("Root unavailable")
    if any(a.root.glob(".megacd-stage-*")):
        p.error("Interrupted staging directory exists; inspect journal before retrying")
    if a.mode == "apply" and (a.confirm != "RENAME MEGACD" or not a.journal):
        p.error("Explicit confirmation and journal required")
    plan = list(candidates(a.root))
    for cue, blocks, text in plan:
        print(f"PREVIEW {cue.parent.name}: {len(blocks)} BIN(s) -> {canonical_name(cue.parent.name)}.bin/.cue")
    print(f"Eligible: {len(plan)}; originals will be retained as OLD_ folders")
    if a.mode == "apply":
        with a.journal.open("x"):
            pass
        for cue, blocks, text in plan:
            apply(a.root, cue, blocks, text, a.hasher, a.journal)

if __name__ == "__main__":
    main()
