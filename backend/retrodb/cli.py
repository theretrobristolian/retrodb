"""Administrative command-line tasks for RetroDB."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from retrodb.providers.retroachievements import (
    RetroAchievementsClient,
    RetroAchievementsError,
    find_system,
)


TARGET_SYSTEMS = (
    ("playstation", ("PlayStation", "Sony PlayStation")),
    ("playstation-2", ("PlayStation 2", "Sony PlayStation 2")),
)


def load_environment_file(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RetroAchievementsError(f"Cannot read configuration file: {path}") from exc
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def make_client(cache_dir: Path) -> RetroAchievementsClient:
    return RetroAchievementsClient(
        os.getenv("RETRODB_RA_USERNAME", ""),
        os.getenv("RETRODB_RA_API_KEY", ""),
        cache_dir,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="RetroDB administration")
    parser.add_argument(
        "--env-file", type=Path, default=Path("/etc/retrodb/retrodb.env")
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("/var/cache/retrodb/providers/retroachievements"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("ra-test", help="test RetroAchievements credentials")
    sync_parser = subparsers.add_parser(
        "ra-sync", help="cache achievement-enabled PS1 and PS2 games and hashes"
    )
    sync_parser.add_argument("--force", action="store_true", help="ignore fresh cache")
    args = parser.parse_args()

    try:
        load_environment_file(args.env_file)
        client = make_client(args.cache_dir)
        if args.command == "ra-test":
            systems = client.test_connection()
            print(f"[OK] RetroAchievements connection successful ({systems} systems).")
            return 0

        systems = client.get_systems()
        print("[+] Synchronising RetroAchievements catalogues...")
        for slug, names in TARGET_SYSTEMS:
            system_id, system_name = find_system(systems, names)
            result = client.sync_system(
                system_id, system_name, slug, force=args.force
            )
            source = "cache" if result.from_cache else "downloaded"
            print(
                f"[OK] {system_name}: {result.games} games, "
                f"{result.hashes} hashes ({source})."
            )
        print("[+] RetroAchievements catalogue sync complete.")
        return 0
    except RetroAchievementsError as exc:
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
