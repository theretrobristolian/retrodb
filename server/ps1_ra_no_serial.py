#!/usr/bin/env python3
"""Conservative RA-hash-verified PS1 names for three serial-less Calamity discs.

No invented PS1 disc IDs, no overwrite, no writes during preview.
"""
import argparse
import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from ps1_ra_conflict import ra_hash, verify_pair, rewritten

# Exact identities established by the 2026-10-31 verified RA compatibility audit.
RELEASES = {
    "15631": ("Calamity 1 - The Natural World (USA)", "Calamity 1 The Natural World [RA-15631]", "a90f05716df8f35ea5dde12410e4a70b"),
    "15632": ("Calamity 2 - People and Traditions (USA)", "Calamity 2 People and Traditions [RA-15632]", "dd57cc1402eda12258c82295fc002dd2"),
    "15633": ("Calamity 3 - Around the World (USA)", "Calamity 3 Around the World [RA-15633]", "63b2b009595635e4f9dbd9d4c6be5fca"),
}


def proposed(root, audit):
    with audit.open(newline="", encoding="utf-8-sig") as fh:
        data = list(csv.DictReader(fh))
    found = []
    for game_id, (source, target, expected_hash) in RELEASES.items():
        candidates = [row for row in data if row.get("platform") == "Sony PlayStation"
                      and row.get("status") == "matched"
                      and str(row.get("ra_game_id") or row.get("no_set_ra_game_id")) == game_id
                      and row.get("local_ra_hash", "").lower() == expected_hash
                      and Path(row.get("path", "")).stem == source]
        if len(candidates) != 1:
            continue
        relative = Path(candidates[0]["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() not in (".cue", ".bin"):
            continue
        directory = root / relative.parent
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
        print(f"[VERIFY] RA {game_id}: hashing {b.name}",flush=True)
        if ra_hash(hasher,b) != expected:
            raise RuntimeError("RA hash mismatch: " + b.name)
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
            if ra_hash(hasher,b)!=record["expected_hash"]:
                raise RuntimeError("Source hash changed")
            updated=rewritten(lines,m,d,enc)
            b.rename(d)
            record["state"]="bin_moved"
            write_journal(journal,records)
            a.rename(c)
            record["state"]="cue_moved"
            write_journal(journal,records)
            c.write_bytes(updated)
            if ra_hash(hasher,d)!=record["expected_hash"]:
                raise RuntimeError("Post-rename RA hash mismatch")
            verify_pair(c,d)
            record["state"]="applied"
            write_journal(journal,records)
            print(f"[OK] RA {record['game_id']}: {c.name}",flush=True)
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
            print(f"[RA VERIFIED] {a.name} -> {c.name} (game {game_id}; no disc serial invented)")
        if not operations:
            print("[INFO] No Calamity RA-verified renames pending")
    else:
        if not args.journal:
            p.error("--journal required for apply")
        apply(operations,args.journal,args.hasher)


if __name__=="__main__":
    main()
