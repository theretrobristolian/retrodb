#!/usr/bin/env python3
"""Conservative PS1 RA conflict resolver. Reviewed Alundra, Driver and Gran Turismo 2 same-disc collisions.

Never deletes a BIN, overwrites existing files or trusts filenames as RA proof.
A journal is written BEFORE any rename; interrupted work requires manual review.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

RA_HASH = "940e0711309dd542a8a487edf2aebeb9"
UNMATCHED_HASH = "3841328147ba8a9bbdd152d9a599b296"
SOURCE_NAME = "Alundra (USA) (Rev 1)"
TARGET_NAME = "Alundra [SLUS-00553]"
ROOT_REL = Path("iso")
# Exact reviewed identities; never group by RA game ID alone.
PROFILES = {
    "alundra": dict(source=SOURCE_NAME, target=TARGET_NAME, serial="SLUS-00553",
                    verified=RA_HASH, unmatched=UNMATCHED_HASH),
    "driver": dict(source="Driver - You Are the Wheelman (USA) (Rev 1)",
                   target="Driver You Are the Wheelman [SLUS-00842]",
                   serial="SLUS-00842", verified="96be802f3f536946b5906f06029766f1",
                   unmatched=None),
    "gt2-simulation": dict(source="Gran Turismo 2 (USA) (Simulation Mode) (Rev 2)",
                           target="Gran Turismo 2 (Simulation Mode) [SCUS-94488]",
                           serial="SCUS-94488", verified="4ea57dce50b86a32f0d5034479c1bc48",
                           unmatched=None),
}

FILE_RE = re.compile(r'^(\s*FILE\s+)(?:"([^"]+)"|(\S+))(\s+[^\r\n]+)$', re.I)


def ra_hash(hasher, cue):
    result = subprocess.run([str(hasher), "12", str(cue)], capture_output=True,
                            text=True, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError("RAHasher failed: " + (result.stderr or result.stdout)[-220:])
    hashes = re.findall(r"(?i)\b[a-f0-9]{32}\b", result.stdout + "\n" + result.stderr)
    if len(hashes) != 1:
        raise RuntimeError("RAHasher did not return exactly one unambiguous hash")
    return hashes[0].lower()


def verify_pair(cue, binary):
    if any(p.is_symlink() or not p.is_file() for p in (cue, binary)):
        raise RuntimeError("Missing or symlinked CUE/BIN")
    raw = cue.read_bytes()
    try:
        txt = raw.decode("utf-8-sig")
        enc = "utf-8-sig"
    except UnicodeDecodeError:
        txt = raw.decode("cp1252")
        enc = "cp1252"
    lines = txt.splitlines(keepends=True)
    matches = [(i, FILE_RE.match(line.rstrip("\r\n"))) for i, line in enumerate(lines)
               if line.lstrip().upper().startswith("FILE ")]
    if len(matches) != 1 or not matches[0][1]:
        raise RuntimeError("CUE must contain exactly one parseable FILE reference")
    match = matches[0][1]
    if (match.group(2) or match.group(3)) != binary.name:
        raise RuntimeError("CUE does not reference expected BIN")
    return raw, enc, lines, matches[0]


def rewritten(lines, line_match, binary, enc):
    i, match = line_match
    out = list(lines)
    ending = "\r\n" if out[i].endswith("\r\n") else ("\n" if out[i].endswith("\n") else "")
    out[i] = match.group(1) + '"' + binary.name + '"' + match.group(4) + ending
    return "".join(out).encode(enc)


def inspect(root, hasher, profile="alundra"):
    from report_ps1_audit import disc_serial
    cfg = PROFILES[profile]
    folder = root / ROOT_REL
    a_cue, a_bin = (folder / (cfg["source"] + suffix) for suffix in (".cue", ".bin"))
    b_cue, b_bin = (folder / (cfg["target"] + suffix) for suffix in (".cue", ".bin"))
    backup_cue = folder / ("OLD_" + cfg["target"] + ".cue")
    backup_bin = folder / ("OLD_" + cfg["target"] + ".bin")
    paths = [a_cue, a_bin, b_cue, b_bin]
    if any(not x.is_file() or x.is_symlink() for x in paths):
        return None
    if backup_cue.exists() or backup_bin.exists():
        raise RuntimeError("OLD_ backup already exists; refusing collision resolution")
    if len({str(p).casefold() for p in paths + [backup_cue, backup_bin]}) != 6:
        raise RuntimeError("Case-folded name collision")
    for cue, binary in ((a_cue, a_bin), (b_cue, b_bin)):
        verify_pair(cue, binary)
    if disc_serial(a_bin) != cfg["serial"] or disc_serial(b_bin) != cfg["serial"]:
        raise RuntimeError("Disc serial differs from reviewed identity for " + profile)
    source_hash = ra_hash(hasher, a_bin)
    target_hash = ra_hash(hasher, b_bin)
    if source_hash != cfg["verified"] or target_hash == cfg["verified"]:
        raise RuntimeError("Verified hash evidence changed for " + profile)
    if cfg["unmatched"] is not None and target_hash != cfg["unmatched"]:
        raise RuntimeError("Unmatched copy hash changed for " + profile)
    if source_hash == target_hash:
        raise RuntimeError("Identical disc hashes; not a collision to promote")
    return dict(source_cue=a_cue, source_bin=a_bin, dest_cue=b_cue, dest_bin=b_bin,
                backup_cue=backup_cue, backup_bin=backup_bin,
                verified_hash=source_hash, unmatched_hash=target_hash)


def apply(root, hasher, journal, expected, profile="alundra"):
    if journal.exists():
        raise RuntimeError("Journal exists; refusing overwrite")
    operation = inspect(root, hasher, profile)
    if operation is None:
        raise RuntimeError("Pairs changed since preview: " + profile)
    if (operation["verified_hash"], operation["unmatched_hash"]) != expected:
        raise RuntimeError("RA hashes changed since confirmed preview")
    src_raw, src_enc, src_lines, src_match = verify_pair(operation["source_cue"], operation["source_bin"])
    dst_raw, dst_enc, dst_lines, dst_match = verify_pair(operation["dest_cue"], operation["dest_bin"])
    def write(state):
        record = {"operation": "verified-ps1-collision", "profile": profile, "state": state,
                  "created_utc": datetime.now(timezone.utc).isoformat(),
                  "paths": {k: str(v) for k, v in operation.items() if isinstance(v, Path)},
                  "verified_hash": operation["verified_hash"],
                  "unmatched_hash": operation["unmatched_hash"],
                  "original_cues_hex": {"source": src_raw.hex(), "destination": dst_raw.hex()}}
        journal.parent.mkdir(parents=True, exist_ok=True)
        temp = journal.with_suffix(".json.tmp")
        temp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(temp, journal)
    # Journal each irreversible step. Leave files as-is on error for recovery.
    write("pending")
    operation["dest_bin"].rename(operation["backup_bin"])
    write("unmatched-bin-backed-up")
    operation["dest_cue"].rename(operation["backup_cue"])
    write("unmatched-cue-backed-up")
    operation["backup_cue"].write_bytes(rewritten(dst_lines, dst_match, operation["backup_bin"], dst_enc))
    write("backup-cue-relinked")
    operation["source_bin"].rename(operation["dest_bin"])
    write("verified-bin-promoted")
    operation["source_cue"].rename(operation["dest_cue"])
    write("verified-cue-promoted")
    operation["dest_cue"].write_bytes(rewritten(src_lines, src_match, operation["dest_bin"], src_enc))
    write("verified-cue-relinked")
    if (ra_hash(hasher, operation["dest_bin"]), ra_hash(hasher, operation["backup_bin"])) != expected:
        raise RuntimeError("Post-rename RA verification failed; inspect journal immediately")
    write("applied")
    print("[OK]", profile, "RA-compatible pair promoted; unmatched pair preserved as OLD_.")



def verify_completed(journal, ro_root, hasher):
    """Finish only post-rename verification; never rename or rewrite collection files."""
    record = json.loads(journal.read_text(encoding="utf-8"))
    if record.get("operation") not in ("alundra-ra-collision", "verified-ps1-collision"):
        raise RuntimeError("Not a PS1 collision journal")
    cfg = PROFILES[record.get("profile", "alundra")]
    if record.get("state") not in ("verified-cue-relinked", "applied"):
        raise RuntimeError("Journal is not ready for final verification: " + str(record.get("state")))
    paths = record["paths"]
    expected_dir = (ro_root / ROOT_REL).resolve()
    for name in ("dest_cue", "dest_bin", "backup_cue", "backup_bin"):
        candidate = Path(paths[name])
        if candidate.name != (("OLD_" if name.startswith("backup_") else "") + cfg["target"] + (".cue" if name.endswith("cue") else ".bin")):
            raise RuntimeError("Journal contains unexpected filename for " + name)
    active_cue = expected_dir / (cfg["target"] + ".cue")
    active_bin = expected_dir / (cfg["target"] + ".bin")
    backup_cue = expected_dir / ("OLD_" + cfg["target"] + ".cue")
    backup_bin = expected_dir / ("OLD_" + cfg["target"] + ".bin")
    verify_pair(active_cue, active_bin)
    verify_pair(backup_cue, backup_bin)
    active_hash = ra_hash(hasher, active_bin)
    old_hash = ra_hash(hasher, backup_bin)
    print("[VERIFY] Active:", active_hash, "expected:", record["verified_hash"])
    print("[VERIFY] OLD_  :", old_hash, "expected:", record["unmatched_hash"])
    if (active_hash, old_hash) != (record["verified_hash"], record["unmatched_hash"]):
        raise RuntimeError("Final RA hash mismatch; journal unchanged")
    if record["state"] == "applied":
        print("[OK] Already verified and completed")
        return
    record["state"] = "applied"
    record["verified_utc"] = datetime.now(timezone.utc).isoformat()
    tmp = journal.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(tmp, journal)
    print("[OK] Both hashes verified on read-only RetroNAS; existing journal completed.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("preview", "apply", "count", "verify-journal"))
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--hasher", type=Path, default=Path("/opt/retrodb-tools/RAHasher"))
    p.add_argument("--journal", type=Path)
    args = p.parse_args()
    if args.mode == "verify-journal":
        if not args.journal:
            p.error("--journal required for verify-journal")
        verify_completed(args.journal, args.root, args.hasher)
        return
    available = [(key, op) for key in PROFILES
                 if (op := inspect(args.root, args.hasher, key)) is not None]
    if args.mode == "count":
        print(len(available))
        return
    if not available:
        print("[INFO] No reviewed PS1 RA collision requiring resolution")
        return
    for profile, operation in available:
        print("[RA CONFLICT]", profile, "verified:", operation["source_cue"].name,
              "=>", operation["dest_cue"].name)
        print("[PRESERVE]", operation["dest_cue"].name, "=>", operation["backup_cue"].name)
    if args.mode == "apply":
        if not args.journal:
            p.error("--journal required for apply")
        for profile, operation in available:
            target_journal = args.journal.with_name(args.journal.stem + "-" + profile + ".json")
            apply(args.root, args.hasher, target_journal,
                  (operation["verified_hash"], operation["unmatched_hash"]), profile)
            print("[JOURNAL]", target_journal)
    else:
        print("PREVIEW ONLY: no files changed.")


if __name__ == "__main__":
    main()
