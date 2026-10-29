#!/usr/bin/env python3
"""Read-only PS1 BIN/CUE audit and conservative filename proposals.

No network writes or renames. Pass the PS1 folder (not the RetroNAS share root).
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

CUE_FILE = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))\s+(BINARY|MOTOROLA|WAVE|AIFF|MP3)\s*$', re.I)
SERIAL = re.compile(r'(?<![A-Z0-9])((?:SCES|SCUS|SLES|SLUS|SLPS|SLPM|SCPS|SIPS|SCED|SLED|PAPX|PCPX|PBPX|SCZS)[-_ .]?[0-9]{3}[-_ .]?[0-9]{2})(?![0-9])', re.I)
BRACKET_ID = re.compile(r'\s*\[([A-Z]{4}[-_ .]?[0-9]{3}[-_ .]?[0-9]{2})\]', re.I)
DISC_SUFFIX = re.compile(r'\s*\((?:Disc|Disk|CD)\s*\d+\)', re.I)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from retrodb.providers.gamedb import load as load_gamedb

GAMEDB_CACHE = Path("/var/cache/retrodb/providers/gamedb")
BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def serial_from_name(name: str) -> str:
    match = SERIAL.search(name)
    if not match:
        return ""
    raw = re.sub(r'[^A-Z0-9]', '', match.group(1).upper())
    return raw[:4] + "-" + raw[4:]


# Explicitly reviewed disc labels; never infer disc order by filename sorting.
MULTIDISC_IDS = {
    "SLUS-00594": 1, "SLUS-00776": 2,  # Metal Gear Solid
    "SLUS-00544": 1, "SLUS-00556": 2,  # G-Police
    "SLUS-00710": 1, "SLUS-00731": 2,  # Abe's Exoddus
    "SLPS-01995": 1, "SLPS-01996": 2,  # Geppy-X (four discs)
    "SLPS-01997": 3, "SLPS-01998": 4,
    "SLUS-00920": 1, "SLUS-01056": 2,  # Fear Effect (USA)
    "SLUS-01057": 3, "SLUS-01058": 4,
    "SLUS-01266": 1, "SLUS-01275": 2,  # Fear Effect 2: Retro Helix (USA)
    "SLUS-01276": 3, "SLUS-01277": 4,
    "SLUS-01201": 1, "SLUS-01377": 2,  # Alone in the Dark: The New Nightmare (USA)
    "SLES-02801": 1, "SLES-12801": 2,  # UK / English
    "SLES-02802": 1, "SLES-12802": 2,  # French
    "SLES-02803": 1, "SLES-12803": 2,  # German
    "SLES-02804": 1, "SLES-12804": 2,  # Spanish
    "SLES-02805": 1, "SLES-12805": 2,  # Italian
}


def cleaned_ps1_title(stem: str) -> str:
    """Remove an ID and surrounding punctuation, including malformed brackets."""
    title = SERIAL.sub("", stem)
    # Removing the serial may leave empty or mismatched delimiters.
    title = re.sub(r"\[\s*\]|\{\s*\}|\(\s*\)", " ", title)
    title = title.rstrip(" ._-[]{}")  # Preserve meaningful suffixes such as (Disc 1) and (Claire)
    title = BAD_CHARS.sub(" ", title)
    return " ".join(title.split())


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



def disc_serial(binfile: Path) -> str:
    """Inspect ISO9660 SYSTEM.CNF inside a raw Mode 1/Mode 2 PS1 BIN."""
    try:
        with binfile.open("rb") as stream:
            for sector_size, data_offset in ((2352, 16), (2352, 24), (2048, 0)):
                stream.seek(16 * sector_size + data_offset)
                pvd = stream.read(2048)
                if len(pvd) != 2048 or pvd[0] != 1 or pvd[1:6] != b"CD001":
                    continue
                root = pvd[156:190]
                lba = int.from_bytes(root[2:6], "little")
                size = int.from_bytes(root[10:14], "little")
                if not 0 < lba < 1000000 or not 0 < size < 4 * 1024 * 1024:
                    continue
                stream.seek(lba * sector_size + data_offset)
                directory = stream.read(size)
                offset = 0
                while offset < len(directory):
                    length = directory[offset]
                    if not length:
                        offset = ((offset // 2048) + 1) * 2048
                        continue
                    entry = directory[offset:offset + length]
                    if len(entry) < 34:
                        break
                    count = entry[32]
                    filename = entry[33:33 + count].decode("ascii", "replace").upper().split(";")[0]
                    if filename == "SYSTEM.CNF":
                        start = int.from_bytes(entry[2:6], "little")
                        amount = int.from_bytes(entry[10:14], "little")
                        if not 0 < amount <= 65536:
                            return ""
                        stream.seek(start * sector_size + data_offset)
                        raw = stream.read(amount).decode("latin1", "replace")
                        match = SERIAL.search(raw)
                        if match:
                            return serial_from_name(match.group(1))
                        return ""
                    offset += length
    except (OSError, ValueError):
        pass
    return ""


def plan(root: Path, gamedb: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Generate a non-mutating, disc-level audit and conservative rename proposal."""
    rows = []
    gamedb = gamedb or {}
    referenced: set[Path] = set()
    cues = sorted((p for p in root.rglob("*") if p.suffix.lower() == ".cue" and not p.name.upper().startswith("OLD_") and p.is_file() and not p.is_symlink()), key=lambda p: str(p).casefold())
    for cue in cues:
        refs, issues = read_cue(cue)
        paths = []
        for ref in refs:
            if ref != Path(ref).name or Path(ref).is_absolute() or ".." in Path(ref.replace("\\", "/")).parts:
                continue
            target = cue.parent / ref
            if target.is_file() and not target.is_symlink():
                paths.append(target)
                referenced.add(target)
            else:
                issues.append("MISSING_REFERENCE:" + ref)
        if len(set(refs)) > 1:
            issues.append("MULTI_BIN_REVIEW")
        if len(refs) == 1 and not refs[0].lower().endswith(".bin"):
            issues.append("NON_BIN_REFERENCE")
        filename_serial = serial_from_name(cue.stem) or (serial_from_name(paths[0].stem) if len(paths) == 1 else "")
        internal_serial = disc_serial(paths[0]) if len(paths) == 1 and paths[0].suffix.lower() == ".bin" else ""
        if filename_serial and internal_serial and filename_serial != internal_serial:
            issues.append("DISC_ID_MISMATCH")
        selected_serial = internal_serial or filename_serial
        is_homebrew = bool(re.search(r"240p.?test.?suite", cue.stem, re.I))
        if not selected_serial and not is_homebrew:
            issues.append("ID_MISSING")
        catalogue_title = gamedb.get(selected_serial, "")
        if selected_serial == "SLES-03120":
            catalogue_title = "3, 2, 1, Smurf! My First Racing Game"
        # A catalogue serial match does not prove the image is that retail title.
        # Kula World has been observed proposing a PS One Kids demo title;
        # preserve the source and require manual disc identity review.
        if (re.search(r"\\bkula\\s+world\\b", cue.stem, re.I)
                and re.search(r"\\bps\\s*one\\s+kids\\b", catalogue_title, re.I)):
            issues.append("TITLE_IDENTITY_CONFLICT")
        title = cleaned_ps1_title(catalogue_title) if catalogue_title else cleaned_ps1_title(cue.stem)
        title = re.sub(r"\s*\((?:Rev(?:ision)?\s*\d+(?:\.\d+)?|v\d+(?:\.\d+)?)\)", "", title, flags=re.I).strip()
        # Preserve disc numbering already evidenced by this individual file even
        # if GameDB supplies the same plain title for every disc.
        file_disc = DISC_SUFFIX.search(cue.stem)
        if file_disc and not DISC_SUFFIX.search(title):
            title += " " + file_disc.group(0).strip()
        if selected_serial in MULTIDISC_IDS and not DISC_SUFFIX.search(title):
            title += f" (Disc {MULTIDISC_IDS[selected_serial]})"
        if not title:
            issues.append("TITLE_MISSING")
        proposed = f"{title} [{selected_serial}]" if title and selected_serial else (title if is_homebrew else "")
        dest_cue = cue.with_name(proposed + ".cue") if proposed else None
        dest_bin = cue.with_name(proposed + ".bin") if proposed and len(paths) == 1 else None
        if proposed and dest_cue != cue and dest_cue.exists() and dest_cue.samefile(cue) is False:
            issues.append("CUE_DESTINATION_EXISTS")
        if dest_bin and paths and dest_bin != paths[0] and dest_bin.exists() and dest_bin.samefile(paths[0]) is False:
            issues.append("BIN_DESTINATION_EXISTS")
        if cue.suffix != ".cue" or (len(paths) == 1 and paths[0].suffix != ".bin"):
            issues.append("EXTENSION_CASE_NORMALIZATION")
        if len(paths) == 1 and paths[0].stem != cue.stem:
            issues.append("BASENAME_MISMATCH")
        if not internal_serial and not is_homebrew:
            issues.append("INTERNAL_ID_UNVERIFIED")
        blockers = {"DISC_ID_MISMATCH", "MULTI_BIN_REVIEW", "NON_BIN_REFERENCE",
                    "ID_MISSING", "TITLE_MISSING", "CUE_DESTINATION_EXISTS",
                    "BIN_DESTINATION_EXISTS", "INTERNAL_ID_UNVERIFIED", "TITLE_IDENTITY_CONFLICT"}
        broken = any(x.startswith(("CUE_FILE_SYNTAX", "NO_FILE_REFERENCES", "MISSING_REFERENCE", "UNSAFE_REFERENCE", "CUE_UNREADABLE")) for x in issues)
        # This known RA-verified Metal Gear Solid Disc 1 release has a typo in
        # its filename (00694), while the on-disc boot ID is SLUS-00594.
        # The executor independently checks its exact RA hash before renaming.
        mgs_disc1 = (cue.name == "Metal Gear Solid [SLUS_006.94].cue"
                     and filename_serial == "SLUS-00694"
                     and internal_serial == "SLUS-00594"
                     and dest_cue is not None
                     and dest_cue.name == "Metal Gear Solid (Disc 1) [SLUS-00594].cue"
                     and dest_bin is not None
                     and dest_bin.name == "Metal Gear Solid (Disc 1) [SLUS-00594].bin")
        if mgs_disc1:
            blockers.discard("DISC_ID_MISMATCH")
        if len(refs) != 1 or len(paths) != 1:
            blockers.add("PAIR_NOT_SINGLE_BIN")
            issues.append("PAIR_NOT_SINGLE_BIN")
        status = "BROKEN" if broken else "REVIEW" if any(x in blockers for x in issues) else "WARNING" if issues else "VALID"
        if status in ("VALID", "WARNING") and all(x in ("EXTENSION_CASE_NORMALIZATION", "BASENAME_MISMATCH") or (mgs_disc1 and x == "DISC_ID_MISMATCH") for x in issues) and (cue.name != (dest_cue.name if dest_cue else "") or (paths and paths[0].name != (dest_bin.name if dest_bin else ""))):
            status = "RENAME_CANDIDATE"
        if status == "VALID" and dest_cue and dest_bin and paths and (dest_cue != cue or dest_bin != paths[0]):
            status = "RENAME_CANDIDATE"
        rows.append(dict(status=status, relative_cue=cue.relative_to(root).as_posix(),
                         relative_bin=paths[0].relative_to(root).as_posix() if len(paths) == 1 else "",
                         filename_serial=filename_serial, internal_serial=internal_serial,
                         selected_serial=selected_serial, gamedb_title=catalogue_title, homebrew="YES" if is_homebrew else "NO",
                         file_references=" | ".join(refs), file_count=str(len(set(refs))),
                         proposed_cue=dest_cue.relative_to(root).as_posix() if dest_cue else "",
                         proposed_bin=dest_bin.relative_to(root).as_posix() if dest_bin else "",
                         ra_compatibility="NOT_CHECKED", issues=" | ".join(dict.fromkeys(issues))))
    for binfile in sorted((p for p in root.rglob("*") if p.suffix.lower() == ".bin" and not p.name.upper().startswith("OLD_") and p.is_file() and not p.is_symlink() and p not in referenced), key=lambda p: str(p).casefold()):
        rows.append(dict(status="REVIEW", relative_cue="", relative_bin=binfile.relative_to(root).as_posix(),
                         filename_serial=serial_from_name(binfile.name), internal_serial=disc_serial(binfile),
                         selected_serial="", homebrew="NO", file_references="", file_count="1",
                         proposed_cue="", proposed_bin="", ra_compatibility="NOT_CHECKED", issues="ORPHAN_BIN"))
    return rows

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
    try:
        gamedb = load_gamedb(GAMEDB_CACHE, "playstation")
    except (ValueError, OSError) as exc:
        parser.error(f"GameDB PS1 cache invalid: {exc}")
    if not gamedb:
        parser.error("GameDB PS1 catalogue missing. Run RetroDB Audit games to synchronise it first.")
    rows = plan(root, gamedb)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["status", "relative_cue", "relative_bin", "filename_serial", "internal_serial", "selected_serial", "gamedb_title", "homebrew", "file_references", "file_count", "proposed_cue", "proposed_bin", "ra_compatibility", "issues"]
    with output.open("w", newline="", encoding="utf-8-sig") as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"PS1 audit: {len(rows)} records -> {output}")
    print(" | ".join(f"{key}: {value}" for key, value in sorted(Counter(row["status"] for row in rows).items())))
    print("Read-only: no ROMs or CUE sheets were modified.")


if __name__ == "__main__":
    main()
