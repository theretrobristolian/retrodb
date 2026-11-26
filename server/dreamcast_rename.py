#!/usr/bin/env python3
"""Dreamcast layout organizer. Filename-based only; no claim of Redump hash verification."""
import argparse
import collections
import csv
import json
import os
from pathlib import Path
import re
import shlex
import stat

REGION = re.compile(r"\((?:USA|Europe|Japan|World|Asia|Australia|Brazil|France|Germany|Spain|Italy|Korea|United Kingdom)(?:\s*,\s*(?:USA|Europe|Japan|World|Asia|Australia|Brazil|France|Germany|Spain|Italy|Korea|United Kingdom))*\)", re.I)


def canonical(stem):
    """Conservative Redump-style formatting; never invent a region or edition."""
    stem = stem.strip()
    if not REGION.search(stem):
        raise ValueError("No explicit region; requires catalogue or manual identification")
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', stem) or stem.endswith((".", " ")):
        raise ValueError("Unsafe Windows filename")
    if stem.split(".")[0].upper() in {"CON","PRN","AUX","NUL", *("COM"+str(i) for i in range(1,10)), *("LPT"+str(i) for i in range(1,10))}:
        raise ValueError("Reserved Windows filename")
    m = re.fullmatch(r"(.+?), (The|A|An)(\s*\(.*)", stem, re.I)
    return m[2]+" "+m[1]+m[3] if m else stem


def regular(path):
    return not path.is_symlink() and path.is_file()


def tracks(descriptor):
    lines = descriptor.read_text(encoding="utf-8-sig").splitlines()
    if not lines or not lines[0].strip().isdigit():
        raise ValueError("Invalid GDI track count")
    count = int(lines[0])
    if count < 1 or len(lines[1:]) != count:
        raise ValueError("GDI track count mismatch")
    names = []
    for i, line in enumerate(lines[1:], 1):
        fields = shlex.split(line, posix=True)
        if len(fields) != 6 or int(fields[0]) != i:
            raise ValueError("Invalid GDI track descriptor")
        for j in (1,2,3,5):
            if int(fields[j]) < 0:
                raise ValueError("Invalid negative GDI field")
        name = fields[4]
        if not name or name in (".","..") or any(c in name for c in "/\\:"):
            raise ValueError("Unsafe GDI track path")
        p = descriptor.parent / name
        if not regular(p) or p.stat().st_size == 0:
            raise ValueError("Missing or empty GDI track: "+name)
        names.append(name)
    if len({n.casefold() for n in names}) != len(names):
        raise ValueError("Repeated GDI track filename; review manually")
    return names


def discover(root):
    """Root loose CHDs/GDIs, root game folders, and one level under format folders."""
    for child in sorted(root.iterdir()):
        if child.name.startswith((".", "OLD_", "NEW_")) or child.is_symlink():
            continue
        if child.is_file() and child.suffix.lower() in (".chd",".gdi"):
            yield child
        elif child.is_dir():
            if child.name.lower() in ("chd","gdi"):
                for item in sorted(child.iterdir()):
                    if item.name.startswith((".", "OLD_", "NEW_")) or item.is_symlink():
                        continue
                    if item.is_file() and item.suffix.lower() in (".chd",".gdi"):
                        yield item
                    elif item.is_dir():
                        yield from descriptors(item)
            else:
                yield from descriptors(child)


def descriptors(folder):
    for p in sorted(folder.iterdir()):
        if regular(p) and p.suffix.lower() in (".chd",".gdi") and not p.name.startswith(("OLD_", ".")):
            yield p


def plan(root):
    candidates = list(discover(root))
    parent_counts = collections.Counter(p.parent for p in candidates)
    claimed = collections.Counter()
    rows = []
    for p in candidates:
        fmt = p.suffix.lower()[1:]
        row = dict(source=p.relative_to(root).as_posix(), format=fmt,
                   destination="", status="REVIEW", reason="", files=[], size_bytes=0)
        rows.append(row)
        try:
            if p.stat().st_size == 0:
                raise ValueError("Empty image")
            title = canonical(p.stem)
            target = root / fmt / title
            dest = target / (title+"."+fmt)
            row["destination"] = dest.relative_to(root).as_posix()
            names = tracks(p) if fmt == "gdi" else []
            sources = [p, *(p.parent/n for n in names)]
            if fmt == "chd":
                with p.open("rb") as f:
                    if f.read(8) != b"MComprHD":
                        raise ValueError("Not a CHD header")
            row["size_bytes"] = sum(x.stat().st_size for x in sources)
            row["files"] = [(x.relative_to(root).as_posix(),
                              (target/(dest.name if x == p else x.name)).relative_to(root).as_posix(),
                              x.stat().st_size, x.stat().st_mtime_ns) for x in sources]
            if p == dest:
                row["status"] = "VALID"
                continue
            if p.parent not in (root, root/"chd", root/"gdi"):
                if parent_counts[p.parent] != 1 or set(p.parent.iterdir()) != set(sources):
                    raise ValueError("Folder contains other files or images; leave untouched")
            if any(q.is_symlink() for q in (target, target.parent)):
                raise ValueError("Symlink destination")
            if target.exists():
                raise ValueError("Destination folder exists; no overwrite")
            row["status"] = "PROPOSED"
            for src, dst, _, _ in row["files"]:
                claimed[src.casefold()] += 1
                claimed[dst.casefold()] += 1
        except (ValueError, OSError, UnicodeError) as e:
            row["reason"] = str(e)
    for row in rows:
        if row["status"] == "PROPOSED" and any(claimed[p.casefold()] > 1 for pair in row["files"] for p in pair[:2]):
            row.update(status="REVIEW", reason="Multiple images claim same source or destination")
    # A valid/review descriptor may also reference a source claimed by another proposal.
    source_owners = collections.Counter(src.casefold() for r in rows for src,_,_,_ in r["files"])
    for row in rows:
        if row["status"] == "PROPOSED" and any(source_owners[src.casefold()] > 1 for src,_,_,_ in row["files"]):
            row.update(status="REVIEW", reason="Shared track or descriptor")
    return rows


def apply(root, rows, journal):
    with journal.open("x", encoding="utf-8") as log:
        def record(**event):
            log.write(json.dumps(event)+"\n")
            log.flush()
            os.fsync(log.fileno())
        for row in rows:
            if row["status"] != "PROPOSED":
                continue
            files = row["files"]
            dest = root/row["destination"]
            target = dest.parent
            for src, dst, size, mtime in files:
                p = root/src
                if not regular(p) or (p.stat().st_size,p.stat().st_mtime_ns)!=(size,mtime):
                    raise RuntimeError("Source changed: "+src)
                if (root/dst).exists() or (root/dst).is_symlink():
                    raise RuntimeError("Destination changed: "+dst)
            if target.parent.is_symlink():
                raise RuntimeError("Unsafe format directory")
            target.parent.mkdir(exist_ok=True)
            target.mkdir()  # exclusive reservation; never overwrite an existing game
            moved = []
            try:
                record(event="begin", source=row["source"], destination=row["destination"], files=files)
                # Descriptor is moved last, after the tracks.
                for src,dst,_,_ in reversed(files):
                    if (root/dst).exists() or (root/dst).is_symlink():
                        raise RuntimeError("Destination collision: "+dst)
                    (root/src).rename(root/dst)
                    moved.append((src,dst))
                    record(event="move", source=src, destination=dst)
                if row["format"] == "gdi":
                    tracks(dest)
                record(event="complete", destination=row["destination"])
                print("DONE",row["destination"])
            except BaseException:
                for src,dst in reversed(moved):
                    if (root/src).exists() or (root/src).is_symlink():
                        raise RuntimeError("Rollback collision; inspect journal: "+src)
                    (root/dst).rename(root/src)
                    record(event="rollback", source=dst, destination=src)
                target.rmdir()
                raise
            # Leave old empty source directories in place intentionally.


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("operation",choices=("preview","apply","audit"))
    parser.add_argument("--root",required=True,type=Path)
    parser.add_argument("--journal",type=Path)
    parser.add_argument("--confirm")
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    if not args.root.is_dir() or args.root.is_symlink():
        parser.error("Dreamcast root unavailable")
    rows=plan(args.root)
    for row in rows:
        print(row["status"],row["source"],"->",row["destination"],row["reason"])
    print(dict(collections.Counter(r["status"] for r in rows)))
    if args.output:
        with args.output.open("w",newline="",encoding="utf-8") as f:
            cols=["source","format","destination","status","reason","size_bytes"]
            writer=csv.DictWriter(f,fieldnames=cols,extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    if args.operation=="apply":
        if args.confirm!="RENAME DREAMCAST" or not args.journal:
            parser.error("Explicit confirmation and journal required")
        apply(args.root,rows,args.journal)

if __name__=="__main__":
    main()
