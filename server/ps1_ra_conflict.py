#!/usr/bin/env python3
"""Conservative PS1 RA conflict resolver. Reviewed Alundra, Driver and Gran Turismo 2 same-disc collisions.

Never deletes a BIN, overwrites existing files or trusts filenames as RA proof.
A journal is written BEFORE any rename; interrupted work requires manual review.
"""
import argparse
import csv
import hashlib
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
                   serial="SLUS-00842", ra_game_id="11391", verified="96be802f3f536946b5906f06029766f1",
                   unmatched=None),
    "gt2-simulation": dict(source="Gran Turismo 2 (USA) (Simulation Mode) (Rev 2)",
                           target="Gran Turismo 2 (Simulation Mode) [SCUS-94488]",
                           serial="SCUS-94488", ra_game_id="11278", verified="4ea57dce50b86a32f0d5034479c1bc48",
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


def audit_pair(audit_path, cfg, source_hash, target_hash):
    """Prove one verified and one unmatched same-disc image in the raw RA audit."""
    if not audit_path or not Path(audit_path).is_file():
        raise RuntimeError("Fresh raw RetroAchievements CSV required")
    with open(audit_path, newline="", encoding="utf-8-sig") as handle:
        rows = [r for r in csv.DictReader(handle)
                if r.get("platform") == "Sony PlayStation"]
    def unique(stem):
        matches = [r for r in rows if Path(r.get("path", "")).stem == stem]
        if len(matches) != 1:
            raise RuntimeError("Missing or ambiguous RA audit for " + stem)
        return matches[0]
    source = unique(cfg["source"])
    target = unique(cfg["target"])
    game_id = cfg["ra_game_id"]
    if (not cfg.get("identical") and source.get("status") != "matched"
            or (not cfg.get("identical") and str(source.get("ra_game_id")) != game_id)
            or (cfg.get("identical") and str(source.get("ra_game_id") or source.get("no_set_ra_game_id") or ("serial:" + cfg["serial"])) != game_id)
            or source.get("local_ra_hash", "").lower() != source_hash
            or (not cfg.get("identical") and target.get("status") != "unmatched")
            or str((target.get("ra_game_id") or target.get("no_set_ra_game_id") or ("serial:" + cfg["serial"])) if cfg.get("identical") else target.get("recommended_ra_game_id")) != game_id
            or target.get("local_ra_hash", "").lower() != target_hash):
        raise RuntimeError("RA audit does not prove a verified source and unmatched destination")
    if (source.get("local_serial") != cfg["serial"]
            or target.get("local_serial") != cfg["serial"]
            or source.get("disc_id_conflict") == "YES"
            or target.get("disc_id_conflict") == "YES"):
        raise RuntimeError("RA audit disc serial conflict")


def discover(audit, ps1_audit):
    """Discover same-serial canonical collisions from two independent audits.

    No game/title allowlist. Fail closed on missing RA evidence or ambiguous
    sources/targets. An RA game ID without equal disc serial is insufficient.
    """
    if not audit or not ps1_audit:
        raise RuntimeError("Both RA and PS1 file audits are required")
    with open(audit, newline="", encoding="utf-8-sig") as fh:
        ra_rows = [r for r in csv.DictReader(fh) if r.get("platform") == "Sony PlayStation"]
    with open(ps1_audit, newline="", encoding="utf-8-sig") as fh:
        file_rows = list(csv.DictReader(fh))
    by_stem = {}
    for row in ra_rows:
        by_stem.setdefault(Path(row.get("path", "")).stem, []).append(row)
    def ra(stem):
        records = by_stem.get(stem, [])
        return records[0] if len(records) == 1 else None
    candidates = {}
    for row in file_rows:
        issue = row.get("issues", "")
        if "CUE_DESTINATION_EXISTS" not in issue or "BIN_DESTINATION_EXISTS" not in issue:
            continue
        if any(x in issue for x in ("DISC_ID_MISMATCH", "MULTI_BIN_REVIEW",
                                     "MISSING_REFERENCE", "INTERNAL_ID_UNVERIFIED")):
            continue
        source_rel = Path(row.get("relative_cue", ""))
        target_rel = Path(row.get("proposed_cue", ""))
        if not source_rel.name or not target_rel.name or source_rel.parent != target_rel.parent:
            continue
        if source_rel.suffix.lower() != ".cue" or target_rel.suffix.lower() != ".cue":
            continue
        # Different modes, disc numbers, and special editions may share RA ID
        # or disc serial; never auto-archive one as another.
        def variant(stem):
            words = stem.casefold()
            mode = re.search(r"\\b(arcade|simulation)(?:\\s+mode)?\\b", words)
            disc = re.search(r"\\b(?:disc|disk|cd)\\s*[-_ ]*(\\d+)\\b", words)
            edition = re.search(r"\\b(special edition|collector(?:'s|s)? edition)\\b", words)
            return (mode.group(1) if mode else "",
                    disc.group(1) if disc else "",
                    edition.group(1) if edition else "")
        if variant(source_rel.stem) != variant(target_rel.stem):
            continue
        serial = row.get("internal_serial", "")
        if not serial or row.get("selected_serial") != serial:
            continue
        src, dst = ra(source_rel.stem), ra(target_rel.stem)
        if not src or not dst:
            continue
        identical = (src.get("status") == dst.get("status")
                     and src.get("status") in ("matched", "unmatched")
                     and bool(src.get("local_ra_hash")) and bool(dst.get("local_ra_hash")))
        # Equal compatibility and identity can be redundant despite BIN differences.
        promotion = src.get("status") == "matched" and dst.get("status") == "unmatched"
        if not (identical or promotion):
            continue
        if src.get("local_serial") != serial or dst.get("local_serial") != serial:
            continue
        if src.get("disc_id_conflict") == "YES" or dst.get("disc_id_conflict") == "YES":
            continue
        game_id = str(src.get("ra_game_id") or src.get("no_set_ra_game_id") or "")
        target_id = str(dst.get("ra_game_id") or dst.get("no_set_ra_game_id") or "")
        if not game_id and identical:
            game_id = "serial:" + serial
            target_id = game_id
        if not game_id or (not identical and str(dst.get("recommended_ra_game_id", "")) != game_id) or (identical and target_id != game_id):
            continue
        src_hash = src.get("local_ra_hash", "").lower()
        dst_hash = dst.get("local_ra_hash", "").lower()
        if not (re.fullmatch(r"[a-f0-9]{32}", src_hash)
                and re.fullmatch(r"[a-f0-9]{32}", dst_hash)
                and (identical or src_hash != dst_hash)):
            continue
        key = str(target_rel)
        cfg = dict(source=source_rel.stem, target=target_rel.stem,
                   folder=source_rel.parent.as_posix(), serial=serial,
                   ra_game_id=game_id, verified=src_hash, unmatched=dst_hash,
                   identical=identical, archive_source=identical)
        candidates.setdefault(key, []).append(cfg)
    # A canonical destination with multiple eligible sources is ambiguous.
    return {"collision-%04d" % number: candidates[key][0]
            for number, key in enumerate(sorted(candidates), 1)
            if len(candidates[key]) == 1}


class NotIdenticalDuplicate(RuntimeError):
    """RA-equivalent images with different complete BIN contents; preserve both."""


def inspect(root, hasher, profile="alundra", audit=None):
    from report_ps1_audit import disc_serial
    cfg = PROFILES[profile]
    folder = root / Path(cfg.get("folder", "iso"))
    a_cue, a_bin = (folder / (cfg["source"] + suffix) for suffix in (".cue", ".bin"))
    b_cue, b_bin = (folder / (cfg["target"] + suffix) for suffix in (".cue", ".bin"))
    backup_stem = cfg["source"] if cfg.get("archive_source") else cfg["target"]
    backup_cue = folder / ("OLD_" + backup_stem + ".cue")
    backup_bin = folder / ("OLD_" + backup_stem + ".bin")
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
    if source_hash != cfg["verified"] or (target_hash == cfg["verified"] and not cfg.get("identical")):
        raise RuntimeError("Verified hash evidence changed for " + profile)
    if cfg["unmatched"] is not None and target_hash != cfg["unmatched"]:
        raise RuntimeError("Unmatched copy hash changed for " + profile)
    if cfg.get("archive_source") and not cfg.get("ra_game_id", "").startswith("serial:"):
        pass  # Both images share a reviewed RA identity, not necessarily bytes.
    elif source_hash == target_hash and not cfg.get("identical"):
        raise RuntimeError("Equal hashes without an explicit duplicate decision")
    elif cfg.get("archive_source") and source_hash != target_hash:
        raise RuntimeError("No reviewed RA identity; unequal hashes need manual review")
    if profile != "alundra":
        audit_pair(audit, cfg, source_hash, target_hash)
    return dict(source_cue=a_cue, source_bin=a_bin, dest_cue=b_cue, dest_bin=b_bin,
                backup_cue=backup_cue, backup_bin=backup_bin,
                verified_hash=source_hash, unmatched_hash=target_hash)


def apply(root, hasher, journal, expected, profile="alundra", audit=None):
    if journal.exists():
        raise RuntimeError("Journal exists; refusing overwrite")
    operation = inspect(root, hasher, profile, audit)
    if operation is None:
        raise RuntimeError("Pairs changed since preview: " + profile)
    if (operation["verified_hash"], operation["unmatched_hash"]) != expected:
        raise RuntimeError("RA hashes changed since confirmed preview")
    src_raw, src_enc, src_lines, src_match = verify_pair(operation["source_cue"], operation["source_bin"])
    dst_raw, dst_enc, dst_lines, dst_match = verify_pair(operation["dest_cue"], operation["dest_bin"])
    def write(state):
        record = {"operation": "verified-ps1-collision", "profile": profile, "config": PROFILES[profile], "state": state,
                  "created_utc": datetime.now(timezone.utc).isoformat(),
                  "paths": {k: str(v) for k, v in operation.items() if isinstance(v, Path)},
                  "verified_hash": operation["verified_hash"],
                  "unmatched_hash": operation["unmatched_hash"],
                  "original_cues_hex": {"source": src_raw.hex(), "destination": dst_raw.hex()}}
        journal.parent.mkdir(parents=True, exist_ok=True)
        temp = journal.with_suffix(".json.tmp")
        temp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(temp, journal)
    if PROFILES[profile].get("archive_source"):
        write("pending")
        operation["source_bin"].rename(operation["backup_bin"])
        write("source-bin-backed-up")
        operation["source_cue"].rename(operation["backup_cue"])
        write("source-cue-backed-up")
        operation["backup_cue"].write_bytes(rewritten(src_lines, src_match, operation["backup_bin"], src_enc))
        write("source-cue-relinked")
        if (ra_hash(hasher, operation["backup_bin"]), ra_hash(hasher, operation["dest_bin"])) != expected:
            raise RuntimeError("Post-archive hash verification failed; inspect journal")
        write("applied")
        print("[OK]", profile, "canonical pair retained; other pair now OLD_.")
        return
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
    cfg = record.get("config") or PROFILES[record.get("profile", "alundra")]
    if record.get("state") not in ("verified-cue-relinked", "source-cue-relinked", "applied"):
        raise RuntimeError("Journal is not ready for final verification: " + str(record.get("state")))
    paths = record["paths"]
    expected_dir = (ro_root / Path(cfg.get("folder", "iso"))).resolve()
    for name in ("dest_cue", "dest_bin", "backup_cue", "backup_bin"):
        candidate = Path(paths[name])
        if candidate.name != (("OLD_" if name.startswith("backup_") else "") + (cfg["source"] if name.startswith("backup_") and cfg.get("archive_source") else cfg["target"]) + (".cue" if name.endswith("cue") else ".bin")):
            raise RuntimeError("Journal contains unexpected filename for " + name)
    active_cue = expected_dir / (cfg["target"] + ".cue")
    active_bin = expected_dir / (cfg["target"] + ".bin")
    backup_cue = expected_dir / ("OLD_" + (cfg["source"] if cfg.get("archive_source") else cfg["target"]) + ".cue")
    backup_bin = expected_dir / ("OLD_" + (cfg["source"] if cfg.get("archive_source") else cfg["target"]) + ".bin")
    verify_pair(active_cue, active_bin)
    verify_pair(backup_cue, backup_bin)
    active_hash = ra_hash(hasher, active_bin)
    old_hash = ra_hash(hasher, backup_bin)
    print("[VERIFY] Active:", active_hash, "expected:", record["verified_hash"])
    print("[VERIFY] OLD_  :", old_hash, "expected:", record["unmatched_hash"])
    if (active_hash, old_hash) != ((record["unmatched_hash"], record["verified_hash"]) if cfg.get("archive_source") else (record["verified_hash"], record["unmatched_hash"])):
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
    p.add_argument("--audit", type=Path)
    p.add_argument("--ps1-audit", type=Path)
    args = p.parse_args()
    if args.mode == "verify-journal":
        if not args.journal:
            p.error("--journal required for verify-journal")
        verify_completed(args.journal, args.root, args.hasher)
        return
    PROFILES.clear()
    PROFILES.update(discover(args.audit, args.ps1_audit))
    available = []
    skipped = []
    for key in PROFILES:
        try:
            operation = inspect(args.root, args.hasher, key, args.audit)
        except NotIdenticalDuplicate as exc:
            skipped.append((key, str(exc)))
            continue
        if operation is not None:
            available.append((key, operation))
    if args.mode != "count":
        for key, reason in skipped:
            print("[SKIP - REVIEW]", PROFILES[key]["source"], "=>",
                  PROFILES[key]["target"], "-", reason)
        if skipped:
            print(f"[INFO] {len(skipped)} collision candidate(s) retained unchanged.")
    if args.mode == "count":
        print(len(available))
        return
    if not available:
        print("[INFO] No reviewed PS1 RA collision requiring resolution")
        return
    for profile, operation in available:
        print("[RA CONFLICT]", profile, "extra:" if PROFILES[profile].get("archive_source") else "verified:", operation["source_cue"].name,
              "=>", operation["dest_cue"].name)
        print("[PRESERVE]", (operation["source_cue"] if PROFILES[profile].get("archive_source") else operation["dest_cue"]).name, "=>", operation["backup_cue"].name)
    if args.mode == "apply":
        if not args.journal:
            p.error("--journal required for apply")
        for profile, operation in available:
            target_journal = args.journal.with_name(args.journal.stem + "-" + profile + ".json")
            apply(args.root, args.hasher, target_journal,
                  (operation["verified_hash"], operation["unmatched_hash"]), profile, args.audit)
            print("[JOURNAL]", target_journal)
    else:
        print("PREVIEW ONLY: no files changed.")


if __name__ == "__main__":
    main()
