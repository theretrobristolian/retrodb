#!/usr/bin/env python3
"""One-off, evidence-gated Lost World PS1 cleanup. Archives, never deletes."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ps1_ra_conflict import ra_hash, verify_pair, rewritten

VERIFIED = "42db88df74ef4ea07ef0c575960a0934"
UNMATCHED = "b0bfe71d05db76cd85a650e04cb77703"
ACTIVE = "Lost World, The Jurassic Park [SLUS-00515]"
EXTRA = "Lost World, The - Jurassic Park - Special Edition (USA)"


def inspect(root, hasher):
    folder = root / "iso"
    active_cue, active_bin = (folder / (ACTIVE + ext) for ext in (".cue", ".bin"))
    extra_cue, extra_bin = (folder / (EXTRA + ext) for ext in (".cue", ".bin"))
    old_cue, old_bin = (folder / ("OLD_" + EXTRA + ext) for ext in (".cue", ".bin"))
    if any(p.is_symlink() or not p.is_file() for p in (active_cue, active_bin, extra_cue, extra_bin)):
        raise RuntimeError("Expected unsymlinked BIN/CUE pairs not present")
    if old_cue.exists() or old_bin.exists():
        raise RuntimeError("OLD_ destination exists; refusing overwrite")
    if len({str(p).casefold() for p in (active_cue, active_bin, extra_cue, extra_bin, old_cue, old_bin)}) != 6:
        raise RuntimeError("Case-folded path collision")
    verify_pair(active_cue, active_bin)
    original, encoding, lines, line = verify_pair(extra_cue, extra_bin)
    print("[VERIFY] Active RA-compatible game hash...", flush=True)
    if ra_hash(hasher, active_bin) != VERIFIED:
        raise RuntimeError("The canonical pair does not match RA 14615; refusing")
    print("[VERIFY] Extra Special Edition-labelled game hash...", flush=True)
    if ra_hash(hasher, extra_bin) != UNMATCHED:
        raise RuntimeError("Unexpected Special Edition source hash; refusing")
    return {"extra_cue": extra_cue, "extra_bin": extra_bin, "old_cue": old_cue,
            "old_bin": old_bin, "original": original, "updated": rewritten(lines, line, old_bin, encoding)}


def save(journal, record):
    temp = journal.with_suffix(".json.tmp")
    temp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(temp, journal)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("preview", "archive"))
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--hasher", type=Path, default=Path("/opt/retrodb-tools/RAHasher"))
    p.add_argument("--journal", type=Path)
    args = p.parse_args()
    details = inspect(args.root, args.hasher)
    print("[KEEP]", ACTIVE + ".cue/.bin", "(RA 14615, verified)", flush=True)
    print("[ARCHIVE]", EXTRA + ".cue/.bin", "-> OLD_ pair (unmatched)", flush=True)
    if args.mode == "preview":
        print("PREVIEW ONLY; no changes.")
        return
    if not args.journal:
        p.error("--journal required for archive")
    if args.journal.exists():
        raise RuntimeError("Existing journal; refusing overwrite")
    # Recheck hashes before writing, after user confirmation.
    details = inspect(args.root, args.hasher)
    args.journal.parent.mkdir(parents=True, exist_ok=True)
    record = {"operation": "lost-world-reviewed-archive",
              "created_utc": datetime.now(timezone.utc).isoformat(), "state": "pending",
              "paths": {k: str(v) for k, v in details.items() if isinstance(v, Path)},
              "original_cue_hex": details["original"].hex(),
              "expected_verified_hash": VERIFIED, "expected_unmatched_hash": UNMATCHED}
    save(args.journal, record)
    try:
        details["extra_bin"].rename(details["old_bin"])
        record["state"] = "bin_moved"
        save(args.journal, record)
        details["extra_cue"].rename(details["old_cue"])
        record["state"] = "cue_moved"
        save(args.journal, record)
        details["old_cue"].write_bytes(details["updated"])
        record["state"] = "cue_relinked"
        save(args.journal, record)
        verify_pair(details["old_cue"], details["old_bin"])
        if ra_hash(args.hasher, details["old_bin"]) != UNMATCHED:
            raise RuntimeError("Post-archive hash mismatch; inspect journal")
        record["state"] = "applied"
        save(args.journal, record)
        print("[OK] Verified canonical pair retained; unmatched source archived OLD_.")
    except Exception as exc:
        record["error"] = str(exc)
        save(args.journal, record)
        raise


if __name__ == "__main__":
    main()
