"""Enrich GameCube audit with official registered RA file names and hashes."""
import argparse
import csv
import os
import re
import tempfile
from pathlib import Path
from retrodb.cli import load_environment_file
from retrodb.providers.retroachievements import RetroAchievementsClient, RetroAchievementsError

def alternatives(entries, region):
    choices={}
    for entry in entries:
        name=str(entry.get("Name") or entry.get("Description") or entry.get("Title") or "").strip()
        digest=str(entry.get("MD5") or entry.get("Hash") or "").strip().lower()
        if not name or not re.fullmatch(r"[0-9a-f]{32}",digest):
            continue
        if re.search(r"\b(subset|hack|patched|patch|prototype|demo|beta|translation|maeson|dreamsyntax|widescreen|unknown|[56]0\s*hz|v\d+\.\d+)\b",name,re.I):
            continue
        choices[(name,digest)] = (name,digest)
    return sorted(choices.values(), key=lambda x:(
        not bool(region and re.search(r"\b"+re.escape(region)+r"\b",x[0],re.I)),
        not bool(re.search(r"\((?:USA|Europe|Japan)\)",x[0],re.I)),x[0].casefold(),x[1]))

def enrich(path, cache_dir, env_file):
    load_environment_file(env_file)
    client=RetroAchievementsClient(os.environ.get("RETRODB_RA_USERNAME",""),
                                  os.environ.get("RETRODB_RA_API_KEY",""),cache_dir)
    with path.open(newline="",encoding="utf-8") as f:
        reader=csv.DictReader(f)
        fields=list(reader.fieldnames or [])
        rows=list(reader)
    extra=("suggested_release","suggested_ra_hash","registered_alternatives","suggestion_evidence")
    fields.extend(k for k in extra if k not in fields)
    ids=sorted({r["candidate_ra_id"] for r in rows
                if r["ra_status"]=="UNMATCHED" and r["candidate_ra_id"].isdigit()
                and r["collection_status"] not in ("SOFT_PASS","SOFT_PASS_NO_SET")})
    cache={}
    for ident in ids:
        try:
            cache[ident]=client.get_game_hashes(int(ident))
        except (RetroAchievementsError,OSError,ValueError) as e:
            print(f"[WARNING] GameCube RA file descriptions unavailable for {ident}: {type(e).__name__}")
    for r in rows:
        r.update(dict.fromkeys(extra,""))
        if r["ra_status"]!="UNMATCHED" or r["candidate_ra_id"] not in cache or r["collection_status"] in ("SOFT_PASS","SOFT_PASS_NO_SET"):
            continue
        options=alternatives(cache[r["candidate_ra_id"]],r.get("region",""))
        if not options:
            r["suggestion_evidence"]="No ordinary registered release description available; inspect RA manually"
            continue
        r["registered_alternatives"]=" | ".join(f"{n} [{h}]" for n,h in options)
        # Don't select a different disc automatically.
        disc=r.get("disc_number","")
        if disc and (disc!="1" or re.search(r"\(Disc\s+\d+\)",r["filename"],re.I)):
            options=[(n,h) for n,h in options if re.search(r"\(Disc\s+"+re.escape(disc)+r"\)",n,re.I)]
        if options:
            r["suggested_release"],r["suggested_ra_hash"]=options[0]
            r["suggestion_evidence"]="Official RA registered hash description; verify replacement by hashing; not a Redump full-image checksum"
        else:
            r["suggestion_evidence"]="No explicitly matching disc number in registered descriptions; inspect RA manually"
    fd,tmp=tempfile.mkstemp(prefix=".gamecube-release-",suffix=".csv",dir=path.parent)
    try:
        with os.fdopen(fd,"w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fields)
            writer.writeheader()
            writer.writerows(rows)
        os.chmod(tmp,0o600)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print(f"[OK] GameCube release descriptions: {len(cache)}/{len(ids)} RA titles checked; {sum(bool(r['suggested_release']) for r in rows)} recommendations.")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--audit",type=Path,required=True)
    p.add_argument("--cache-dir",type=Path,default=Path("/var/cache/retrodb/providers/retroachievements"))
    p.add_argument("--env-file",type=Path,default=Path("/etc/retrodb/retrodb.env"))
    a=p.parse_args()
    enrich(a.audit,a.cache_dir,a.env_file)
