#!/usr/bin/env python3
"""Read-only GameCube ISO inventory and RA hash audit."""
import argparse
import csv
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from dreamcast_rename import regular
from gamecube_rename import disc_header, proposed_name
from report_dreamcast_audit import reconcile
from report_megacd_audit import HASH

FIELDS = ("source","format","destination","status","reason","size_bytes","title",
          "filename","ra_hash","ra_game_id","ra_title","ra_status","collection_status",
          "candidate_ra_id","local_alternative","disc_id","region","disc_number","revision","internal_title")

def audit(root, hasher, games):
    lookup={}
    for g in games:
        for h in g.get("Hashes",[]):
            if isinstance(h,str) and HASH.fullmatch(h):
                lookup.setdefault(h.lower(),{})[str(g["ID"])]=g
    rows=[]
    for p in sorted(root.iterdir()):
        if not regular(p) or p.suffix.lower() != ".iso" or p.name.startswith((".", "OLD_", "NEW_")):
            continue
        r=dict.fromkeys(FIELDS,"")
        r.update(source=p.relative_to(root).as_posix(), format=p.suffix.lower()[1:],filename=p.name,
                 title=p.stem,status="REVIEW",ra_status="NOT_CHECKED")
        rows.append(r)
        try:
            if not regular(p) or p.stat().st_size==0:
                raise ValueError("Missing or empty image")
            info=disc_header(p)
            r.update(status="VALID",size_bytes=p.stat().st_size,disc_id=info["disc_id"],
                     region=info["region"],disc_number=info["disc"],revision=info["revision"],
                     internal_title=info["internal_title"])
            try:
                r["destination"]=proposed_name(p,info)
                r["title"]=Path(r["destination"]).stem
                if r["source"]!=r["destination"]:
                    r["status"]="TIDY_CANDIDATE"
            except ValueError as e:
                r["reason"]=str(e)
            result=subprocess.run([str(hasher),"16",str(p)],capture_output=True,text=True,timeout=180)
            hashes=HASH.findall(result.stdout)
            if result.returncode or len(set(h.lower() for h in hashes))!=1:
                r.update(ra_status="HASH_ERROR",reason="RAHasher failed or returned no unique hash")
                continue
            h=hashes[0].lower()
            r["ra_hash"]=h
            matches=lookup.get(h,{})
            if len(matches)==1:
                game=next(iter(matches.values()))
                r.update(ra_game_id=game["ID"],ra_title=game["Title"],ra_status="SUPPORTED" if int(game.get("NumAchievements") or 0)>0 else "NO_SET")
            else:
                r["ra_status"]="AMBIGUOUS" if matches else "UNMATCHED"
        except (OSError,ValueError,UnicodeError,subprocess.TimeoutExpired) as e:
            r["reason"]=str(e)
            if r["status"] in ("VALID","TIDY_CANDIDATE"):
                r["ra_status"]="HASH_ERROR"
    reconcile(rows,games)
    return rows

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--hasher",type=Path,required=True)
    p.add_argument("--ra-catalogue",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if not a.root.is_dir() or a.root.is_symlink():
        p.error("GameCube root unavailable")
    games=json.loads(a.ra_catalogue.read_text())
    if not isinstance(games,list) or not games or any(int(g.get("ConsoleID",16))!=16 for g in games):
        p.error("Invalid GameCube catalogue")
    rows=audit(a.root,a.hasher,games)
    with a.output.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"[OK] GameCube: {len(rows)} images; read-only")
    for k in ("format","status","ra_status","collection_status"):
        print(k,dict(Counter(r[k] for r in rows)))

if __name__=="__main__":
    main()
