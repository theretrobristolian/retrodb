#!/usr/bin/env python3
"""Read-only PS1 BIN/CUE audit and conservative filename proposals.

No network writes or renames. Pass the PS1 folder (not the RetroNAS share root).
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

CUE_FILE = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))\s+(BINARY|MOTOROLA|WAVE|AIFF|MP3)\s*$', re.I)
SERIAL = re.compile(r'(?<![A-Z0-9])((?:SCES|SCUS|SLES|SLUS|SLPS|SLPM|SCPS|SIPS|SCED|SLED|PAPX|PCPX|PBPX|SCZS)[-_ .]?[0-9]{3}[-_ .]?[0-9]{2})(?![0-9])', re.I)
BRACKET_ID = re.compile(r'\s*\[([A-Z]{4}[-_ .]?[0-9]{3}[-_ .]?[0-9]{2})\]', re.I)
DISC_SUFFIX = re.compile(r'\s*\((?:Disc|Disk|CD)\s*\d+\)', re.I)
BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def serial_from_name(name: str) -> str:
    match = SERIAL.search(name)
    if not match:
        return ""
    raw = re.sub(r'[^A-Z0-9]', '', match.group(1).upper())
    return raw[:4] + "-" + raw[4:]


def read_cue(path: Path) -> tuple[list[str], list[str]]:
    errors = []
    try:
        raw = path.read_bytes()
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp1252')
    except OSError as exc:
        return [], [f"CUE_UNREADABLE: {exc}"]
    refs = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().upper().startswith("FILE "):
            continue
        match = CUE_FILE.match(line)
        if match is None:
            errors.append(f"CUE_FILE_SYNTAX_LINE_{lineno}")
            continue
        ref = match.group(1) or match.group(2)
        refs.append(ref)
        if Path(ref).is_absolute() or ".." in Path(ref.replace("\\", "/")).parts or "/" in ref or "\\" in ref:
            errors.append(f"UNSAFE_REFERENCE_LINE_{lineno}")
    if not refs:
        errors.append("NO_FILE_REFERENCES")
    return refs, errors


def audit(root: Path) -> list[dict[str, str]]:
    rows = []
    cues = sorted(root.rglob("*.cue"), key=lambda p: str(p).casefold())
    cues += sorted((p for p in root.rglob("*.CUE") if p not in cues), key=lambda p: str(p).casefold())
    referenced = set()
    for cue in cues:
        if cue.is_symlink():
            continue
        refs, problems = read_cue(cue)
        resolved = []
        for ref in refs:
            target = cue.parent / ref
            if ref != Path(ref).name or Path(ref).is_absolute() or ".." in Path(ref.replace("\\", "/")).parts:
                continue
            if not target.is_file() or target.is_symlink():
                problems.append("MISSING_BIN:" + ref)
            else:
                resolved.append(target)
                referenced.add(target)
        if len(set(refs)) > 1:
            problems.append("MULTI_FILE_CUE")
        if len(refs) == 1 and not refs[0].casefold().endswith(".bin"):
            problems.append("NON_BIN_REFERENCE")
        stem = cue.stem
        serial = serial_from_name(stem)
        title = BRACKET_ID.sub("", stem)
        title = SERIAL.sub("", title).strip(" ._-")
        title = BAD_CHARS.sub(" ", title)
        title = " ".join(title.split())
        if not serial:
            problems.append("ID_MISSING_REVIEW")
        if not title:
            problems.append("TITLE_MISSING_REVIEW")
        proposed = f"{title} [{serial}]" if serial and title else ""
        cue_dest = cue.with_name(proposed + ".cue") if proposed else None
        bin_dest = cue.with_name(proposed + ".bin") if proposed else None
        if len(refs) == 1 and resolved and refs[0] != resolved[0].name:
            problems.append("REFERENCE_CASE_OR_NAME_MISMATCH")
        if proposed and (cue_dest != cue and cue_dest.exists() or bin_dest and resolved and bin_dest != resolved[0] and bin_dest.exists()):
            problems.append("DESTINATION_EXISTS")
        if len(refs) != 1:
            problems.append("MANUAL_REVIEW_TRACK_STRUCTURE")
        if len(resolved) == 1 and resolved[0].stem != cue.stem:
            problems.append("CUE_BIN_BASENAME_DIFFER")
        rows.append({
            "status": "REVIEW" if problems else ("RENAME_CANDIDATE" if proposed != cue.stem else "OK"),
            "relative_cue": cue.relative_to(root).as_posix(),
            "relative_bin": resolved[0].relative_to(root).as_posix() if len(resolved) == 1 else "",
            "disc_id_from_filename": serial,
            "file_references": " | ".join(refs),
            "file_count": str(len(set(refs))),
            "proposed_cue": cue_dest.relative_to(root).as_posix() if cue_dest else "",
            "proposed_bin": bin_dest.relative_to(root).as_posix() if bin_dest and len(refs) == 1 else "",
            "issues": " | ".join(dict.fromkeys(problems)),
        })
    for binfile in sorted(root.rglob("*"), key=lambda p: str(p).casefold()):
        if binfile.suffix.casefold() == ".bin" and binfile.is_file() and not binfile.is_symlink() and binfile not in referenced:
            rows.append({"status": "REVIEW", "relative_cue": "", "relative_bin": binfile.relative_to(root).as_posix(),
                         "disc_id_from_filename": serial_from_name(binfile.name), "file_references": "", "file_count": "1",
                         "proposed_cue": "", "proposed_bin": "", "issues": "ORPHAN_BIN_OR_CASE_MISMATCH"})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="PlayStation 1 directory")
    parser.add_argument("--output", required=True, type=Path, help="Local output CSV (outside source tree)")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    output = args.output.resolve()
    if not root.is_dir():
        parser.error("--root must be a directory")
    if output.is_relative_to(root):
        parser.error("CSV output must be outside the PlayStation 1 ROM directory")
    rows = audit(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["status", "relative_cue", "relative_bin", "disc_id_from_filename", "file_references", "file_count", "proposed_cue", "proposed_bin", "issues"]
    with output.open("w", newline="", encoding="utf-8-sig") as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"PS1 audit: {len(rows)} records -> {output}")
    print(" | ".join(f"{key}: {value}" for key, value in sorted(Counter(row["status"] for row in rows).items())))
    print("Read-only: no ROMs or CUE sheets were modified.")


if __name__ == "__main__":
    main()
