#!/usr/bin/env python3
"""Read-only, resumable full-file SHA-256 inventory for compatibility exports.

This is NOT a RetroAchievements hash. PS1 checks the BIN media referenced by
its CUE; PS2/PS3/PSP check ISO bytes. Extracted PS3 folders are deliberately
excluded because a folder has no meaningful single-file SHA-256 digest.
"""
import argparse
import csv
import hashlib
import json
import os
import shlex
import tempfile
from pathlib import Path

FIELDS = ("sha256", "sha256_target", "sha256_status")
CHUNK = 4 * 1024 * 1024


def source_path(kind, record, root):
    root = Path(root)
    if kind == "ra":
        source = root / record.get("path", "")
        if record.get("platform") == "Sony PlayStation" and source.suffix.lower() == ".cue":
            # Single-BIN CUE sheets only: do not claim a CUE hash is a disc hash.
            lines = source.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            refs = []
            for line in lines:
                if not line.lstrip().upper().startswith("FILE "):
                    continue
                parts = shlex.split(line)
                if len(parts) != 3 or parts[0].upper() != "FILE" or parts[2].upper() != "BINARY":
                    raise ValueError("Unsupported CUE FILE declaration")
                refs.append(parts[1])
            if len(refs) != 1 or not refs[0].lower().endswith(".bin"):
                raise ValueError("PS1 requires exactly one referenced BIN")
            name = refs[0]
            if name in (".", "..") or "/" in name or "\\" in name:
                raise ValueError("Unsafe CUE BIN reference")
            source = source.parent / name
        return source
    if kind == "ps3":
        if record.get("status", "").startswith("EXTRACTED_"):
            return None
        source = root / "roms/sony/playstation3/iso" / record.get("existing_iso", "")
        return source if source.suffix.lower() == ".iso" else None
    if kind == "psp":
        source = root / "roms/sony/playstationportable/iso" / record.get("relative_path", "")
        return source if source.suffix.lower() == ".iso" else None
    raise ValueError(f"Unsupported sheet {kind}")


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".sha256-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, sort_keys=True)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def enrich(kind, csv_path, root, cache, cache_path):
    with csv_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields:
        raise ValueError(f"Empty audit CSV: {csv_path}")
    for col in FIELDS:
        if col not in fields:
            fields.append(col)
    processed = hits = errors = skipped = 0
    for row in rows:
        row.update({key: "" for key in FIELDS})
        try:
            target = source_path(kind, row, root)
            if target is None:
                row["sha256_status"] = "NOT_APPLICABLE — extracted folder"
                skipped += 1
                continue
            if target.is_symlink() or not target.is_file():
                raise ValueError("Image is missing or a symlink")
            stat = target.stat()
            if not stat.st_size:
                raise ValueError("Empty image")
            key = str(target)
            entry = cache.get(key, {})
            if (entry.get("size") == stat.st_size and
                    entry.get("mtime_ns") == stat.st_mtime_ns and
                    isinstance(entry.get("sha256"), str) and
                    len(entry["sha256"]) == 64):
                digest = entry["sha256"]
                hits += 1
                state = "CACHED"
            else:
                digest = sha256_file(target)
                # Do not cache a digest when a file changed during hashing.
                after = target.stat()
                if after.st_size != stat.st_size or after.st_mtime_ns != stat.st_mtime_ns:
                    raise ValueError("Image changed during hash calculation")
                cache[key] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest}
                processed += 1
                state = "VERIFIED"
                # Persist progress so interruption doesn't discard earlier hours of work.
                write_json_atomic(cache_path, cache)
            row.update(sha256=digest, sha256_target=str(target.relative_to(root)),
                       sha256_status=state)
        except (OSError, ValueError, UnicodeError) as exc:
            row["sha256_status"] = f"ERROR — {type(exc).__name__}: {str(exc)[:130]}"
            errors += 1
    fd, temp = tempfile.mkstemp(prefix=".sha256-audit-", suffix=".csv", dir=csv_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        os.chmod(temp, 0o600)
        os.replace(temp, csv_path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print(f"[SHA-256] {kind}: {len(rows)} rows; {processed} hashed, {hits} reused, {skipped} folders skipped, {errors} errors.", flush=True)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/mnt/retrodb-retronas"))
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--ra", type=Path, required=True)
    parser.add_argument("--ps3", type=Path)
    parser.add_argument("--psp", type=Path)
    args = parser.parse_args()
    try:
        cache = json.loads(args.cache.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            raise ValueError("Invalid SHA cache object")
    except FileNotFoundError:
        cache = {}
    errors = 0
    for kind, path in (("ra", args.ra), ("ps3", args.ps3), ("psp", args.psp)):
        if path and path.is_file():
            errors += enrich(kind, path, args.root, cache, args.cache)
    print("[SHA-256] Note: cached hashes are revalidated using file size and mtime; use a fresh cache for a forced full rehash.")
    if errors:
        print(f"[WARNING] {errors} image checksums unavailable; individual rows marked ERROR.")


if __name__ == "__main__":
    main()
