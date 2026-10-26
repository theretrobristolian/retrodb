#!/usr/bin/env python3
"""Deploy ONE previously RA-verified PS1 BIN/CUE patch, preserving OLD_ originals.

Never overwrite existing OLD_ backups. Stages and verifies both files before
switching the active pair; journalled restore on errors. RetroNAS is RO except
for the explicitly supplied temporary writable mount.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

from retrodb.retroachievements_match import hash_file

FILE = re.compile(r'^(\s*FILE\s+)(?:"([^"]+)"|(\S+))(\s+BINARY\s*)$', re.I | re.M)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w") as out:
        json.dump(record, out, indent=2)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)


def cue_bin(path):
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
        encoding = "cp1252"
    matches = list(FILE.finditer(text))
    if len(matches) != 1:
        raise ValueError("Expected exactly one BINARY FILE reference in CUE")
    value = matches[0].group(2) or matches[0].group(3)
    if Path(value).name != value or "/" in value or "\\" in value or not value.lower().endswith(".bin"):
        raise ValueError("Unsafe CUE BIN reference")
    return path.parent / value, text, encoding, matches[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-id", required=True)
    ap.add_argument("--ro-mount", type=Path, required=True)
    ap.add_argument("--rw-mount", type=Path, required=True)
    ap.add_argument("--journal", type=Path, required=True)
    ap.add_argument("--hasher", type=Path, default=Path("/opt/retrodb-tools/RAHasher"))
    ap.add_argument("--workspace", type=Path, default=Path("/var/lib/retrodb/patches"))
    args = ap.parse_args()
    if not args.game_id.isdecimal():
        ap.error("Invalid game ID")
    workspace = args.workspace
    record = {"game_id": args.game_id, "state": "initialising"}
    plan = json.loads((workspace / "patch-plan.json").read_text())
    choices = [p for p in plan if str(p.get("ra_game_id")) == args.game_id and p.get("platform") == "Sony PlayStation"]
    if len(choices) != 1:
        raise ValueError("Expected one unambiguous PS1 patch plan for RA ID")
    choice = choices[0]
    entries = json.loads((workspace / "patch-apply.json").read_text())
    matched = [e for e in entries if str(e.get("ra_game_id")) == args.game_id and e.get("status") == "patched-and-verified"]
    if len(matched) != 1:
        raise ValueError("No unique locally patched-and-verified PS1 pair; patch first")
    result = matched[0]
    expected = str(result.get("ra_hash", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{32}", expected) or expected != str(choice.get("expected_ra_hash", "")).lower():
        raise ValueError("Patch verification hash does not match plan")
    relative = Path(choice["local_path"])
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".cue":
        raise ValueError("Unsafe PS1 CUE path")
    ro_root, rw_root = args.ro_mount.resolve(strict=True), args.rw_mount.resolve(strict=True)
    ro_cue, active_cue = ro_root / relative, rw_root / relative
    if not ro_cue.is_file() or not active_cue.is_file() or ro_cue.is_symlink() or active_cue.is_symlink():
        raise ValueError("Original CUE unavailable/unsafe")
    ro_bin, _, _, _ = cue_bin(ro_cue)
    active_bin = active_cue.parent / ro_bin.name
    if not ro_bin.is_file() or not active_bin.is_file() or ro_bin.is_symlink() or active_bin.is_symlink():
        raise ValueError("Original BIN unavailable/unsafe")
    if not str(ro_bin.resolve()).startswith(str(ro_root) + os.sep):
        raise ValueError("Original BIN escapes NAS")
    patched_cue, patched_bin = Path(result["cue"]), Path(result["output"])
    referenced_bin, _, _, _ = cue_bin(patched_cue)
    if referenced_bin.resolve() != patched_bin.resolve():
        raise ValueError("Patched CUE points to wrong BIN")
    if hash_file(args.hasher, 12, patched_cue) != expected:
        raise ValueError("Local patched pair no longer RA-verified")
    if digest(ro_cue) != digest(active_cue) or digest(ro_bin) != digest(active_bin):
        raise ValueError("Read-only and writable NAS mounts disagree")
    old_cue = active_cue.with_name("OLD_" + active_cue.name)
    old_bin = active_bin.with_name("OLD_" + active_bin.name)
    if old_cue.exists() or old_bin.exists():
        raise ValueError("An OLD_ backup already exists: refusing overwrite/redeployment")
    if args.journal.exists():
        raise ValueError("Journal already exists")
    token = uuid.uuid4().hex
    stage_dir = active_cue.parent / ("retrodb-patch-stage-" + token)
    stage_dir.mkdir(mode=0o700)
    stage_bin = stage_dir / active_bin.name
    stage_cue = stage_dir / active_cue.name
    # Keep the exact live BIN filename in the temporary CUE. The RAHasher
    # uses disc-file identity while locating the PlayStation executable;
    # randomised/hidden temporary BIN names can make it reject a valid disc.
    def rewrite_cue(new_bin_name):
        _, text, encoding, match = cue_bin(patched_cue)
        updated = text[:match.start()] + match.group(1) + '"' + new_bin_name + '"' + match.group(4) + text[match.end():]
        return updated.encode(encoding)
    record.update(source=str(active_cue), source_bin=str(active_bin),
                  backup=str(old_cue), backup_bin=str(old_bin),
                  expected_ra_hash=expected, state="staging")
    save(args.journal, record)
    switched_bin = switched_cue = False
    try:
        shutil.copyfile(patched_bin, stage_bin)
        stage_cue.write_bytes(rewrite_cue(active_bin.name))
        if hash_file(args.hasher, 12, stage_cue) != expected:
            raise ValueError("Staged NAS BIN/CUE RA hash mismatch")
        record["state"] = "creating-backups"
        save(args.journal, record)
        shutil.copy2(active_bin, old_bin)
        shutil.copy2(active_cue, old_cue)
        if digest(old_bin) != digest(active_bin) or digest(old_cue) != digest(active_cue):
            raise ValueError("OLD_ BIN/CUE SHA256 verification failed")
        record["state"] = "backups-verified"
        save(args.journal, record)
        record["state"] = "switching-pair"
        save(args.journal, record)
        os.replace(stage_bin, active_bin)
        switched_bin = True
        os.replace(stage_cue, active_cue)
        switched_cue = True
        record["state"] = "verifying-active-pair"
        save(args.journal, record)
        if hash_file(args.hasher, 12, active_cue) != expected:
            raise ValueError("Final active CUE/BIN RA hash mismatch")
        record.update(state="verified-on-retronas", actual_ra_hash=expected)
        save(args.journal, record)
        print("[OK] RA verified on RetroNAS:", active_cue)
        print("[SAFE] Original BIN/CUE retained as OLD_ backups")
    except Exception as exc:
        record["error"] = str(exc)
        if switched_bin or switched_cue:
            # Keep OLD_ backups, restore active filenames from verified backup.
            try:
                for original, backup in ((active_bin, old_bin), (active_cue, old_cue)):
                    temp = original.with_name(".retrodb-restore-" + uuid.uuid4().hex)
                    shutil.copyfile(backup, temp)
                    if digest(temp) != digest(backup):
                        raise ValueError("Restoration SHA256 check failed")
                    os.replace(temp, original)
                record["state"] = "restored-from-old"
            except Exception as restore_exc:
                record["state"] = "MANUAL-RECOVERY-REQUIRED"
                record["restore_error"] = str(restore_exc)
        else:
            record["state"] = "failed-before-switch"
        save(args.journal, record)
        raise
    finally:
        for staged in (stage_bin, stage_cue):
            if staged.exists():
                staged.unlink()
        if stage_dir.exists():
            stage_dir.rmdir()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[ERROR]", exc, file=sys.stderr)
        sys.exit(1)
