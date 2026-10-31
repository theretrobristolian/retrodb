#!/usr/bin/env python3
"""Conservative PS3 ISO/sidecar naming audit. No ISO content is ever modified."""
import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SERIAL = re.compile(r"(?<![A-Z0-9])((?:BL|BC)[A-Z]{2})[-_ .]?(\d{5})(?![A-Z0-9])", re.I)
EXTENSIONS = {".iso", ".dkey", ".png"}
FIELDS = ["status", "disc_id", "catalogue_title", "existing_iso", "proposed_iso",
          "sidecars", "reason"]
def serial(value):
    match = SERIAL.search(value)
    return (match.group(1) + match.group(2)).upper() if match else ""

def safe_title(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(value))
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value if value and value not in {".", ".."} else ""

def catalogue(path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Expected GameDB serial-to-title JSON object")
    found = {}
    for raw_id, value in obj.items():
        ident = serial(raw_id)
        if not ident or not isinstance(value, str) or not safe_title(value):
            continue
        if ident in found and found[ident] != value:
            found[ident] = None  # Ambiguous IDs are not auto-renamed.
        elif ident not in found:
            found[ident] = value
    return found

def audit(root, titles):
    rows, plans = [], []
    if not root.is_dir() or root.is_symlink():
        raise ValueError("PS3 collection directory unavailable")
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
        folder = Path(base)
        lower_names = {}
        for name in files:
            lower_names.setdefault(name.casefold(), []).append(name)
        for name in sorted(files):
            iso = folder / name
            if iso.suffix.lower() != ".iso" or iso.is_symlink() or not iso.is_file():
                continue
            ident = serial(iso.stem)
            title = titles.get(ident) if ident else None
            matches = [p for p in files if Path(p).stem.casefold() == iso.stem.casefold()
                       and Path(p).suffix.lower() in EXTENSIONS]
            # Exact unique source names required, including ISO itself.
            if any(len(lower_names[x.casefold()]) > 1 for x in matches):
                status, reason = "REVIEW", "Case-insensitive source collision"
            elif not ident:
                status, reason = "REVIEW", "Missing disc ID; internal ISO ID not checked"
            elif not title:
                status, reason = "REVIEW", "Disc ID not found / ambiguous in GameDB"
            else:
                status, reason = "VALID", "Filename matches catalogue"
            target_stem = f"{safe_title(title)} [{ident}]" if title else ""
            proposed = f"{target_stem}.iso" if target_stem else ""
            moves = []
            if status == "VALID":
                for source_name in matches:
                    source = folder / source_name
                    ext = source.suffix.lower()
                    target = folder / (target_stem + ext)
                    if source.is_symlink() or not source.is_file():
                        status, reason = "REVIEW", "Symlink or invalid sidecar"
                        break
                    moves.append((source, target))
                if status == "VALID":
                    if not any(p.suffix.lower() == ".iso" for p, _ in moves):
                        status, reason = "REVIEW", "Missing primary ISO"
                    elif len({str(dst).casefold() for _, dst in moves}) != len(moves):
                        status, reason = "REVIEW", "Duplicate proposed sidecars"
                    elif any(dst.exists() and dst != src for src, dst in moves):
                        status, reason = "REVIEW", "Target exists"
                    elif any(dst.name.casefold() in lower_names and
                             dst.name.casefold() not in {src.name.casefold() for src, _ in moves}
                             for _, dst in moves):
                        status, reason = "REVIEW", "Target clashes with another file"
                    elif any(src != dst for src, dst in moves):
                        status, reason = "RENAME_CANDIDATE", "Catalogue ID matched; filename normalization"
            rel = iso.relative_to(root).as_posix()
            rows.append(dict(status=status, disc_id=ident, catalogue_title=title or "",
                             existing_iso=rel, proposed_iso=str((iso.parent / proposed).relative_to(root))
                             if proposed else "", sidecars=" | ".join(sorted(matches)), reason=reason))
            if status == "RENAME_CANDIDATE":
                plans.append([(str(src), str(dst)) for src, dst in moves if src != dst])
    # Exclude global cross-plan collisions.
    used = set()
    clean = []
    for plan in plans:
        destinations = {dst.casefold() for _, dst in plan}
        if used & destinations:
            continue
        used.update(destinations)
        clean.append(plan)
    return rows, clean

def audit_extracted(root):
    """Inventory extracted PS3 folders; deliberately do not rename their contents."""
    rows = []
    if not root.is_dir():
        return rows
    for entry in sorted(root.iterdir()):
        if entry.is_symlink() or not entry.is_dir():
            continue
        ident = serial(entry.name)
        rows.append(dict(status="SKIPPED_EXTRACTED", disc_id=ident, catalogue_title="",
                         existing_iso=str(entry), proposed_iso="", sidecars="",
                         reason="Extracted game directory; audit only, no rename"))
    return rows

def apply(plans, journal):
    if journal.exists():
        raise ValueError("Journal already exists")
    journal.parent.mkdir(parents=True, exist_ok=True)
    ops = [{"source": src, "target": dst, "state": "pending"} for plan in plans for src, dst in plan]
    def save():
        tmp = journal.with_name(journal.name + ".tmp")
        tmp.write_text(json.dumps({"created_utc": datetime.now(timezone.utc).isoformat(),
                                   "operations": ops}, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, journal)
    save()
    # Revalidate immediately before touching any filename. Atomic renames, no overwrite.
    for op in ops:
        src, dst = Path(op["source"]), Path(op["target"])
        if (src.is_symlink() or not src.is_file() or dst.exists()
                or not src.parent.samefile(dst.parent)):
            op["state"] = "blocked"
            save()
            raise RuntimeError(f"Safety check failed for {src}; journal: {journal}")
        os.rename(src, dst)
        op["state"] = "renamed"
        save()
    print(f"[OK] Renamed {len(ops)} files. Journal: {journal}")

def main():
    parser = argparse.ArgumentParser(description="PS3 title/serial audit and safe rename")
    parser.add_argument("command", choices=["audit", "preview", "apply"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--games-root", type=Path)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    rows, plans = audit(args.root, catalogue(args.catalogue))
    if args.games_root:
        rows.extend(audit_extracted(args.games_root))
    for row in rows:
        print(f'{row["status"]:17} {row["existing_iso"]} -> {row["proposed_iso"]} ({row["reason"]})')
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    print(f"Audited {len(rows)} ISOs; {len(plans)} safe rename groups. No ISO contents inspected.")
    if args.command == "apply":
        if args.confirm != "RENAMEPS3" or not args.journal:
            parser.error("Apply requires --confirm RENAMEPS3 and --journal PATH")
        apply(plans, args.journal)
if __name__ == "__main__":
    main()
