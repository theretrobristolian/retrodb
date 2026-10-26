#!/usr/bin/env python3
"""PS1 paired BIN/CUE rename executor. Default preview; apply needs a writable mount."""
import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from report_ps1_audit import disc_serial

FILE_LINE = re.compile(r'^(\s*FILE\s+)(?:"([^"]+)"|(\S+))(\s+[^\r\n]+)$', re.I)

def parse(args):
    with open(args.csv, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    ops = []
    used = set()
    for row in rows:
        # Restrict automatic updates to independently verified clean one-BIN records.
        if row["status"] not in ("RENAME_CANDIDATE", "VALID"):
            continue
        if row.get("issues"):
            continue
        if not row.get("internal_serial") or row["internal_serial"] != row.get("selected_serial"):
            continue
        paths = [row.get(k, "") for k in ("relative_cue", "relative_bin",
                                         "proposed_cue", "proposed_bin")]
        if any(not p or Path(p).is_absolute() or ".." in Path(p).parts for p in paths):
            continue
        oldcue, oldbin, newcue, newbin = (args.root / p for p in paths)
        if oldcue.parent != oldbin.parent or newcue.parent != newbin.parent:
            continue
        if oldcue == newcue and oldbin == newbin:
            continue
        if len({str(p).casefold() for p in (newcue, newbin)}) != 2:
            continue
        if any(p.is_symlink() for p in (oldcue, oldbin)):
            continue
        if not all(p.is_file() for p in (oldcue, oldbin)):
            continue
        if disc_serial(oldbin) != row["internal_serial"]:
            continue
        if (newcue != oldcue and newcue.exists()) or (newbin != oldbin and newbin.exists()):
            continue
        if any(str(p).casefold() in used for p in (newcue, newbin)):
            continue
        raw = oldcue.read_bytes()
        try:
            content = raw.decode("utf-8-sig")
            encoding = "utf-8"
        except UnicodeDecodeError:
            content = raw.decode("cp1252")
            encoding = "cp1252"
        lines = content.splitlines(keepends=True)
        indices = [i for i, line in enumerate(lines) if line.lstrip().upper().startswith("FILE ")]
        if len(indices) != 1:
            continue
        match = FILE_LINE.match(lines[indices[0]].rstrip("\r\n"))
        if not match or (match.group(2) or match.group(3)) != oldbin.name:
            continue
        used.update((str(newcue).casefold(), str(newbin).casefold()))
        ops.append(dict(old_cue=str(oldcue), old_bin=str(oldbin),
                        new_cue=str(newcue), new_bin=str(newbin),
                        original_cue_hex=raw.hex(), encoding=encoding,
                        serial=row["internal_serial"],
                        state="pending"))
    return ops

def sync(journal, operations):
    temp = journal.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"created_utc": datetime.now(timezone.utc).isoformat(),
                                "operations": operations}, indent=2), encoding="utf-8")
    os.replace(temp, journal)

def apply(ops, journal):
    journal.parent.mkdir(parents=True, exist_ok=True)
    if journal.exists():
        raise RuntimeError("Journal already exists: " + str(journal))
    sync(journal, ops)
    for op in ops:
        oldcue, oldbin, newcue, newbin = [Path(op[k]) for k in ("old_cue", "old_bin", "new_cue", "new_bin")]
        try:
            # Keep original CUE in journal for recovery; never rewrite track layout.
            raw = bytes.fromhex(op["original_cue_hex"])
            decoded = raw.decode(op["encoding"])
            lines = decoded.splitlines(keepends=True)
            idx = next(i for i, line in enumerate(lines)
                       if line.lstrip().upper().startswith("FILE "))
            m = FILE_LINE.match(lines[idx].rstrip("\r\n"))
            if not m:
                raise RuntimeError("CUE changed since preview")
            updated = m.group(1) + '"' + newbin.name + '"' + m.group(4)
            ending = "\r\n" if lines[idx].endswith("\r\n") else ("\n" if lines[idx].endswith("\n") else "")
            lines[idx] = updated + ending
            if oldcue.read_bytes() != raw:
                raise RuntimeError("CUE changed since plan")
            if disc_serial(oldbin) != op["serial"]:
                raise RuntimeError("Internal disc ID changed since audit")
            oldbin.rename(newbin)
            op["state"] = "bin_moved"
            sync(journal, ops)
            oldcue.rename(newcue)
            op["state"] = "cue_moved"
            sync(journal, ops)
            newcue.write_bytes("".join(lines).encode(op["encoding"]))
            if newbin.name not in newcue.read_text(encoding=op["encoding"]):
                raise RuntimeError("Post-write CUE validation failed")
            op["state"] = "applied"
            sync(journal, ops)
            print("[OK]", newcue.name)
        except Exception as exc:
            op["error"] = str(exc)
            sync(journal, ops)
            raise

def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("preview", "apply"))
    p.add_argument("--csv", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--journal", type=Path)
    args = p.parse_args()
    ops = parse(args)
    print(f"Eligible paired BIN/CUE renames: {len(ops)}")
    for op in ops:
        print(Path(op["old_cue"]).name, "=>", Path(op["new_cue"]).name)
    if args.mode == "apply":
        if not args.journal:
            p.error("--journal is required for apply")
        apply(ops, args.journal)
    else:
        print("PREVIEW ONLY: no changes made.")

if __name__ == "__main__":
    main()
