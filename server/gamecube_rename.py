#!/usr/bin/env python3
"""Conservative GameCube ISO renames, never change disc bytes."""
import argparse
from collections import Counter
import json
import os
import re
from pathlib import Path
from dreamcast_rename import canonical, regular

REGIONS = {"E":"USA","J":"Japan","P":"Europe","D":"Germany","F":"France","I":"Italy","S":"Spain","K":"Korea","U":"Australia"}
REGION_TAG = re.compile(r"\((?:USA|Japan|Europe|Germany|France|Italy|Spain|Korea|Australia|World|Asia)(?:,\s*[^()]*)?\)", re.I)

def disc_header(path):
    with path.open("rb") as f:
        header=f.read(0x400)
    if len(header)<0x400 or header[28:32]!=b"\xc2\x33\x9f\x3d":
        raise ValueError("Invalid GameCube disc header")
    ident=header[:6].decode("ascii", errors="replace")
    if not re.fullmatch(r"[A-Z0-9]{6}",ident):
        raise ValueError("Invalid GameCube disc ID")
    return dict(disc_id=ident,region=REGIONS.get(ident[3],""),
                disc=header[6]+1,revision=header[7],
                internal_title=header[0x20:0x400].split(b"\0",1)[0].decode("shift_jis",errors="replace"))

def proposed_name(path, info):
    if not info["region"]:
        raise ValueError("Unknown disc ID region code: "+info["disc_id"])
    stem=path.stem.strip()
    region=REGION_TAG.search(stem)
    if region:
        if region.group(0).casefold()!=("("+info["region"]+")").casefold():
            raise ValueError("Existing region differs from disc ID; review")
        stem=stem[:region.start()]+stem[region.end():]
    disc=re.search(r"\(Disc\s+(\d+)\)",stem,re.I)
    if disc and int(disc[1])!=info["disc"]:
        raise ValueError("Existing disc number differs from header")
    rev=re.search(r"\((?:Rev\s*(\d+)|v1\.(\d+))\)",stem,re.I)
    if rev and int(rev[1] or rev[2])!=info["revision"]:
        raise ValueError("Existing revision differs from header")
    if disc:
        stem=stem[:disc.start()]+stem[disc.end():]
    if rev:
        stem=re.sub(r"\((?:Rev\s*\d+|v1\.\d+)\)","",stem,flags=re.I)
    tags=re.findall(r"\([^()]*\)",stem)
    title=re.sub(r"\([^()]*\)","",stem).strip()
    title=re.sub(r"^(.+?), (The|A|An)(?=\s*(?: - |$))",r"\2 \1",title,flags=re.I)
    title=re.sub(r"\s{2,}"," ",title).strip()
    if not title:
        raise ValueError("Missing filename title")
    parts=[title,"("+info["region"]+")"]
    if disc or info["disc"]>1:
        parts.append(f'(Disc {info["disc"]})')
    if info["revision"]:
        parts.append(f'(Rev {info["revision"]})')
    parts.extend(tags)
    return canonical(" ".join(parts))+".iso"

def plan(root):
    if not root.is_dir() or root.is_symlink():
        raise ValueError("GameCube ISO directory unavailable")
    entries=list(root.iterdir())
    occupied={p.name.casefold() for p in entries}
    rows=[]
    valid=0
    review=0
    for p in sorted(entries):
        if not regular(p) or p.suffix.lower()!=".iso" or p.name.startswith((".", "OLD_", "NEW_")):
            continue
        try:
            info=disc_header(p)
            dest=proposed_name(p,info)
            if dest==p.name:
                valid+=1
                continue
            if dest.casefold() in occupied:
                raise ValueError("Destination already exists (including case-only changes)")
            st=p.stat()
            rows.append((p.name,dest,st.st_size,st.st_mtime_ns))
        except (OSError,ValueError) as e:
            review+=1
            print("REVIEW",p.name,str(e))
    counts=Counter(row[1].casefold() for row in rows)
    safe=[]
    for row in rows:
        if counts[row[1].casefold()]>1:
            review+=1
            print("REVIEW",row[0],"conflicting proposals")
        else:
            print("PROPOSED",row[0],"->",row[1])
            safe.append(row)
    print(f'[SUMMARY] Already correct: {valid} | Proposed: {len(safe)} | Review: {review}')
    return safe

def main():
    p=argparse.ArgumentParser()
    p.add_argument("operation",choices=("preview","apply"))
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--journal",type=Path)
    p.add_argument("--confirm")
    p.add_argument("--exit-if-no-changes", action="store_true", help="Return 3 for an empty preview")
    a=p.parse_args()
    rows=plan(a.root)
    print(f"{len(rows)} safe proposals")
    if a.operation=="preview":
        if a.exit_if_no_changes and not rows:
            raise SystemExit(3)
        return
    if a.confirm!="RENAME GAMECUBE" or not a.journal:
        p.error("Explicit confirmation and journal required")
    with a.journal.open("x",encoding="utf-8") as f:
        def record(event,src,dst):
            f.write(json.dumps(dict(event=event,source=src,destination=dst))+"\n")
            f.flush()
            os.fsync(f.fileno())
        for src,dst,size,mtime in rows:
            source=a.root/src
            target=a.root/dst
            if not regular(source) or (source.stat().st_size,source.stat().st_mtime_ns)!=(size,mtime):
                raise RuntimeError("Source changed: "+src)
            if any(q.name.casefold()==dst.casefold() for q in a.root.iterdir()):
                raise RuntimeError("Destination changed: "+dst)
            record("begin",src,dst)
            # Linux renameat2 RENAME_NOREPLACE: fail closed if unsupported.
            import ctypes
            import errno
            libc=ctypes.CDLL(None,use_errno=True)
            rename=libc.renameat2
            rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
            rename.restype=ctypes.c_int
            if rename(-100,os.fsencode(source),-100,os.fsencode(target),1):
                err=ctypes.get_errno()
                raise OSError(err,os.strerror(err),str(source))
            record("complete",src,dst)
            print("DONE",dst)
if __name__=="__main__":
    main()
