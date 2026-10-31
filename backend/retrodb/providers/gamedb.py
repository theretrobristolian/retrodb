"""GameDB serial-to-title catalogue provider, shared across console platforms."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.request import Request, urlopen

SOURCES = {
    "playstation-2": ("PS2", "https://github.com/niemasd/GameDB-PS2/releases/latest/download/PS2.titles.json"),
    "playstation": ("PSX", "https://github.com/niemasd/GameDB-PSX/releases/latest/download/PSX.titles.json"),
    "playstation-3": ("PS3", "https://github.com/niemasd/GameDB-PS3/releases/latest/download/PS3.titles.json"),
}
CACHE_DAYS = 180
MAX_BYTES = 5 * 1024 * 1024
SERIAL = re.compile(r"^([A-Z]{4})[-_. ]?(\d{3})[-_. ]?(\d{2})$", re.I)
PS3_SERIAL = re.compile(r"^((?:BL|BC)[A-Z]{2})[-_. ]?(\d{5})$", re.I)


def normalise_serial(value: str) -> str:
    value = str(value).strip()
    ps3 = PS3_SERIAL.fullmatch(value)
    if ps3:
        return ps3[1].upper() + ps3[2]
    match = SERIAL.fullmatch(value)
    return f"{match[1].upper()}-{match[2]}{match[3]}" if match else ""


def parse_titles(payload: object) -> dict[str, str]:
    """GameDB's titles JSON maps serials to titles; discard ambiguous entries."""
    if not isinstance(payload, dict):
        raise ValueError("GameDB titles payload must be an object")
    titles: dict[str, str] = {}
    for key, value in payload.items():
        serial = normalise_serial(key)
        if not serial:
            continue
        if isinstance(value, str):
            title = value.strip()
        elif isinstance(value, dict) and isinstance(value.get("title"), str):
            title = value["title"].strip()
        elif isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
            title = value[0].strip()
        else:
            continue
        if title and len(title) < 256:
            titles[serial] = title
    if not titles:
        raise ValueError("GameDB catalogue contained no usable serial-title pairs")
    return titles


def cache_file(cache_dir: Path, platform: str) -> Path:
    if platform not in SOURCES:
        raise ValueError(f"Unsupported GameDB platform: {platform}")
    return cache_dir / f"{platform}.json"


def load(cache_dir: Path, platform: str) -> dict[str, str]:
    path = cache_file(cache_dir, platform)
    if not path.exists():
        return {}
    return parse_titles(json.loads(path.read_text(encoding="utf-8")))


def sync(cache_dir: Path, platform: str, force: bool = False) -> tuple[int, str]:
    path = cache_file(cache_dir, platform)
    if not force and path.is_file():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if age < timedelta(days=CACHE_DAYS):
            titles = load(cache_dir, platform)
            return len(titles), "cached"
    url = SOURCES[platform][1]
    try:
        with urlopen(Request(url, headers={"User-Agent": "RetroDB-GameDB/0.1"}), timeout=45) as response:
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("GameDB catalogue exceeds download limit")
        titles = parse_titles(json.loads(data.decode("utf-8-sig")))
        cache_dir.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".gamedb-", dir=cache_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return len(titles), "downloaded"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if path.exists():
            try:
                return len(load(cache_dir, platform)), "stale-cache (download failed)"
            except (OSError, ValueError):
                pass
        raise RuntimeError(f"Could not retrieve GameDB {platform} catalogue: {exc}") from exc

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Refresh the cached GameDB serial/title catalogue")
    parser.add_argument("--platform", choices=list(SOURCES), default="playstation-2")
    parser.add_argument("--cache-dir", type=Path, default=Path("/var/cache/retrodb/providers/gamedb"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    count, source = sync(args.cache_dir, args.platform, args.force)
    print(f"[OK] GameDB {args.platform}: {count} serial/title records ({source}).")
