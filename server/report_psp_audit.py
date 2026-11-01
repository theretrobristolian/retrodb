#!/usr/bin/env python3
"""Read-only PSP ISO inventory. No rename and no unsupported RA compatibility claims."""
import argparse
import csv
import json
import re
from pathlib import Path

FIELDS = ["status", "disc_id", "title", "filename", "relative_path", "size_bytes", "identity_source", "ra_status", "reason"]
ID = re.compile(r"(?<![A-Z0-9])((?:UL|UC|NP)[A-Z]{2})[-_. ]?(\d{5})(?![A-Z0-9])", re.I)

def normalise(value):
    m = ID.search(str(value))
    return (m[1]+m[2]).upper() if m else ""

def inventory(root, titles):
    if not root.is_dir():
        raise FileNotFoundError(f"PSP collection unavailable: {root}")
    rows=[]
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file() or p.suffix.casefold() != ".iso" or p.name.casefold().startswith("old_"):
            continue
        ident=normalise(p.stem)
        title=titles.get(ident,"") if ident else ""
        status="IDENTIFIED_FROM_FILENAME" if title else "REVIEW_IDENTITY"
        rows.append(dict(status=status,disc_id=ident or "UNKNOWN",title=title or p.stem,
            filename=p.name, relative_path=p.relative_to(root).as_posix(),
            size_bytes=p.stat().st_size, identity_source="filename/GameDB" if title else "filename only",
            ra_status="NOT_CHECKED",reason="Disc ID from filename, not independently verified from ISO"
            if ident else "No recognisable PSP serial in filename"))
    return rows

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--catalogue",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    catalogue=json.loads(args.catalogue.read_text(encoding="utf-8"))
    titles={normalise(k):v for k,v in catalogue.items() if normalise(k) and isinstance(v,str)}
    rows=inventory(args.root,titles)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("w",newline="",encoding="utf-8") as fh:
        writer=csv.DictWriter(fh,fieldnames=FIELDS)
        writer.writeheader();writer.writerows(rows)
    print(f"[OK] PSP read-only inventory: {len(rows)} ISOs -> {args.output}")
    print("[INFO] RA compatibility NOT CHECKED; filename serials are provisional.")

if __name__=="__main__":
    main()
