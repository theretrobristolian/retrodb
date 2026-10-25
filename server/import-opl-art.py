#!/usr/bin/env python3
"""Import an extracted Luden02 OPL artwork archive into an existing OPL ART share.

Never deletes destination files. Never assumes where the user's RetroNAS is mounted.
PS1 artwork is staged separately, not mixed into the PS2 OPL directory.
"""
from __future__ import annotations
import argparse
import shutil
from pathlib import Path

def import_art(source: Path, target: Path, apply: bool, replace: bool) -> tuple[int,int,int]:
    copied = skipped = candidates = 0
    if not source.is_dir() or not target.is_dir():
        raise ValueError("Source and destination must exist as directories")
    if source.resolve() == target.resolve():
        raise ValueError("Source and target cannot be the same directory")
    for item in source.glob("*/*.png"):
        if item.is_symlink() or not item.is_file():
            continue
        # Avoid letting unexpectedly named files escape the target or collide.
        if not item.name.startswith(item.parent.name + "_"):
            continue
        dst = target / item.name
        candidates += 1
        if dst.exists() and not replace:
            skipped += 1
            continue
        if apply:
            shutil.copy2(item, dst)
        copied += 1
    return candidates, copied, skipped

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True,
                   help="Path to extracted psx-ps2-opl-art-database clone")
    p.add_argument("--ps2-art", type=Path, required=True,
                   help="Existing, correctly mounted OPL ART folder")
    p.add_argument("--ps1-art", type=Path,
                   help="Optional separate existing staging folder for PS1 artwork")
    p.add_argument("--apply", action="store_true",
                   help="Copy files (default is safe dry run)")
    p.add_argument("--replace", action="store_true",
                   help="Allow overwriting previously copied art (default skip)")
    args = p.parse_args()
    try:
        ps2 = import_art(args.source / "PS2", args.ps2_art, args.apply, args.replace)
        print(f"PS2: candidates={ps2[0]} {'copied' if args.apply else 'would copy'}={ps2[1]} already present={ps2[2]}")
        if args.ps1_art:
            ps1 = import_art(args.source / "PS1", args.ps1_art, args.apply, args.replace)
            print(f"PS1 staging: candidates={ps1[0]} {'copied' if args.apply else 'would copy'}={ps1[1]} already present={ps1[2]}")
        print("Finished. No destination files were deleted.")
    except (ValueError, OSError) as exc:
        p.error(str(exc))

if __name__ == "__main__":
    main()
