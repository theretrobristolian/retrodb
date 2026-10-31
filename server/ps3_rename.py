#!/usr/bin/env python3
"""Conservative PS3 ISO/sidecar naming audit. No ISO content is ever modified."""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import uuid
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


def internal_disc_id(path):
    """Best-effort ISO9660 PARAM.SFO TITLE_ID / PS3_DISC.SFB scan, bounded reads."""
    try:
        with path.open("rb") as fh:
            fh.seek(16 * 2048)
            pvd = fh.read(2048)
            if len(pvd) != 2048 or pvd[1:6] != b"CD001":
                return "", "ISO9660 volume descriptor unavailable (possibly encrypted)"
            def directory(record):
                if len(record) < 34:
                    return None
                block = int.from_bytes(record[2:6], "little")
                size = int.from_bytes(record[10:14], "little")
                if not block or not 0 < size <= 16 * 1024 * 1024:
                    return None
                fh.seek(block * 2048)
                return fh.read(size)
            def entries(blob):
                pos = 0
                found = {}
                while pos < len(blob):
                    n = blob[pos]
                    if n == 0:
                        pos = (pos // 2048 + 1) * 2048
                        continue
                    if n < 34 or pos + n > len(blob):
                        break
                    entry = blob[pos:pos+n]
                    ln = entry[32]
                    label = entry[33:33+ln].decode("ascii", "ignore").split(";")[0].upper()
                    found[label] = entry
                    pos += n
                return found
            roots = entries(directory(pvd[156:190]) or b"")
            game = roots.get("PS3_GAME")
            if game:
                inside = entries(directory(game) or b"")
                sfo = inside.get("PARAM.SFO")
                if sfo:
                    blob = directory(sfo)
                    if blob and blob[:4] == b"\x00PSF" and len(blob) >= 20:
                        key_start = int.from_bytes(blob[8:12], "little")
                        value_start = int.from_bytes(blob[12:16], "little")
                        count = min(int.from_bytes(blob[16:20], "little"), 512)
                        for i in range(count):
                            entry = blob[20+i*16:36+i*16]
                            if len(entry) < 16:
                                break
                            ko = int.from_bytes(entry[:2], "little")
                            vo = int.from_bytes(entry[12:16], "little")
                            key = blob[key_start+ko:key_start+ko+32].split(b"\0")[0]
                            if key == b"TITLE_ID":
                                candidate = blob[value_start+vo:value_start+vo+32].split(b"\0")[0].decode("ascii", "ignore")
                                return (serial(candidate), "PARAM.SFO TITLE_ID") if serial(candidate) else ("", "Invalid PARAM.SFO TITLE_ID")
            sfb = roots.get("PS3_DISC.SFB")
            if sfb:
                blob = directory(sfb) or b""
                candidates = set(re.findall(rb"(?:BL|BC)[A-Z]{2}[-_ .]?\d{5}", blob, re.I))
                ids = {serial(x.decode("ascii", "ignore")) for x in candidates}
                if len(ids) == 1:
                    return ids.pop(), "PS3_DISC.SFB"
            return "", "No readable internal disc ID"
    except (OSError, ValueError) as exc:
        return "", f"Metadata unavailable: {type(exc).__name__}"

def duplicate_target(folder, stem, sources, files):
    """Reserve a case-insensitive unused duplicate basename for the whole sidecar group."""
    occupied = {f.casefold() for f in files}
    source_names = {p.casefold() for p in sources}
    for number in range(1, 1000):
        suffix = " - duplicate" if number == 1 else f" - duplicate {number}"
        match = re.fullmatch(r"(.+) (\[[A-Z0-9]+\])", stem)
        candidate = (match.group(1) + suffix + " " + match.group(2)) if match else stem + suffix
        destinations = [candidate + Path(name).suffix.lower() for name in sources]
        if not any(dst.casefold() in occupied and dst.casefold() not in source_names
                   for dst in destinations):
            return candidate
    return ""


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def edition_title(filename, catalogue_title):
    """Keep explicitly named special editions even when title catalogue omits them."""
    stem = re.sub(r"\s*\[[A-Z]{4}\d{5}\]\s*$", "", filename, flags=re.I).strip()
    if re.search(r"\bXL Edition\b", stem, re.I):
        return safe_title(stem), True
    if re.search(r"\bArcade Edition\b", stem, re.I):
        return safe_title(stem), True
    return safe_title(catalogue_title), False

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
            filename_id = serial(iso.stem)
            internal_id, id_source = internal_disc_id(iso) if not filename_id else ("", "not checked")
            ident = filename_id or internal_id
            title = titles.get(ident) if ident else None
            matches = [p for p in files if Path(p).stem.casefold() == iso.stem.casefold()
                       and Path(p).suffix.lower() in EXTENSIONS]
            # Exact unique source names required, including ISO itself.
            if any(len(lower_names[x.casefold()]) > 1 for x in matches):
                status, reason = "REVIEW", "Case-insensitive source collision"
            elif not ident:
                status, reason = "REVIEW", "Missing disc ID; " + id_source
            elif not filename_id:
                if title and id_source == "PARAM.SFO TITLE_ID":
                    status, reason = "VALID", f"Verified internal {id_source} and matched GameDB"
                else:
                    status, reason = "REVIEW", f"Internal disc ID recovered from {id_source}; verify before renaming"
            elif not title:
                status, reason = "REVIEW", "Disc ID not found / ambiguous in GameDB"
            else:
                status, reason = "VALID", "Filename matches catalogue"
            display_title, protected_edition = edition_title(iso.stem, title) if title else ("", False)
            target_stem = f"{display_title} [{ident}]" if title else ""
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
                        # Only a conflicting ISO proves that two ISO paths exist.
                        # Never hash sidecars as substitutes for disc images.
                        conflict_isos = [dst for src, dst in moves if src.suffix.lower() == ".iso"
                                         and dst.exists() and dst != src]
                        if conflict_isos:
                            other = conflict_isos[0]
                            if other.is_symlink() or not other.is_file():
                                status, reason = "REVIEW", "Conflicting ISO is not a regular file"
                            elif iso.samefile(other):
                                # SMB can resolve differently-cased spellings to the same inode.
                                # Staging under a unique temporary name changes the actual case safely.
                                if all(not dst.exists() or src.samefile(dst) for src, dst in moves):
                                    status, reason = "RENAME_CANDIDATE", "Case-only SMB alias; staged rename required"
                                else:
                                    status, reason = "REVIEW_SIDECAR", "Case-only ISO but another sidecar destination is occupied"
                            elif iso.stat().st_size == other.stat().st_size and sha256(iso) == sha256(other):
                                old_name = "OLD_" + iso.name
                                if (folder / old_name).exists():
                                    status, reason = "REVIEW", "Identical ISO; OLD_ destination already exists"
                                else:
                                    status, reason = "REVIEW_IDENTICAL", "SHA256 identical to " + other.name + "; OLD_ proposed (not automatic)"
                                    proposed = old_name
                            else:
                                alternative = duplicate_target(folder, target_stem, matches, files)
                                if alternative:
                                    proposed = alternative + ".iso"
                                    status, reason = "REVIEW_DUPLICATE", "Different ISO SHA256 from " + other.name + "; duplicate name proposed"
                                else:
                                    status, reason = "REVIEW", "No safe duplicate name"
                        else:
                            status, reason = "REVIEW_SIDECAR", "Only sidecar target occupied; ISO not duplicated"
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

def audit_extracted(root, titles=None):
    """Inventory extracted PS3 folders; deliberately do not rename their contents."""
    rows = []
    titles = titles or {}
    if not root.is_dir():
        return rows
    for entry in sorted(root.iterdir()):
        if entry.is_symlink() or not entry.is_dir():
            continue
        ident = serial(entry.name)
        title = titles.get(ident) if ident else None
        target = f"{safe_title(title)} [{ident}] - extracted" if title else ""
        status = ("EXTRACTED_VALID" if target == entry.name else
                  "EXTRACTED_RENAME_CANDIDATE" if target and not (entry.parent / target).exists() else
                  "EXTRACTED_REVIEW")
        rows.append(dict(status=status, disc_id=ident, catalogue_title=title or "",
                         existing_iso=str(entry), proposed_iso=target, sidecars="",
                         reason="Disc ID matched GameDB; folder only, contents untouched" if title
                                else "Unmatched disc ID; manual review"))
    return rows

def _save_journal(journal, payload):
    """Persist state before and after each filesystem mutation."""
    temp = journal.with_name(journal.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, journal)


def _run_journal(journal):
    data = json.loads(journal.read_text(encoding="utf-8"))
    for op in data["operations"]:
        source, staged, target = (Path(op[name]) for name in ("source", "staged", "target"))
        state = op["state"]
        if state == "done":
            if not target.exists() or staged.exists():
                raise RuntimeError(f"Completed operation has inconsistent target: {target}")
            continue
        if state in {"pending", "staging"}:
            # A crash after rename but before journal update leaves the unique temp.
            if staged.exists() and not source.exists():
                op["state"] = "staged"
                _save_journal(journal, data)
            elif source.exists() and not source.is_symlink() and not staged.exists():
                # A target that resolves to the source is a case-insensitive alias.
                if target.exists() and not source.samefile(target):
                    raise RuntimeError(f"Target already occupied: {target}")
                op["state"] = "staging"
                _save_journal(journal, data)
                os.rename(source, staged)
                op["state"] = "staged"
                _save_journal(journal, data)
            else:
                raise RuntimeError(f"Unexpected stage state for: {source}")
        if op["state"] in {"staged", "finalizing"}:
            if staged.exists() and not target.exists():
                op["state"] = "finalizing"
                _save_journal(journal, data)
                os.rename(staged, target)
                op["state"] = "done"
                _save_journal(journal, data)
            elif not staged.exists() and target.exists():
                op["state"] = "done"
                _save_journal(journal, data)
            else:
                raise RuntimeError(f"Unexpected finalization state for: {target}")
    print(f"[OK] Completed {len(data['operations'])} file renames; journal: {journal}")


def apply(plans, journal):
    if journal.exists():
        raise ValueError("Journal already exists; use recover with that journal")
    journal.parent.mkdir(parents=True, exist_ok=True)
    ops = []
    reserved = set()
    for plan in plans:
        for src_text, dst_text in plan:
            source, target = Path(src_text), Path(dst_text)
            if source.parent != target.parent or not source.is_file() or source.is_symlink():
                raise RuntimeError(f"Unsafe source or target: {source}")
            if target.exists() and not source.samefile(target):
                raise RuntimeError(f"Occupied destination: {target}")
            if str(target).casefold() in reserved:
                raise RuntimeError(f"Duplicate destination: {target}")
            reserved.add(str(target).casefold())
            temp = source.parent / (".retrodb-ps3-" + uuid.uuid4().hex + ".tmp")
            if temp.exists():
                raise RuntimeError(f"Temporary name occupied: {temp}")
            ops.append({"source": str(source), "staged": str(temp),
                        "target": str(target), "state": "pending"})
    _save_journal(journal, {"version": 2, "created_utc": datetime.now(timezone.utc).isoformat(),
                            "operations": ops})
    _run_journal(journal)


def recover(journal):
    if not journal.is_file():
        raise ValueError("Journal not found")
    data = json.loads(journal.read_text(encoding="utf-8"))
    if data.get("version") != 2:
        raise ValueError("Unsupported journal version; manual investigation required")
    _run_journal(journal)

def rename_extracted(rows, journal):
    """Only rename top-level extracted directories, with a resumable journal."""
    if journal.exists():
        raise ValueError("Journal already exists; recover it first")
    moves = []
    for row in rows:
        if row["status"] != "EXTRACTED_RENAME_CANDIDATE":
            continue
        source = Path(row["existing_iso"])
        target = source.parent / row["proposed_iso"]
        if not source.is_dir() or source.is_symlink() or target.exists():
            raise RuntimeError(f"Unsafe extracted folder rename: {source}")
        temp = source.parent / (".retrodb-ps3-extracted-" + uuid.uuid4().hex)
        moves.append({"source": str(source), "staged": str(temp),
                      "target": str(target), "state": "pending"})
    journal.parent.mkdir(parents=True, exist_ok=True)
    _save_journal(journal, {"version": 2, "operations": moves})
    _run_journal(journal)


def main():
    parser = argparse.ArgumentParser(description="PS3 title/serial audit and safe rename")
    parser.add_argument("command", choices=["audit", "preview", "apply", "recover", "extracted-preview", "extracted-apply"])
    parser.add_argument("--root", type=Path)
    parser.add_argument("--catalogue", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--games-root", type=Path)
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.command == "recover":
        if not args.journal:
            parser.error("Recover requires --journal")
        recover(args.journal)
        return
    if not args.root or not args.catalogue:
        parser.error("Audit/preview/apply require --root and --catalogue")
    titles = catalogue(args.catalogue)
    if args.command in ("extracted-preview", "extracted-apply"):
        if not args.games_root:
            parser.error("--games-root required")
        rows = audit_extracted(args.games_root, titles)
        for row in rows:
            print(f'{row["status"]:28} {row["existing_iso"]} -> {row["proposed_iso"]} ({row["reason"]})')
        if args.command == "extracted-apply":
            if args.confirm != "RENAMEEXTRACTED" or not args.journal:
                parser.error("Extracted apply requires --confirm RENAMEEXTRACTED and --journal")
            rename_extracted(rows, args.journal)
        return
    rows, plans = audit(args.root, titles)
    if args.games_root:
        rows.extend(audit_extracted(args.games_root, catalogue(args.catalogue)))
    for row in rows:
        print(f'{row["status"]:17} {row["existing_iso"]} -> {row["proposed_iso"]} ({row["reason"]})')
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    print(f"Audited {len(rows)} ISOs; {len(plans)} safe rename groups. SHA256 computed only for conflicting ISOs; OLD_ proposals are review-only.")
    if args.command == "apply":
        if args.confirm != "RENAMEPS3" or not args.journal:
            parser.error("Apply requires --confirm RENAMEPS3 and --journal PATH")
        apply(plans, args.journal)
if __name__ == "__main__":
    main()
