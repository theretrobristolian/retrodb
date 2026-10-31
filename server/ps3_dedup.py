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
    """Map ISO9660 file paths to (extent byte offset, length). Fail closed."""
    with path.open("rb") as handle:
        handle.seek(16 * BLOCK)
        pvd = handle.read(BLOCK)
        if len(pvd) != BLOCK or pvd[0] != 1 or pvd[1:6] != b"CD001":
            raise UnsupportedISO("ISO9660 primary descriptor not readable (encrypted/UDF?)")
        total = path.stat().st_size
        seen = set()
        records = {}
        def walk(entry, prefix="", depth=0):
            if depth > 40:
                raise UnsupportedISO("Excessive ISO directory depth")
            extent = int.from_bytes(entry[2:6], "little")
            size = int.from_bytes(entry[10:14], "little")
            offset = extent * BLOCK
            if size > 256 * 1024 * 1024 or offset + size > total:
                raise UnsupportedISO("Invalid ISO directory extent")
            if (offset, size) in seen:
                raise UnsupportedISO("Cyclic or duplicated ISO directory extent")
            seen.add((offset, size))
            handle.seek(offset)
            data = handle.read(size)
            if len(data) != size:
                raise UnsupportedISO("Short ISO directory read")
            position = 0
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
                if n in (0, 1) and record[33] in (0, 1):
                    continue
                try:
                    filename = record[33:33+n].decode("ascii")
                except UnicodeDecodeError as exc:
                    raise UnsupportedISO("Non-ASCII ISO9660 name") from exc
                filename = filename.split(";")[0].rstrip(".")
                if not filename or filename in (".", "..") or "/" in filename or "\\" in filename:
                    raise UnsupportedISO("Unsafe ISO9660 filename")
                key = (prefix + filename).casefold()
                if key in records:
                    raise UnsupportedISO("Colliding ISO9660 filenames")
                is_dir = bool(record[25] & 2)
                if is_dir:
                    walk(record, prefix + filename + "/", depth + 1)
                else:
                    file_offset = int.from_bytes(record[2:6], "little") * BLOCK
                    file_size = int.from_bytes(record[10:14], "little")
                    if file_offset + file_size > total or record[25] & 0x80:
                        raise UnsupportedISO("File extent invalid or multi-extent unsupported")
                    records[key] = (file_offset, file_size)
        walk(pvd[156:190])
    if not records:
        raise UnsupportedISO("No ISO files indexed")
    return records


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


def compare(folder, iso):
    try:
        sources = extracted_index(folder)
        targets = iso_index(iso)
        missing_in_iso = sorted(sources.keys() - targets.keys())
        missing_in_folder = sorted(targets.keys() - sources.keys())
        shared = sorted(sources.keys() & targets.keys())
        differing = []
        matching = 0
        with iso.open("rb") as handle:
            for name in shared:
                offset, size = targets[name]
                if sources[name].stat().st_size != size:
                    differing.append(name)
                    continue
                if file_digest(sources[name]) == extent_digest(handle, offset, size):
                    matching += 1
                else:
                    differing.append(name)
        if not differing and not missing_in_iso and not missing_in_folder:
            return ("BYTE_IDENTICAL", len(targets), len(sources), matching, 0,
                    "All paths, sizes and SHA-256 contents match; format compatibility still untested")
        details = []
        for label, values in (("different", differing), ("extracted-only", missing_in_iso),
                              ("ISO-only", missing_in_folder)):
            if values:
                details.append(f"{label}={len(values)} (e.g. {values[0]})")
        return ("DIFFERENT", len(targets), len(sources), matching,
                len(differing) + len(missing_in_iso) + len(missing_in_folder), "; ".join(details))
    except (UnsupportedISO, OSError, ValueError) as exc:
        return ("INCONCLUSIVE", 0, 0, 0, 0, str(exc))


def audit(iso_root, games_root):
    if not iso_root.is_dir() or not games_root.is_dir():
        raise ValueError("PS3 ISO and extracted roots must exist")
    by_id = {}
    for iso in iso_root.rglob("*"):
        if iso.suffix.casefold() == ".iso" and iso.is_file() and not iso.is_symlink():
            by_id.setdefault(serial(iso.stem), []).append(iso)
    result = []
    for folder in sorted(games_root.iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        disc = serial(folder.name)
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
            status, iso_n, extracted_n, matched, changed, reason = compare(folder, iso)
            row.update(status=status, iso=str(iso), iso_files=iso_n,
                       extracted_files=extracted_n, matching_files=matched,
                       different_files=changed, reason=reason)
        result.append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description="Read-only PS3 extracted versus ISO deduplication audit")
    parser.add_argument("--iso-root", type=Path, required=True)
    parser.add_argument("--games-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = audit(args.iso_root, args.games_root)
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
    print(f"Checked {len(rows)} extracted folders (read-only); no deletion or rename performed.")


if __name__ == "__main__":
    main()
