#!/usr/bin/env python3
"""Enrich read-only PSP audit CSV using official RA registered hash descriptions.

Never interpret title equality as proof that a replacement ISO will hash correctly.
"""
import argparse
import csv
import os
import tempfile
from pathlib import Path

from retrodb.cli import load_environment_file
from retrodb.providers.retroachievements import RetroAchievementsClient, RetroAchievementsError

import json
import re

def release_region(description):
    for region,pattern in (("USA",r"\\b(?:USA|US|North America)\\b"),
                           ("Europe",r"\\b(?:Europe|EUR|PAL)\\b"),
                           ("Japan",r"\\b(?:Japan|JPN)\\b")):
        if re.search(pattern,str(description),re.I):
            return region
    return ""

def registered_alternatives(game_id, local_serial, detail_dir):
    path=detail_dir / f"{game_id}.json"
    if not path.is_file():
        return "", "Registered RA release descriptions unavailable"
    try:
        payload=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        return "", "Registered RA release descriptions unavailable"
    regions=set()
    for item in payload if isinstance(payload,list) else []:
        if isinstance(item,dict):
            description=item.get("Name") or item.get("Description") or item.get("Title") or ""
            region=release_region(description)
            if region:
                regions.add(region)
    prefix=local_serial[:4].upper()
    local=("USA" if prefix in ("ULUS","UCUS","NPUH","NPUG")
           else "Europe" if prefix in ("ULES","UCES","NPEH","NPEG")
           else "Japan" if prefix in ("ULJS","ULJM","UCJS","UCJM","NPJH","NPJQ") else "")
    alternatives=sorted(regions - {local})
    if alternatives:
        return "/".join(alternatives),"Registered RA hash describes this alternative region; verify exact revision and hash"
    return "", "RA achievement set exists; no confirmed alternative region in registered hash descriptions"


def enrich(csv_path, cache_dir, env_file):
    load_environment_file(env_file)
    client=RetroAchievementsClient(os.environ.get("RETRODB_RA_USERNAME",""),
                                    os.environ.get("RETRODB_RA_API_KEY",""),
                                    cache_dir)
    with csv_path.open(newline="",encoding="utf-8") as stream:
        reader=csv.DictReader(stream)
        fields=list(reader.fieldnames or [])
        records=list(reader)
    for key in ("suggested_ra_game_id","suggested_release","suggested_region","suggestion_evidence"):
        if key not in fields:
            raise ValueError("PSP audit lacks suggestion field "+key)
    candidates=sorted({r["suggested_ra_game_id"] for r in records
                       if r.get("ra_status")=="UNMATCHED" and r.get("suggested_ra_game_id","").isdigit()})
    failures=[]
    for i,game_id in enumerate(candidates,1):
        try:
            client.get_game_hashes(int(game_id))
        except (RetroAchievementsError, OSError, ValueError) as exc:
            failures.append(game_id)
            print(f"[WARNING] PSP RA release descriptions unavailable for game {game_id}: {type(exc).__name__}")
        if i%10==0:
            print(f"[INFO] PSP RA release descriptions: {i}/{len(candidates)} checked.")
    detail_dir=cache_dir/"games"
    for row in records:
        game_id=row.get("suggested_ra_game_id","")
        if row.get("ra_status")!="UNMATCHED" or game_id not in candidates or game_id in failures:
            continue
        region,evidence=registered_alternatives(game_id,row.get("disc_id",""),detail_dir)
        title=row.get("suggested_release","") or row.get("title","")
        row.update(suggested_release=title + (", "+region if region else ""),
                   suggested_region=region,suggestion_evidence=evidence)
    fd,name=tempfile.mkstemp(prefix=".psp-release-",suffix=".csv",dir=csv_path.parent)
    try:
        with os.fdopen(fd,"w",newline="",encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)
        os.chmod(name,0o600)
        os.replace(name,csv_path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    regions=sum(bool(r.get("suggested_region")) for r in records)
    print(f"[OK] PSP alternative releases: {len(candidates)} RA titles inspected, {regions} region-specific suggestions; {len(failures)} API failures.")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--audit",type=Path,required=True)
    parser.add_argument("--cache-dir",type=Path,default=Path("/var/cache/retrodb/providers/retroachievements"))
    parser.add_argument("--env-file",type=Path,default=Path("/etc/retrodb/retrodb.env"))
    a=parser.parse_args()
    enrich(a.audit,a.cache_dir,a.env_file)
