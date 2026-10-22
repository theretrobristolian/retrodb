#!/usr/bin/env python3
"""One-at-a-time verified PS2 patch deployment to a temporary RetroNAS RW mount.

Never delete OLD_ backups. Never modify the ISO until the patched image's RA
hash matches the manifest. Save a local operation journal before any writes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from retrodb.retroachievements_match import hash_file
from retrodb.retroachievements_patches import _current_xdelta, _source_requirements, _validate_source, PatchError

def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)

def file_sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def deploy(args):
    workspace, mount, read_mount = (p.resolve(strict=True) for p in (args.workspace, args.mount, args.read_mount))
    plan = json.loads((workspace / "patch-plan.json").read_text())
    prepared = json.loads((workspace / "patch-prepare.json").read_text())
    selected = [e for e in plan if str(e.get("ra_game_id")) == args.game_id and e.get("platform") == "Sony PlayStation 2"]
    if len(selected) != 1:
        raise PatchError("Select exactly one planned PS2 patch by RA game ID")
    item = selected[0]
    matching = [e for e in prepared if e.get("title") == item["title"]
                and e.get("state") == "clean-base-verified-ready-to-patch"
                and e.get("candidate_path") == e.get("collection_source")]
    if len(matching) != 1:
        raise PatchError("Exact RetroNAS source is not READY; no network file will be changed")
    if item.get("local_region", "").casefold() != item.get("required_region", "").casefold():
        raise PatchError("Source/patch region mismatch; refusing network replacement")
    relative = Path(item["local_path"])
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".iso":
        raise PatchError("Unsafe or unsupported ISO path")
    src = mount / relative
    read_src = read_mount / relative
    if not src.is_file() or not read_src.is_file() or src.is_symlink() or src.parent.is_symlink():
        raise PatchError("Original ISO missing or unsafe")
    if src.stat().st_size != read_src.stat().st_size:
        raise PatchError("RW and RO mount disagree about source size")
    backup = src.with_name("OLD_" + src.name)
    if backup.exists():
        raise PatchError("OLD_ backup already exists; refusing to overwrite it")
    patch = _current_xdelta(workspace, args.game_id, item["title"])
    requirements = _source_requirements(workspace, args.game_id, item["title"])
    valid, kind, actual = _validate_source(read_src, requirements, args.hasher, 21)
    if not valid:
        raise PatchError(f"Source changed since audit or checksum mismatch ({kind}: {actual})")
    expected = str(item.get("expected_ra_hash", "")).casefold()
    if len(expected) != 32 or any(x not in "0123456789abcdef" for x in expected):
        raise PatchError("Missing valid expected RA hash")
    local = workspace / "workspace" / ("network-deploy-" + uuid.uuid4().hex)
    local.mkdir(parents=True)
    journal = args.journal.resolve()
    if journal.exists():
        raise PatchError("Journal exists; refusing to overwrite")
    record = {"game_id": args.game_id, "source": str(src), "backup": str(backup),
              "expected_ra_hash": expected, "state": "preparing"}
    write_json(journal, record)
    staged = local / "patched.iso"
    try:
        if shutil.disk_usage(local).free < src.stat().st_size + 1024**3:
            raise PatchError("Not enough local disk space to stage patch")
        done = subprocess.run(["xdelta3", "-d", "-s", str(read_src), str(patch), str(staged)],
                              capture_output=True, text=True, check=False)
        if done.returncode:
            raise PatchError("Patch failed: " + done.stderr.strip()[-500:])
        verified = hash_file(args.hasher, 21, staged)
        if verified != expected:
            raise PatchError(f"Patched RA hash mismatch: expected {expected}, got {verified}")
        record.update(state="patched-locally-verified", actual_ra_hash=verified)
        write_json(journal, record)
        if args.dry_run:
            print("[OK] DRY RUN: patched locally and RA verified; nothing written to RetroNAS")
            return

        # Preserve the original BEFORE replacing the live filename.
        print("[+] Copying original to OLD_ backup on RetroNAS...")
        shutil.copy2(src, backup)
        if backup.stat().st_size != src.stat().st_size or file_sha256(backup) != file_sha256(src):
            raise PatchError("OLD_ backup integrity check failed")
        record["state"] = "backup-verified"
        write_json(journal, record)
        transient = src.with_name(".retrodb-patch-" + uuid.uuid4().hex + ".iso")
        try:
            shutil.copyfile(staged, transient)
            if hash_file(args.hasher, 21, transient) != expected:
                raise PatchError("Patched copy on RetroNAS failed RA hash verification")
            record["state"] = "network-copy-verified"
            write_json(journal, record)
            # Same-directory atomic rename; OLD_ remains untouched.
            os.replace(transient, src)
            record["state"] = "replaced-pending-final-check"
            write_json(journal, record)
            if hash_file(args.hasher, 21, src) != expected:
                raise PatchError("Final RetroNAS ISO hash mismatch; restore from OLD_ manually")
            record["state"] = "verified-on-retronas"
            write_json(journal, record)
            print(f"[OK] RA-verified patched ISO: {src}")
            print(f"[SAFE] Original preserved: {backup}")
        finally:
            if transient.exists():
                transient.unlink()
    except Exception as exc:
        record["error"] = str(exc)
        if record["state"] != "verified-on-retronas":
            record["state"] = "failed-" + record["state"]
        write_json(journal, record)
        raise
    finally:
        shutil.rmtree(local, ignore_errors=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-id", required=True)
    ap.add_argument("--workspace", type=Path, default=Path("/var/lib/retrodb/patches"))
    ap.add_argument("--mount", type=Path, required=True)
    ap.add_argument("--read-mount", type=Path, default=Path("/mnt/retrodb-retronas"))
    ap.add_argument("--hasher", type=Path, default=Path("/opt/retrodb-tools/RAHasher"))
    ap.add_argument("--journal", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    try:
        deploy(args)
    except (PatchError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
