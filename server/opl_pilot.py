#!/usr/bin/env python3
"""Reversible, journalled OPL bulk renaming. Never alters ISO contents."""
import argparse
import csv
import json
import os
import uuid
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
    # Include ordinary and case-only proposals; exclude exact no-op paths.
    eligible = [r for r in rows if r.get("Status") == "PROPOSED"
                and r.get("Proposed relative path")
                and r.get("Current relative path")
                and r["Current relative path"] != r["Proposed relative path"]]
    eligible.sort(key=lambda r: ((r.get("GameDB title") or r.get("Current filename") or "").casefold(),
                                 r["Current relative path"].casefold()))
    return eligible

def journal_write(path, data):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as h:
        json.dump(data, h, indent=2)
        h.flush()
        os.fsync(h.fileno())
    os.replace(tmp, path)

def exact_exists(path):
    """Inspect actual directory spelling, avoiding case-insensitive SMB aliases."""
    try:
        return path.name in os.listdir(path.parent)
    except FileNotFoundError:
        return False

def location(root, op):
    paths = {name: safe(root, op[name]) for name in ("old", "new", "temp")}
    present = [name for name, path in paths.items() if exact_exists(path)]
    if len(present) > 1:
        raise ValueError(f"Ambiguous rename state {present}: {op['old']}")
    return present[0] if present else None

def move_file(src, dst, expected_size):
    if not exact_exists(src) or exact_exists(dst):
        raise ValueError(f"Unsafe move: {src} -> {dst}")
    if src.stat().st_size != expected_size:
        raise ValueError(f"Source size changed: {src}")
    os.rename(src, dst)
    # os.rename succeeding is authoritative; CIFS readdir may be cached immediately
    # afterward, so avoid a false failure from stale directory-entry enumeration.

def check_targets(root, rows):
    sources = set()
    targets = set()
    for row in rows:
        src = safe(root, row["Current relative path"])
        dst = safe(root, row["Proposed relative path"])
        if not exact_exists(src) or not src.is_file():
            raise ValueError(f"Source missing: {src}")
        case_only = str(src).casefold() == str(dst).casefold()
        if exact_exists(dst) and not case_only:
            raise ValueError(f"Destination exists: {dst}")
        if src.stat().st_dev != dst.parent.stat().st_dev:
            raise ValueError("Rename would cross filesystems")
        source_key, target_key = str(src).casefold(), str(dst).casefold()
        if source_key in sources or target_key in targets:
            raise ValueError(f"Duplicate source or target: {dst}")
        sources.add(source_key)
        targets.add(target_key)
    # Never target another source filename, even if it is scheduled to move.
    for row in rows:
        source_key = str(safe(root, row["Current relative path"])).casefold()
        target_key = str(safe(root, row["Proposed relative path"])).casefold()
        if target_key in sources and target_key != source_key:
            raise ValueError(f"Destination belongs to another source: {target_key}")

def do_apply(root, rows, journal):
    if journal.exists():
        raise ValueError(f"Rename journal already exists: {journal}")
    check_targets(root, rows)
    operations = []
    for row in rows:
        src = safe(root, row["Current relative path"])
        dst = safe(root, row["Proposed relative path"])
        temp = src.with_name(f".retrodb-rename-{uuid.uuid4().hex}.iso")
        while exact_exists(temp):
            temp = src.with_name(f".retrodb-rename-{uuid.uuid4().hex}.iso")
        operations.append({"old": row["Current relative path"],
                           "new": row["Proposed relative path"],
                           "temp": str(temp.relative_to(root)),
                           "size": src.stat().st_size,
                           "case_only": str(src).casefold() == str(dst).casefold(),
                           "state": "pending"})
    document = {"created": datetime.now(timezone.utc).isoformat(),
                "operations": operations}
    journal_write(journal, document)
    for op in operations:
        old = safe(root, op["old"])
        new = safe(root, op["new"])
        temp = safe(root, op["temp"])
        if op["case_only"]:
            move_file(old, temp, op["size"])
            op["state"] = "temporary"
            journal_write(journal, document)
            move_file(temp, new, op["size"])
        else:
            move_file(old, new, op["size"])
        op["state"] = "applied"
        journal_write(journal, document)
        print(f"RENAMED {op['old']} -> {op['new']}", flush=True)
    print(f"[OK] Applied {len(operations)} renames. Rollback journal: {journal}")

def do_resume(root, journal):
    """Continue a partially completed run, reconciling actual file locations."""
    document = json.loads(journal.read_text(encoding="utf-8"))
    for op in document["operations"]:
        old = safe(root, op["old"])
        new = safe(root, op["new"])
        temp = safe(root, op["temp"])
        state = location(root, op)
        if state is None:
            raise ValueError(f"Cannot locate any file for: {op['old']}")
        if state == "old":
            if op["case_only"]:
                move_file(old, temp, op["size"])
                op["state"] = "temporary"
                journal_write(journal, document)
                move_file(temp, new, op["size"])
            else:
                move_file(old, new, op["size"])
        elif state == "temp":
            move_file(temp, new, op["size"])
        elif state == "new":
            if new.stat().st_size != op["size"]:
                raise ValueError(f"Target size differs: {new}")
        op["state"] = "applied"
        journal_write(journal, document)
        print(f"[OK] {op['new']}", flush=True)
    print(f"[OK] Reconciled and applied {len(document['operations'])} entries.")

def do_status(root, journal):
    document = json.loads(journal.read_text(encoding="utf-8"))
    from collections import Counter
    outcomes = Counter()
    for op in document["operations"]:
        observed = location(root, op)
        outcomes[(op["state"], observed)] += 1
        if op["state"] != "applied" or observed != "new":
            print(f"[CHECK] journal={op['state']} disk={observed}: {op['old']} => {op['new']}")
    for (recorded, actual), count in sorted(outcomes.items()):
        print(f"Journal state {recorded}, current filename {actual}: {count}")

def do_rollback(root, journal):
    document = json.loads(journal.read_text(encoding="utf-8"))
    for op in reversed(document["operations"]):
        old = safe(root, op["old"])
        new = safe(root, op["new"])
        # Older journals made before case-only support have no temp field.
        if not op.get("temp"):
            if exact_exists(old) and not exact_exists(new):
                op["state"] = "rolled-back"
                journal_write(journal, document)
                continue
            if not exact_exists(new) or exact_exists(old):
                raise ValueError(f"Rollback conflict: {new} -> {old}")
            move_file(new, old, op["size"])
        else:
            temp = safe(root, op["temp"])
            state = location(root, op)
            if state == "old":
                op["state"] = "rolled-back"
                journal_write(journal, document)
                continue
            if state is None:
                raise ValueError(f"Rollback source missing: {op['new']}")
            if state == "new" and op["case_only"]:
                move_file(new, temp, op["size"])
                op["state"] = "temporary"
                journal_write(journal, document)
                state = "temp"
            if state == "temp":
                move_file(temp, old, op["size"])
            elif state == "new":
                move_file(new, old, op["size"])
        op["state"] = "rolled-back"
        journal_write(journal, document)
        print(f"RESTORED {op['new']} -> {op['old']}", flush=True)
    print("[OK] Rollback completed. Journal retained.")

def main():
    a=argparse.ArgumentParser()
    a.add_argument("command",choices=["preview","count","apply","rollback","resume","status"])
    a.add_argument("--csv",type=Path,required=True)
    a.add_argument("--root",type=Path,required=True)
    a.add_argument("--journal",type=Path,required=True)
    args=a.parse_args()
    root=args.root.resolve(strict=True)
    with args.csv.open(encoding="utf-8-sig",newline="") as f:
        entries=list(csv.DictReader(f))
    rows=plan(entries)
    if args.command=="count":
        print(len(rows))
        return
    if args.command=="preview":
        print(f"All {len(rows)} eligible alphabetical proposed PS2 renames:")
        for i,row in enumerate(rows,1):
            print(f"{i:02} {row['Current relative path']} -> {row['Proposed relative path']}")
        case_only = sum(r["Current relative path"].casefold() == r["Proposed relative path"].casefold() for r in rows)
        excluded_review = sum(r.get("Status") in {"COLLISION", "REVIEW"} for r in entries)
        print(f"Included: {case_only} case-only changes; excluded: {excluded_review} collision/review entries")
        print(f"Journal: {args.journal}")
        return
    args.journal.parent.mkdir(parents=True,exist_ok=True)
    if args.command=="apply":
        if not rows:
            print("[INFO] No eligible OPL rename proposals; no journal created and no files changed.")
            return
        do_apply(root,rows,args.journal)
    else:
        if not args.journal.is_file(): raise ValueError("No rollback journal")
        if args.command == "rollback":
            do_rollback(root, args.journal)
        elif args.command == "resume":
            do_resume(root, args.journal)
        else:
            do_status(root, args.journal)

if __name__=="__main__":
    main()
