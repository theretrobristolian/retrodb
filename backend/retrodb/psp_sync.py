"""Persist verified PSP RA hash results from the read-only audit into RetroDB metadata."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from retrodb.cli import load_environment_file
from retrodb.database import get_engine
from retrodb.models import LibraryItem, Platform

def sync(path: Path) -> tuple[int,int]:
    with path.open(newline="",encoding="utf-8-sig") as handle:
        records=list(csv.DictReader(handle))
    if not records or not {"relative_path","ra_status","ra_hash","ra_game_id"}.issubset(records[0]):
        raise ValueError("PSP audit is empty or missing required columns")
    accepted={"SUPPORTED","NO_SET","UNMATCHED","HASH_ERROR","NOT_CHECKED"}
    if any(record["ra_status"] not in accepted for record in records):
        raise ValueError("Unrecognised PSP RA audit status")
    updated=missing=0
    with Session(get_engine()) as session:
        platform=session.scalar(select(Platform).where(Platform.slug=="playstation-portable"))
        if platform is None:
            raise RuntimeError("PSP platform missing; run library-scan first")
        for row in records:
            relative="roms/sony/playstationportable/iso/"+row["relative_path"]
            item=session.scalar(select(LibraryItem).where(
                LibraryItem.platform_id==platform.id,
                LibraryItem.relative_path==relative,
                LibraryItem.is_missing.is_(False)))
            if item is None:
                missing+=1
                continue
            status=row["ra_status"]
            item.ra_hash=row["ra_hash"] or None
            item.ra_game_id=int(row["ra_game_id"]) if row["ra_game_id"].isdigit() else None
            item.ra_game_title=row.get("ra_game_title") or None
            item.ra_match_status=("matched" if status in ("SUPPORTED","NO_SET")
                                  else "unmatched" if status=="UNMATCHED"
                                  else "error" if status=="HASH_ERROR" else None)
            item.ra_hash_error=row.get("reason","")[:500] if status=="HASH_ERROR" else None
            item.ra_hashed_at=datetime.now(timezone.utc) if status!="NOT_CHECKED" else None
            updated+=1
        session.commit()
    return updated,missing

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--audit",required=True,type=Path)
    parser.add_argument("--env-file",type=Path,default=Path("/etc/retrodb/retrodb.env"))
    args=parser.parse_args()
    load_environment_file(args.env_file)
    updated,missing=sync(args.audit)
    print(f"[OK] PSP RA portal metadata updated: {updated}; missing library entries: {missing}")
    return 0 if not missing else 1

if __name__=="__main__":
    raise SystemExit(main())
