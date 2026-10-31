#!/usr/bin/env python3
"""Explicit filename-only PS1 renames for approved serial-less BIN/CUE pairs.

No invented PS1 disc IDs, no overwrite, no writes during preview.
"""
import argparse
import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from ps1_ra_conflict import verify_pair, rewritten

# Exact identities established by the 2026-10-31 verified RA compatibility audit.
RELEASES = {
    "15631": ("Calamity 1 - The Natural World (USA)", "Calamity 1 The Natural World [RA-15631]", "a90f05716df8f35ea5dde12410e4a70b"),
    "15632": ("Calamity 2 - People and Traditions (USA)", "Calamity 2 People and Traditions [RA-15632]", "dd57cc1402eda12258c82295fc002dd2"),
    "15633": ("Calamity 3 - Around the World (USA)", "Calamity 3 Around the World [RA-15633]", "63b2b009595635e4f9dbd9d4c6be5fca"),
    "16325": ("Caesars Palace II (USA)", "Caesars Palace II", ""),
}


def proposed(root, audit):
    found = []
    # Explicitly approved filename-only normalisation, not a hash-based claim.
    for game_id, (source, target, expected_hash) in RELEASES.items():
        directory = root / "iso"
        a, b = directory / (source + ".cue"), directory / (source + ".bin")
        c, d = directory / (target + ".cue"), directory / (target + ".bin")
        if not a.is_file() or not b.is_file() or any(p.is_symlink() for p in (a,b,c,d)):
            continue
        if any(p.exists() for p in (c,d)):
            continue
        if any(p.name.startswith("OLD_") for p in (a,b)):
            continue
        if len({str(p).casefold() for p in (a,b,c,d)}) != 4:
            continue
        try:
            verify_pair(a,b)
        except (OSError, RuntimeError, ValueError):
            continue
        found.append((game_id, expected_hash, a,b,c,d))
    return found


def write_journal(path, records):
    tmp=path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"created_utc":datetime.now(timezone.utc).isoformat(),
                                "operations":records}, indent=2), encoding="utf-8")
    os.replace(tmp,path)


def apply(ops, journal, hasher):
    if journal.exists():
        raise RuntimeError("Journal already exists")
    if not ops:
        return
    journal.parent.mkdir(parents=True, exist_ok=True)
    records=[]
    for game_id,expected,a,b,c,d in ops:
        raw,enc,lines,m=verify_pair(a,b)
        print(f"[CHECK] {game_id}: checking CUE/BIN for {b.name}",flush=True)
        records.append({"game_id":game_id,"expected_hash":expected,
                        "old_cue":str(a),"old_bin":str(b),"new_cue":str(c),"new_bin":str(d),
                        "original_cue_hex":raw.hex(),"state":"pending"})
    write_journal(journal,records)
    for record in records:
        a,b,c,d=[Path(record[k]) for k in ("old_cue","old_bin","new_cue","new_bin")]
        try:
            if c.exists() or d.exists():
                raise RuntimeError("Destination created since preview")
            raw,enc,lines,m=verify_pair(a,b)
            if raw.hex()!=record["original_cue_hex"]:
                raise RuntimeError("Source CUE changed")
            updated=rewritten(lines,m,d,enc)
            b.rename(d)
            record["state"]="bin_moved"
            write_journal(journal,records)
            a.rename(c)
            record["state"]="cue_moved"
            write_journal(journal,records)
            c.write_bytes(updated)
            verify_pair(c,d)
            record["state"]="applied"
            write_journal(journal,records)
            print(f"[OK] Renamed: {c.name}",flush=True)
        except Exception as exc:
            record["error"]=str(exc)
            write_journal(journal,records)
            raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode",choices=("preview","count","apply"))
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--audit",type=Path,required=True)
    p.add_argument("--journal",type=Path)
    p.add_argument("--hasher",type=Path,default=Path("/opt/retrodb-tools/RAHasher"))
    args=p.parse_args()
    operations=proposed(args.root,args.audit)
    if args.mode=="count":
        print(len(operations))
    elif args.mode=="preview":
        for game_id,_,a,_,c,_ in operations:
            print(f"[FILENAME ONLY] {a.name} -> {c.name} (no disc serial or RA hash required)")
        if not operations:
            print("[INFO] No approved serial-less renames pending")
    else:
        if not args.journal:
            p.error("--journal required for apply")
        apply(operations,args.journal,args.hasher)


if __name__=="__main__":
    main()
