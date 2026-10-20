#!/usr/bin/env python3
"""Reversible, journalled first-40 OPL rename pilot. Never alters ISO contents."""
import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

def safe(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts:
        raise ValueError(f"Unsafe relative path: {relative}")
    path = root / rel
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root):
        raise ValueError(f"Symlink in path: {relative}")
    return path

def plan(rows):
    # Select first 40 safe non-case-only title changes alphabetically.
    # Case-only changes need a separate two-stage SMB rename flow.
    eligible = [r for r in rows if r.get("Status") == "PROPOSED"
                and r.get("Proposed relative path")
                and r.get("Current relative path")
                and r["Current relative path"].casefold() != r["Proposed relative path"].casefold()]
    eligible.sort(key=lambda r: ((r.get("GameDB title") or r.get("Current filename") or "").casefold(),
                                 r["Current relative path"].casefold()))
    return eligible[:40]

def journal_write(path, data):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as h:
        json.dump(data, h, indent=2)
        h.flush()
        os.fsync(h.fileno())
    os.replace(tmp, path)

def check_targets(root, rows):
    targets = set()
    for row in rows:
        src = safe(root, row["Current relative path"])
        dst = safe(root, row["Proposed relative path"])
        if not src.is_file():
            raise ValueError(f"Source missing: {src}")
        if dst.exists():
            raise ValueError(f"Destination exists: {dst}")
        if src.stat().st_dev != dst.parent.stat().st_dev:
            raise ValueError("Rename would cross filesystems")
        key = str(dst).casefold()
        if key in targets:
            raise ValueError(f"Target collision: {dst}")
        targets.add(key)

def do_apply(root, rows, journal):
    if journal.exists():
        raise ValueError(f"Pilot journal already exists, rollback first: {journal}")
    check_targets(root, rows)
    operations = []
    for row in rows:
        src = safe(root, row["Current relative path"])
        dst = safe(root, row["Proposed relative path"])
        operations.append({"old":row["Current relative path"],"new":row["Proposed relative path"],
                           "size":src.stat().st_size,"state":"pending"})
    document = {"created":datetime.now(timezone.utc).isoformat(),"operations":operations}
    journal_write(journal, document)
    for op in operations:
        src = safe(root,op["old"])
        dst = safe(root,op["new"])
        if not src.is_file() or dst.exists() or src.stat().st_size != op["size"]:
            raise ValueError(f"Pre-rename validation failed: {src}")
        # Journal is durable BEFORE and AFTER every rename, recoverable by file existence.
        os.rename(src,dst)
        op["state"] = "applied"
        journal_write(journal,document)
        print(f"RENAMED {op['old']} -> {op['new']}",flush=True)
    print(f"[OK] Applied {len(operations)} renames. Rollback journal: {journal}")

def do_rollback(root,journal):
    doc = json.loads(journal.read_text(encoding="utf-8"))
    for op in reversed(doc["operations"]):
        old = safe(root,op["old"])
        new = safe(root,op["new"])
        if old.is_file() and not new.exists():
            op["state"] = "rolled-back"
            journal_write(journal,doc)
            continue
        if not new.is_file() or old.exists() or new.stat().st_size != op["size"]:
            raise ValueError(f"Rollback conflict; no overwrite: {new} -> {old}")
        os.rename(new,old)
        op["state"] = "rolled-back"
        journal_write(journal,doc)
        print(f"RESTORED {op['new']} -> {op['old']}",flush=True)
    print("[OK] Rollback completed. Journal retained as a permanent record.")

def main():
    a=argparse.ArgumentParser()
    a.add_argument("command",choices=["preview","apply","rollback"])
    a.add_argument("--csv",type=Path,required=True)
    a.add_argument("--root",type=Path,required=True)
    a.add_argument("--journal",type=Path,required=True)
    args=a.parse_args()
    root=args.root.resolve(strict=True)
    with args.csv.open(encoding="utf-8-sig",newline="") as f:
        entries=list(csv.DictReader(f))
    rows=plan(entries)
    if args.command=="preview":
        print(f"First {len(rows)} eligible alphabetical proposed PS2 renames:")
        for i,row in enumerate(rows,1):
            print(f"{i:02} {row['Current relative path']} -> {row['Proposed relative path']}")
        print(f"Journal: {args.journal}")
        return
    args.journal.parent.mkdir(parents=True,exist_ok=True)
    if args.command=="apply":
        if not rows: raise ValueError("No eligible proposals")
        do_apply(root,rows,args.journal)
    else:
        if not args.journal.is_file(): raise ValueError("No rollback journal")
        do_rollback(root,args.journal)

if __name__=="__main__":
    main()
