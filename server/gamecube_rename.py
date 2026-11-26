#!/usr/bin/env python3
"""Conservative GameCube ISO renames, never change disc bytes."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
from dreamcast_rename import canonical, regular

def plan(root):
    if not root.is_dir() or root.is_symlink():
        raise ValueError("GameCube ISO directory unavailable")
    entries=list(root.iterdir())
    occupied={p.name.casefold() for p in entries}
    rows=[]
    for p in sorted(entries):
        if not regular(p) or p.suffix.lower()!=".iso" or p.name.startswith((".", "OLD_", "NEW_")):
            continue
        try:
            with p.open("rb") as f:
                header=f.read(32)
            if header[28:32]!=b"\xc2\x33\x9f\x3d":
                raise ValueError("Invalid GameCube disc magic")
            dest=canonical(p.stem)+".iso"
            if dest==p.name:
                print("VALID",p.name)
                continue
            if dest.casefold() in occupied:
                raise ValueError("Destination already exists (including case-only changes)")
            st=p.stat()
            rows.append((p.name,dest,st.st_size,st.st_mtime_ns))
        except (OSError,ValueError) as e:
            print("REVIEW",p.name,str(e))
    counts=Counter(row[1].casefold() for row in rows)
    safe=[]
    for row in rows:
        if counts[row[1].casefold()]>1:
            print("REVIEW",row[0],"conflicting proposals")
        else:
            print("PROPOSED",row[0],"->",row[1])
            safe.append(row)
    return safe

def main():
    p=argparse.ArgumentParser()
    p.add_argument("operation",choices=("preview","apply"))
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--journal",type=Path)
    p.add_argument("--confirm")
    a=p.parse_args()
    rows=plan(a.root)
    print(f"{len(rows)} safe proposals")
    if a.operation=="preview":
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
