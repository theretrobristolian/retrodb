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
import unicodedata
from report_dreamcast_audit import title_key
from report_megacd_audit import HASH

FIELDS = ("source","format","destination","status","reason","size_bytes","title",
          "filename","ra_hash","ra_game_id","ra_title","ra_status","collection_status",
          "candidate_ra_id","local_alternative","disc_id","region","disc_number","revision","internal_title")

def gc_key(value):
    value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    value = re.sub(r"\s*\(Player.s Choice\)", "", value, flags=re.I)
    value = re.sub(r"\s*\(Promo\)", "", value, flags=re.I)
    key = title_key(value)
    return {"chibiroboplugintoadventure":"chibirobo",
            "pokemonboxrubyandsapphire":"pokemonboxrubysapphire"}.get(key,key)

def reconcile(rows,games):
    titles={}
    for g in games:
        for alias in str(g["Title"]).split("|"):
            titles.setdefault(gc_key(alias),{})[str(g["ID"])]=g
    for r in rows:
        r.update(collection_status=r["ra_status"],candidate_ra_id="",local_alternative="")
        if r["ra_status"]!="UNMATCHED":
            continue
        key=gc_key(r["title"])
        candidates=titles.get(key,{})
        # Same header ID and disc number is stronger than title alone; never
        # substitute disc 1 for disc 2 or claim an unmatched hash is supported.
        local=[a for a in rows if a["ra_status"] in ("SUPPORTED","NO_SET")
               and r["disc_id"] and a["disc_id"]==r["disc_id"]
               and a["disc_number"]==r["disc_number"]
               and gc_key(a["title"])==key]
        ids={str(a["ra_game_id"]) for a in local}
        if len(ids)==1 and (not candidates or set(candidates)==ids):
            alt=sorted(local,key=lambda a:(a["ra_status"]!="SUPPORTED",a["source"]))[0]
            r.update(collection_status="SOFT_PASS" if alt["ra_status"]=="SUPPORTED" else "SOFT_PASS_NO_SET",
                     candidate_ra_id=alt["ra_game_id"],local_alternative=alt["source"],
                     reason="Same disc ID, disc number and normalized title; registered local alternative; this hash remains unmatched")
        elif len(candidates)==1:
            ident,g=next(iter(candidates.items()))
            r.update(collection_status="ALTERNATIVE_REQUIRED" if int(g.get("NumAchievements") or 0)>0 else "TITLE_NO_SET",
                     candidate_ra_id=ident,reason="Title candidate only; hash not registered")
        else:
            # A sibling disc may identify the game, but is never a soft pass.
            siblings=[a for a in rows if a["ra_game_id"] and r["disc_id"] and a["disc_id"]==r["disc_id"]]
            sibling_ids={str(a["ra_game_id"]) for a in siblings}
            if len(sibling_ids)==1 and not candidates:
                r.update(candidate_ra_id=next(iter(sibling_ids)),collection_status="REVIEW",
                         reason="Sibling disc identifies RA game candidate; this disc hash is not registered")
            else:
                r.update(collection_status="REVIEW",reason="No unique catalogue title candidate")

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
