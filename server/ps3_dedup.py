#!/usr/bin/env python3
"""Read-only PS3 extracted-folder versus ISO comparison. Never deletes or renames."""
import argparse
import csv
import hashlib
import os
from pathlib import Path

from ps3_rename import serial

BLOCK = 2048
CHUNK = 4 * 1024 * 1024
FIELDS = ("status", "disc_id", "extracted", "iso", "iso_files", "extracted_files",
          "matching_files", "different_files", "reason")


class UnsupportedISO(Exception):
    pass


def iso_index(path):
    """ISO9660 file map: each value is a list of (byte offset, length) extents."""
    with path.open("rb") as handle:
        handle.seek(16 * BLOCK)
        pvd = handle.read(BLOCK)
        if len(pvd) != BLOCK or pvd[0] != 1 or pvd[1:6] != b"CD001":
            raise UnsupportedISO("ISO9660 primary descriptor not readable (encrypted/UDF?)")
        total = path.stat().st_size
        seen = set()
        records = {}

        def extent(record):
            offset = int.from_bytes(record[2:6], "little") * BLOCK
            length = int.from_bytes(record[10:14], "little")
            if offset > total or length > total - offset:
                raise UnsupportedISO("File extent exceeds ISO boundaries")
            return offset, length

        def walk(entry, prefix="", depth=0):
            if depth > 40:
                raise UnsupportedISO("Excessive ISO directory depth")
            offset, size = extent(entry)
            if size > 256 * 1024 * 1024:
                raise UnsupportedISO("Oversized ISO directory")
            if (offset, size) in seen:
                raise UnsupportedISO("Cyclic or repeated ISO directory extent")
            seen.add((offset, size))
            handle.seek(offset)
            data = handle.read(size)
            if len(data) != size:
                raise UnsupportedISO("Short ISO directory read")
            position = 0
            pending = None
            while position < len(data):
                length = data[position]
                if length == 0:
                    position = (position // BLOCK + 1) * BLOCK
                    continue
                if length < 34 or position + length > len(data):
                    raise UnsupportedISO("Malformed ISO directory entry")
                record = data[position:position+length]
                position += length
                n = record[32]
                if not n or 33 + n > length:
                    raise UnsupportedISO("Malformed filename in ISO directory")
                if n == 1 and record[33] in (0, 1):
                    continue
                try:
                    filename = record[33:33+n].decode("ascii")
                except UnicodeDecodeError as exc:
                    raise UnsupportedISO("Non-ASCII ISO9660 name") from exc
                filename = filename.split(";")[0].rstrip(".")
                if not filename or filename in (".", "..") or "/" in filename or "\\" in filename:
                    raise UnsupportedISO("Unsafe ISO9660 filename")
                key = (prefix + filename).casefold()
                is_dir = bool(record[25] & 2)
                segment = extent(record)
                continuation = bool(record[25] & 0x80)
                if pending is not None and pending != key:
                    raise UnsupportedISO("Interrupted multi-extent file chain")
                if is_dir:
                    if pending is not None or continuation or key in records:
                        raise UnsupportedISO("Invalid ISO directory or multi-extent chain")
                    walk(record, prefix + filename + "/", depth + 1)
                else:
                    if key in records and pending != key:
                        raise UnsupportedISO("Colliding ISO9660 filenames")
                    records.setdefault(key, []).append(segment)
                    pending = key if continuation else None
            if pending is not None:
                raise UnsupportedISO("Unterminated multi-extent file chain")

        walk(pvd[156:190])
    if not records:
        raise UnsupportedISO("No ISO files indexed")
    return records


def iso_size(extents):
    return sum(length for _, length in extents)


def iso_digest(handle, extents):
    digest = hashlib.sha256()
    for offset, length in extents:
        handle.seek(offset)
        remaining = length
        while remaining:
            data = handle.read(min(CHUNK, remaining))
            if not data:
                raise OSError("Unexpected end of ISO")
            digest.update(data)
            remaining -= len(data)
    return digest.hexdigest()


def extracted_index(folder):
    files = {}
    for base, dirs, names in os.walk(folder, followlinks=False):
        base = Path(base)
        if any((base / d).is_symlink() for d in dirs):
            raise UnsupportedISO("Extracted folder contains symlink directory")
        for filename in names:
            file = base / filename
            if file.is_symlink() or not file.is_file():
                raise UnsupportedISO("Extracted folder contains symlink or non-file")
            relative = file.relative_to(folder).as_posix().casefold()
            if relative in files:
                raise UnsupportedISO("Case-colliding extracted filenames")
            files[relative] = file
    return files


def file_digest(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.digest()


def extent_digest(handle, offset, size):
    digest = hashlib.sha256()
    handle.seek(offset)
    remaining = size
    while remaining:
        data = handle.read(min(CHUNK, remaining))
        if not data:
            raise OSError("Unexpected end of ISO")
        digest.update(data)
        remaining -= len(data)
    return digest.digest()


def compare_details(folder, iso, progress=None):
    details = []
    try:
        sources = extracted_index(folder)
        targets = iso_index(iso)
        matching = 0
        total_files = len(sources.keys() | targets.keys())
        if progress:
            progress(f"Indexed {len(sources)} extracted / {len(targets)} ISO files; comparing {total_files} paths")
        with iso.open("rb") as handle:
            for count, name in enumerate(sorted(sources.keys() | targets.keys()), 1):
                if progress and (count == 1 or count % 100 == 0):
                    progress(f"File {count}/{total_files}: {name[:100]}")
                source = sources.get(name)
                extents = targets.get(name)
                file_size = source.stat().st_size if source is not None else None
                image_size = iso_size(extents) if extents is not None else None
                record = dict(path=name, status="", extracted_size=file_size, iso_size=image_size,
                              extracted_sha256="", iso_sha256="")
                if source is None:
                    record["status"] = "ISO_ONLY"
                elif extents is None:
                    record["status"] = "EXTRACTED_ONLY"
                elif file_size != image_size:
                    record["status"] = "SIZE_DIFFERENT"
                else:
                    src_hash = file_digest(source).hex()
                    img_hash = iso_digest(handle, extents)
                    if src_hash == img_hash:
                        matching += 1
                        continue
                    record.update(status="HASH_DIFFERENT", extracted_sha256=src_hash, iso_sha256=img_hash)
                # Hash any smaller unshared or size-different files too; these are useful for diagnosis.
                if source is not None and not record["extracted_sha256"]:
                    record["extracted_sha256"] = file_digest(source).hex()
                if extents is not None and not record["iso_sha256"]:
                    record["iso_sha256"] = iso_digest(handle, extents)
                details.append(record)
        if not details:
            summary = ("BYTE_IDENTICAL", len(targets), len(sources), matching, 0,
                       "All paths, sizes and SHA-256 contents match; format compatibility still untested")
        else:
            counts = {kind: sum(r["status"] == kind for r in details) for kind in
                      ("ISO_ONLY", "EXTRACTED_ONLY", "SIZE_DIFFERENT", "HASH_DIFFERENT")}
            summary = ("DIFFERENT", len(targets), len(sources), matching, len(details),
                       ", ".join(f"{key}={value}" for key, value in counts.items() if value))
        return summary, details
    except (UnsupportedISO, OSError, ValueError) as exc:
        return ("INCONCLUSIVE", 0, 0, 0, 0, str(exc)), details


def compare(folder, iso):
    """Backward-compatible summary used by existing tests."""
    return compare_details(folder, iso)[0]


def audit(iso_root, games_root, details=None, progress=None):
    if not iso_root.is_dir() or not games_root.is_dir():
        raise ValueError("PS3 ISO and extracted roots must exist")
    by_id = {}
    for iso in iso_root.rglob("*"):
        if iso.suffix.casefold() == ".iso" and iso.is_file() and not iso.is_symlink():
            by_id.setdefault(serial(iso.stem), []).append(iso)
    result = []
    folders = [folder for folder in sorted(games_root.iterdir()) if folder.is_dir() and not folder.is_symlink()]
    for position, folder in enumerate(folders, 1):
        if not folder.is_dir() or folder.is_symlink():
            continue
        disc = serial(folder.name)
        if progress:
            progress(f"[{position}/{len(folders)}] START {folder.name}")
        choices = by_id.get(disc, []) if disc else []
        row = dict(status="", disc_id=disc, extracted=str(folder), iso="", iso_files=0,
                   extracted_files=0, matching_files=0, different_files=0, reason="")
        if not disc:
            row.update(status="INCONCLUSIVE", reason="No extracted disc ID")
        elif not choices:
            row.update(status="NO_EXACT_ISO", reason="No ISO with identical disc ID; possible other-region release")
        elif len(choices) > 1:
            row.update(status="INCONCLUSIVE", reason="Multiple ISOs with this disc ID")
        else:
            iso = choices[0]
            (status, iso_n, extracted_n, matched, changed, reason), differences = compare_details(folder, iso, progress=progress)
            if details is not None:
                for difference in differences:
                    details.append({"disc_id": disc, "extracted": str(folder), "iso": str(iso), **difference})
            row.update(status=status, iso=str(iso), iso_files=iso_n,
                       extracted_files=extracted_n, matching_files=matched,
                       different_files=changed, reason=reason)
        result.append(row)
        if progress:
            progress(f"[{position}/{len(folders)}] DONE {row['status']}, {row['matching_files']} matched")
    return result


FIRMWARE_PATH = "ps3_update/ps3updat.pup"
# Scope of this explicitly approved clean-up, not a general-purpose game deleter.
APPROVED_DISC_IDS = {"BLES00680", "BLES01179"}


def removable_candidates(iso_root, games_root):
    """Only a perfect SHA-256 match, ignoring one ISO-only firmware updater."""
    rows = audit(iso_root, games_root)
    candidates = []
    for row in rows:
        if (row["disc_id"] not in APPROVED_DISC_IDS or row["status"] != "DIFFERENT"
                or row["different_files"] != 1 or not row["iso"]):
            continue
        folder, iso = Path(row["extracted"]), Path(row["iso"])
        summary, details = compare_details(folder, iso)
        if (summary[0] == "DIFFERENT" and summary[3] == summary[2] > 0
                and len(details) == 1 and details[0]["status"] == "ISO_ONLY"
                and details[0]["path"] == FIRMWARE_PATH):
            candidates.append((folder, iso))
    return candidates


def remove_verified(iso_root, games_root, confirm):
    """Hash each approved Red Dead pair once immediately before removal."""
    if confirm != "DELETE VERIFIED":
        raise ValueError("Explicit DELETE VERIFIED confirmation required")
    if iso_root.is_symlink() or games_root.is_symlink():
        raise ValueError("Symlink root refused")
    import shutil
    deleted = 0
    for disc in sorted(APPROVED_DISC_IDS):
        folders = [p for p in games_root.iterdir()
                   if p.is_dir() and not p.is_symlink() and serial(p.name) == disc]
        isos = [p for p in iso_root.rglob("*.iso")
                if p.is_file() and not p.is_symlink() and serial(p.stem) == disc]
        if len(folders) != 1 or len(isos) != 1:
            print(f"[SKIP] {disc}: expected one extracted folder and one matching ISO")
            continue
        folder, iso = folders[0], isos[0]
        print(f"[VERIFY] {disc}: hashing ISO against {folder.name}", flush=True)
        summary, details = compare_details(
            folder, iso,
            progress=lambda message: print(f"[VERIFY {disc}] {message}", flush=True),
        )
        if not (summary[0] == "DIFFERENT" and summary[3] == summary[2] > 0
                and len(details) == 1 and details[0]["status"] == "ISO_ONLY"
                and details[0]["path"] == FIRMWARE_PATH):
            print(f"[SKIP] {disc}: content no longer qualifies ({summary[0]})", flush=True)
            continue
        if folder.parent != games_root or folder.is_symlink():
            raise ValueError(f"Unsafe deletion target: {folder}")
        # Refuse symlinks and nonregular files anywhere inside before rmtree.
        extracted_index(folder)
        print(f"[REMOVE] {folder.name}: all shared game files SHA-256 identical", flush=True)
        shutil.rmtree(folder)
        deleted += 1
    print(f"[OK] Removed {deleted} verified redundant extracted folders.", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Read-only PS3 extracted versus ISO deduplication audit")
    parser.add_argument("--iso-root", type=Path, required=True)
    parser.add_argument("--games-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--remove-verified", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.remove_verified:
        remove_verified(args.iso_root, args.games_root, args.confirm)
        return
    differences = []
    rows = audit(args.iso_root, args.games_root, differences,
                 progress=lambda message: print("[PROGRESS] " + message, flush=True))
    for row in rows:
        print(f'{row["status"]:15} {Path(row["extracted"]).name} | {Path(row["iso"]).name if row["iso"] else "(no exact ISO)"} | '
              f'{row["matching_files"]}/{row["extracted_files"]} matched | {row["reason"]}')
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"CSV: {args.output}")
        detail_path = args.output.with_name(args.output.stem + "-Files.csv")
        with detail_path.open("w", newline="", encoding="utf-8") as stream:
            columns = ("disc_id", "extracted", "iso", "path", "status", "extracted_size", "iso_size", "extracted_sha256", "iso_sha256")
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(differences)
        print(f"File differences: {detail_path} ({len(differences)} entries)")
    print(f"Checked {len(rows)} extracted folders (read-only); no deletion or rename performed.")


if __name__ == "__main__":
    main()
