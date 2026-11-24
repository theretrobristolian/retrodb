#!/usr/bin/env python3
"""Fetch GameTDB's optional English Wii disc-ID title table, cache-first.

Read-only external metadata. Never run commands or touch Wii disc files.
"""
from __future__ import annotations

import argparse
import os
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

URL = "https://www.gametdb.com/wiitdb.txt?LANG=EN"
LIMIT = 4 * 1024 * 1024
TTL = 30 * 86400


def refresh(path: Path, force: bool = False) -> tuple[int, str]:
    if not force and path.is_file() and time.time() - path.stat().st_mtime < TTL:
        return sum(1 for line in path.read_text(encoding="utf-8-sig").splitlines()
                   if " = " in line), "cached"
    try:
        request = Request(URL, headers={"User-Agent": "RetroDB/0.1 (Wii metadata cache)"})
        with urlopen(request, timeout=15) as response:
            endpoint = urlsplit(response.geturl())
            if endpoint.scheme != "https" or endpoint.hostname not in {"www.gametdb.com", "gametdb.com"}:
                raise ValueError("Unexpected GameTDB redirect")
            content = response.read(LIMIT + 1)
        if len(content) > LIMIT:
            raise ValueError("GameTDB catalogue exceeds configured size limit")
        text = content.decode("utf-8-sig")
        from report_wii_audit import ID
        found = {}
        for line in text.splitlines():
            if " = " not in line:
                continue
            key, title = line.split(" = ", 1)
            key, title = key.strip().upper(), title.strip()
            if ID.fullmatch(key) and 0 < len(title) <= 250:
                found[key] = title
        if len(found) < 100:
            raise ValueError("GameTDB title response was invalid or incomplete")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".wii-titles-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("TITLES = https://www.gametdb.com\n")
                for key, title in sorted(found.items()):
                    stream.write(f"{key} = {title}\n")
            os.chmod(name, 0o644)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return len(found), "downloaded"
    except (OSError, ValueError, UnicodeError) as exc:
        if path.is_file():
            return sum(1 for line in path.read_text(encoding="utf-8-sig").splitlines()
                       if " = " in line), "stale-cache fallback"
        raise RuntimeError("GameTDB unavailable; no changes made") from exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        count, source = refresh(args.output, args.force)
        print(f"[OK] Wii GameTDB titles: {count} IDs ({source})")
    except RuntimeError as exc:
        print(f"[WARN] {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
