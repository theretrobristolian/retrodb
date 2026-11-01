#!/usr/bin/env python3
"""Read-only PSP ISO inspection, internal DISC_ID and RetroAchievements verification."""
import argparse
import csv
import json
import re
import struct
import subprocess
from pathlib import Path

FIELDS = ["status","disc_id","title","filename","relative_path","size_bytes",
          "identity_source","ra_status","reason","filename_disc_id","internal_disc_id",
          "internal_title","ra_hash","ra_game_id","ra_game_title"]
ID = re.compile(r"(?<![A-Z0-9])([A-Z]{4})[-_. ]?(\d{5})(?![A-Z0-9])", re.I)
HASH = re.compile(r"\b([0-9a-fA-F]{32})\b")

def normalise(value):
    match=ID.search(str(value))
    return (match[1]+match[2]).upper() if match else ""

def iso_entry(record):
    if len(record)<34:
        raise ValueError("Invalid ISO9660 directory record")
    length=record[0]
    if length<34 or length>len(record):
        raise ValueError("Invalid ISO9660 directory record length")
    return (int.from_bytes(record[2:6],"little"),
            int.from_bytes(record[10:14],"little"), record[25],
            record[33:33+record[32]].decode("ascii","replace").split(";")[0].upper())

def iso_file(iso, components, limit=1024*1024):
    """Read a named ISO9660 file only; never extract or modify the image."""
    with iso.open("rb") as fh:
        fh.seek(16*2048)
        pvd=fh.read(2048)
        if len(pvd)!=2048 or pvd[0]!=1 or pvd[1:6]!=b"CD001":
            raise ValueError("No ISO9660 primary volume descriptor")
        directory=iso_entry(pvd[156:190])
        for position, name in enumerate(components):
            sector,length,flags,_=directory
            if not flags & 2:
                raise ValueError("Expected ISO directory")
            if length>8*1024*1024:
                raise ValueError("Unusually large ISO directory")
            fh.seek(sector*2048)
            data=fh.read(length)
            if len(data)!=length:
                raise ValueError("Truncated ISO directory")
            child=None
            offset=0
            while offset<len(data):
                n=data[offset]
                if not n:
                    offset=((offset//2048)+1)*2048
                    continue
                if n<34 or offset+n>len(data):
                    raise ValueError("Damaged ISO directory record")
                entry=iso_entry(data[offset:offset+n])
                if entry[3]==name.upper():
                    child=entry
                    break
                offset+=n
            if child is None:
                raise ValueError("Missing "+"/".join(components[:position+1]))
            directory=child
        sector,length,flags,_=directory
        if flags & 2 or length>limit:
            raise ValueError("Invalid or oversized PARAM.SFO")
        fh.seek(sector*2048)
        data=fh.read(length)
        if len(data)!=length:
            raise ValueError("Truncated PARAM.SFO")
        return data

def parse_sfo(data):
    if len(data)<20 or data[:4]!=b"\x00PSF":
        raise ValueError("Invalid PARAM.SFO header")
    keys,values,count=struct.unpack_from("<III",data,8)
    if count>256 or 20+count*16>len(data):
        raise ValueError("Invalid PARAM.SFO index")
    result={}
    for i in range(count):
        key_offset,fmt,size,max_size,value_offset=struct.unpack_from("<HHIII",data,20+i*16)
        key_start=keys+key_offset
        val_start=values+value_offset
        if key_start>=len(data) or val_start+size>len(data):
            raise ValueError("Invalid PARAM.SFO offsets")
        end=data.find(b"\0",key_start)
        if end<0:
            raise ValueError("Unterminated PARAM.SFO key")
        key=data[key_start:end].decode("utf-8","replace")
        value=data[val_start:val_start+size]
        if fmt in (0x0004,0x0204):
            result[key]=value.rstrip(b"\0").decode("utf-8","replace").strip()
    return result

def load_ra(path):
    if not path:
        return None
    games=json.loads(path.read_text(encoding="utf-8"))
    lookup={}
    for game in games:
        if not isinstance(game,dict):
            continue
        for value in game.get("Hashes",[]):
            if isinstance(value,str) and HASH.fullmatch(value):
                lookup[value.casefold()]=(str(game.get("ID","")),str(game.get("Title","")),int(game.get("NumAchievements") or 0))
    return lookup

def verify_hash(hasher,iso,lookup):
    try:
        result=subprocess.run([str(hasher),"41",str(iso)],capture_output=True,text=True,timeout=180,check=False)
    except (OSError,subprocess.TimeoutExpired) as error:
        return "HASH_ERROR","","","",type(error).__name__
    text=result.stdout+"\n"+result.stderr
    found=HASH.findall(text)
    if result.returncode!=0 or not found:
        return "HASH_ERROR","","","",text.strip().splitlines()[-1][:160] if text.strip() else "RAHasher failed"
    value=found[-1].lower()
    if value not in lookup:
        return "UNMATCHED",value,"","","Hash not in PSP RetroAchievements catalogue"
    gameid,title,count=lookup[value]
    return ("SUPPORTED" if count>0 else "NO_SET"),value,gameid,title,""

def inventory(root,titles,hasher=None,ra_lookup=None):
    if not root.is_dir():
        raise FileNotFoundError(f"PSP collection unavailable: {root}")
    rows=[]
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.suffix.casefold()!=".iso" or path.name.casefold().startswith("old_"):
            continue
        named=normalise(path.stem)
        internal=""
        internal_title=""
        issues=[]
        try:
            info=parse_sfo(iso_file(path,["PSP_GAME","PARAM.SFO"]))
            internal=normalise(info.get("DISC_ID",""))
            internal_title=info.get("TITLE","")
            if not internal:
                issues.append("Missing or unrecognised internal DISC_ID")
        except (ValueError,OSError) as exc:
            issues.append("ISO metadata error: "+str(exc)[:150])
        if named and internal and named!=internal:
            issues.append(f"Filename serial {named} differs from internal {internal}")
        chosen=internal or named
        title=titles.get(chosen,"") or internal_title or path.stem
        status="REVIEW_IDENTITY" if issues or not chosen or chosen not in titles else "VERIFIED_INTERNAL"
        ra_status,ra_hash,ra_id,ra_title="NOT_CHECKED","","",""
        if hasher is not None and ra_lookup is not None:
            ra_status,ra_hash,ra_id,ra_title,error=verify_hash(hasher,path,ra_lookup)
            if error:
                issues.append(error)
        rows.append(dict(status=status,disc_id=chosen or "UNKNOWN",title=title,
            filename=path.name,relative_path=path.relative_to(root).as_posix(),
            size_bytes=path.stat().st_size,identity_source="PARAM.SFO/GameDB" if internal else "filename (unverified)",
            ra_status=ra_status,reason="; ".join(issues),filename_disc_id=named,
            internal_disc_id=internal,internal_title=internal_title,
            ra_hash=ra_hash,ra_game_id=ra_id,ra_game_title=ra_title))
    return rows

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--catalogue",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--ra-catalogue",type=Path)
    parser.add_argument("--hasher",type=Path)
    args=parser.parse_args()
    if bool(args.ra_catalogue)!=bool(args.hasher):
        parser.error("--ra-catalogue and --hasher must be supplied together")
    catalogue=json.loads(args.catalogue.read_text(encoding="utf-8"))
    titles={normalise(k):v for k,v in catalogue.items() if normalise(k) and isinstance(v,str)}
    lookup=load_ra(args.ra_catalogue)
    rows=inventory(args.root,titles,args.hasher,lookup)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=FIELDS)
        writer.writeheader();writer.writerows(rows)
    from collections import Counter
    print(f"[OK] PSP read-only audit: {len(rows)} ISOs -> {args.output}")
    print("[INFO] Identity:",dict(Counter(r["status"] for r in rows)))
    print("[INFO] RetroAchievements:",dict(Counter(r["ra_status"] for r in rows)))
    print("[INFO] No PSP ISO files modified.")

if __name__=="__main__":
    main()
