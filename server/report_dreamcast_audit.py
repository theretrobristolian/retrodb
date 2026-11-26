#!/usr/bin/env python3
"""Read-only Dreamcast RA inventory. CHD/GDI are separate physical releases."""
import argparse
import csv
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from dreamcast_rename import discover, tracks, regular, canonical
from report_megacd_audit import HASH

FIELDS = ("source","format","destination","status","reason","size_bytes","title",
          "filename","ra_hash","ra_game_id","ra_title","ra_status","collection_status",
          "candidate_ra_id","local_alternative","flycast_online")

def title_key(title):
    # Preserve disc numbers, hardware and special-build qualifiers.
    title = re.sub(r"\((?:USA|Europe|Japan|World|Asia|Australia|Brazil|France|Germany|Spain|Italy|Korea)(?:,\s*(?:USA|Europe|Japan|World|Asia|Australia|Brazil|France|Germany|Spain|Italy|Korea))*\)", "", title, flags=re.I)
    title = re.sub(r"\((?:Rev[^)]*|v\d[^)]*|Version[^)]*|Alt)\)", "", title, flags=re.I)
    title = re.sub(r"^(.+?), (The|A|An)(?=\s*(?:\(|$))", r"\2 \1", title.strip(), flags=re.I)
    return re.sub(r"[^a-z0-9]", "", title.casefold())

def reconcile(rows, games):
    titles = {}
    for game in games:
        for alias in str(game["Title"]).split("|"):
            titles.setdefault(title_key(alias), {})[str(game["ID"])] = game
    for r in rows:
        r["collection_status"] = r["ra_status"]
        if r["ra_status"] != "UNMATCHED":
            continue
        key = title_key(r["title"])
        local = [a for a in rows if a["ra_status"] in ("SUPPORTED","NO_SET") and title_key(a["title"]) == key]
        ids = {str(a["ra_game_id"]) for a in local}
        candidates = titles.get(key, {})
        if len(ids) == 1 and (not candidates or set(candidates) == ids):
            alt = sorted(local, key=lambda a:(a["ra_status"]!="SUPPORTED",a["source"]))[0]
            r.update(collection_status="SOFT_PASS" if alt["ra_status"]=="SUPPORTED" else "SOFT_PASS_NO_SET",
                     candidate_ra_id=alt["ra_game_id"],local_alternative=alt["source"],
                     reason="Same normalized release title; exact registered local alternative; this hash remains unmatched")
        elif len(candidates)==1:
            ident, game = next(iter(candidates.items()))
            r.update(collection_status="ALTERNATIVE_REQUIRED" if int(game.get("NumAchievements") or 0)>0 else "TITLE_NO_SET",
                     candidate_ra_id=ident,reason="Title candidate only; hash not registered")
        else:
            r.update(collection_status="REVIEW",reason="No unique catalogue title candidate")

def audit(root, hasher, games):
    lookup={}
    for g in games:
        for h in g.get("Hashes",[]):
            if isinstance(h,str) and HASH.fullmatch(h):
                lookup.setdefault(h.lower(),{})[str(g["ID"])]=g
    rows=[]
    for p in discover(root):
        r=dict.fromkeys(FIELDS,"")
        r.update(source=p.relative_to(root).as_posix(), format=p.suffix.lower()[1:],filename=p.name,
                 title=p.stem,status="REVIEW",ra_status="NOT_CHECKED",flycast_online="NOT_TESTED")
        rows.append(r)
        try:
            if not regular(p) or p.stat().st_size==0:
                raise ValueError("Missing or empty image")
            members=[p]
            if r["format"]=="gdi":
                members.extend(p.parent/n for n in tracks(p))
            else:
                with p.open("rb") as f:
                    if f.read(8)!=b"MComprHD":
                        raise ValueError("Invalid CHD header")
            r.update(status="VALID",size_bytes=sum(x.stat().st_size for x in members))
            try:
                title=canonical(p.stem)
                r["destination"]=f'{r["format"]}/{title}/{title}.{r["format"]}'
                if r["source"]!=r["destination"]:
                    r["status"]="TIDY_CANDIDATE"
            except ValueError as e:
                r["reason"]=str(e)
            result=subprocess.run([str(hasher),"40",str(p)],capture_output=True,text=True,timeout=180)
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
        p.error("Dreamcast root unavailable")
    games=json.loads(a.ra_catalogue.read_text())
    if not isinstance(games,list) or not games or any(int(g.get("ConsoleID",40))!=40 for g in games):
        p.error("Invalid Dreamcast catalogue")
    rows=audit(a.root,a.hasher,games)
    with a.output.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"[OK] Dreamcast: {len(rows)} images; read-only")
    for k in ("format","status","ra_status","collection_status"):
        print(k,dict(Counter(r[k] for r in rows)))
    print("[INFO] Flycast online eligibility not tested")
if __name__=="__main__":
    main()
