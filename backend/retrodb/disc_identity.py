"""Read-only disc serial detection from ISO9660 SYSTEM.CNF (PS1 BIN/CUE and PS2 ISO)."""
from __future__ import annotations

import re
from pathlib import Path

BOOT = re.compile(rb"(?im)^\s*BOOT2?\s*=\s*(?:cdrom\d*:\\)?[^\r\n]*?([A-Z]{4})[_\-. ]?(\d{3})[_\-. ]?(\d{2})", re.I)
CUE_FILE = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))\s+BINARY\s*$', re.I)


def _system_cnf(path: Path, sector: int, offset: int) -> bytes:
    with path.open("rb") as fd:
        fd.seek(16 * sector + offset)
        pvd = fd.read(2048)
        if len(pvd) != 2048 or pvd[:1] != b"\x01" or pvd[1:6] != b"CD001":
            return b""
        root = pvd[156:190]
        lba = int.from_bytes(root[2:6], "little")
        size = int.from_bytes(root[10:14], "little")
        if not (0 < lba < 1000000 and 0 < size <= 1024 * 1024):
            return b""
        # Directory records can span sectors; skip 0-padding at sector boundaries.
        directory = bytearray()
        for index in range((size + 2047) // 2048):
            fd.seek((lba + index) * sector + offset)
            directory.extend(fd.read(2048))
        position = 0
        while position < min(len(directory), size):
            length = directory[position]
            if not length:
                position = (position // 2048 + 1) * 2048
                continue
            entry = directory[position:position + length]
            position += length
            if len(entry) < 34:
                continue
            name = entry[33:33 + entry[32]].upper().split(b";")[0]
            if name != b"SYSTEM.CNF":
                continue
            location = int.from_bytes(entry[2:6], "little")
            file_size = int.from_bytes(entry[10:14], "little")
            if not (0 < location < 1000000 and 0 < file_size < 65536):
                return b""
            data = bytearray()
            for index in range((file_size + 2047) // 2048):
                fd.seek((location + index) * sector + offset)
                data.extend(fd.read(min(2048, file_size - len(data))))
            return bytes(data)
    return b""


def internal_disc_serial(path: Path, platform_slug: str) -> str:
    """Best-effort identity hint; never claims a verified RetroAchievements hash."""
    try:
        if platform_slug == "playstation":
            cue = path.read_bytes()
            try:
                lines = cue.decode("utf-8-sig").splitlines()
            except UnicodeDecodeError:
                lines = cue.decode("cp1252").splitlines()
            refs = [m.group(1) or m.group(2) for line in lines if (m := CUE_FILE.fullmatch(line))]
            if len(refs) != 1 or Path(refs[0]).name != refs[0]:
                return ""
            image = path.parent / refs[0]
            if image.suffix.lower() != ".bin" or image.is_symlink():
                return ""
            layouts = ((2352, 16), (2352, 24))
        elif platform_slug == "playstation-2" and path.suffix.lower() == ".iso":
            image = path
            layouts = ((2048, 0), (2352, 16), (2352, 24))
        else:
            return ""
        for sector, offset in layouts:
            match = BOOT.search(_system_cnf(image, sector, offset))
            if match:
                return f"{match.group(1).decode().upper()}-{match.group(2).decode()}{match.group(3).decode()}"
    except (OSError, ValueError, UnicodeError):
        return ""
    return ""
