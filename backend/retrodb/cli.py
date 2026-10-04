"""Administrative command-line tasks for RetroDB."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from sqlalchemy.orm import Session

from retrodb.database import get_engine
from retrodb.library import LibraryScanError, scan_retronas
from retrodb.retroachievements_match import MatchError, match_collection
from retrodb.retroachievements_patches import (
    PatchError,
    create_patch_plan,
    prepare_patch_sources,
)
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
    scan_parser = subparsers.add_parser("library-scan", help="inventory a read-only collection mount")
    scan_parser.add_argument("--root", type=Path, required=True)
    match_parser = subparsers.add_parser("ra-match", help="hash and match local disc images")
    match_parser.add_argument("--root", type=Path, required=True)
    match_parser.add_argument("--hasher", type=Path, default=Path("/opt/retrodb-tools/RAHasher"))
    match_parser.add_argument("--report", type=Path, default=Path("/var/lib/retrodb/reports/retroachievements-compatibility.csv"))
    for command, help_text in (
        ("patch-plan", "create patch manifests and per-game guidance"),
        ("patch-prepare", "inspect incoming patch source images"),
    ):
        patch_parser = subparsers.add_parser(command, help=help_text)
        patch_parser.add_argument("--root", type=Path, required=True)
        patch_parser.add_argument("--hasher", type=Path, default=Path("/opt/retrodb-tools/RAHasher"))
        patch_parser.add_argument("--report", type=Path, default=Path("/var/lib/retrodb/reports/retroachievements-compatibility.csv"))
        patch_parser.add_argument("--workspace", type=Path, default=Path("/var/lib/retrodb/patches"))
    args = parser.parse_args()

    try:
        load_environment_file(args.env_file)
        if args.command == "patch-plan":
            summary = create_patch_plan(args.report, args.cache_dir, args.workspace)
            print(f"[OK] Planned {summary.patches} RA-supported patches.")
            print(f"[+] Official patch links found: {summary.official_links}/{summary.patches}.")
            print(f"[+] Patch workspace: {summary.workspace}")
            print("[+] RetroNAS remained read-only; no ROMs or patches were modified.")
            return 0

        if args.command == "patch-prepare":
            summary = prepare_patch_sources(
                args.report, args.cache_dir, args.workspace, args.root, args.hasher
            )
            print(f"[OK] Checked sources for {summary.patches} RA-supported patches.")
            print(f"[+] Already patched and verified: {summary.already_verified}.")
            print(f"[+] Candidate sources needing patch README validation: {summary.candidates}.")
            print(f"[+] Missing sources: {summary.missing}.")
            print(f"[+] Details: {args.workspace / 'patch-prepare.json'}")
            return 0
        if args.command == "library-scan":
            print(f"[+] RetroNAS mount: {args.root.resolve()}")
            print("[+] Scanning configured collection paths read-only...")
            with Session(get_engine()) as session:
                result = scan_retronas(session, args.root)
            for platform in result.platforms:
                print()
                print(f"[{platform.label}]")
                print(f"  Path     : {platform.path}")
                if not platform.exists:
                    print("  Status   : path not found; not scanned")
                    continue
                gib = platform.bytes_total / (1024 ** 3)
                print(f"  Files    : {platform.files} ({gib:.2f} GiB)")
                if platform.folders:
                    print("  Folders  :")
                    for folder, count in sorted(platform.folders.items()):
                        folder_gib = platform.folder_bytes[folder] / (1024 ** 3)
                        print(f"    {folder}: {count} files ({folder_gib:.2f} GiB)")
                formats = ", ".join(
                    f"{name.upper()}={count}"
                    for name, count in sorted(platform.extensions.items())
                )
                print(f"  Formats  : {formats or 'none'}")
                skipped = ", ".join(
                    f"{name or '(none)'}={count}"
                    for name, count in sorted(platform.skipped_extensions.items())
                )
                skipped_count = sum(platform.skipped_extensions.values()) + platform.skipped_other
                print(f"  Skipped  : {skipped_count}" + (f" ({skipped})" if skipped else ""))
                print(
                    f"  Database : {platform.added} new, {platform.updated} changed, "
                    f"{platform.missing} newly missing"
                )
            total_gib = result.bytes_total / (1024 ** 3)
            print()
            print(f"[Total] {result.files} files ({total_gib:.2f} GiB)")
            print(
                f"[+] Database changes: {result.added} new, {result.updated} changed, "
                f"{result.missing} newly missing."
            )
            print("[+] Counts are files, not games; BIN/CUE pairs are reported separately.")
            return 0

        if args.command == "ra-match":
            print(f"[+] Collection mount: {args.root.resolve()}")
            print(f"[+] Hash engine: {args.hasher}")
            print("[+] Matching local disc images against cached RetroAchievements hashes...")
            with Session(get_engine()) as session:
                summaries = match_collection(
                    session, args.root.resolve(), args.hasher,
                    args.cache_dir, args.report, make_client(args.cache_dir),
                )
            total_candidates = total_matched = total_unmatched = total_failed = 0
            for summary in summaries:
                percentage = (summary.matched / summary.candidates * 100) if summary.candidates else 0
                print()
                print(f"[{summary.platform}]")
                print(f"  Disc images : {summary.candidates}")
                print(f"  Compatible  : {summary.matched} ({percentage:.1f}%)")
                print(f"  Unmatched   : {summary.unmatched}")
                print(f"  Failed      : {summary.failed}")
                print(f"  Cached      : {summary.cached}")
                print(f"  Suggestions : {summary.recommended}")
                total_candidates += summary.candidates
                total_matched += summary.matched
                total_unmatched += summary.unmatched
                total_failed += summary.failed
            percentage = (total_matched / total_candidates * 100) if total_candidates else 0
            print()
            print(f"[Total] {total_matched}/{total_candidates} compatible ({percentage:.1f}%)")
            print(f"[+] Unmatched: {total_unmatched}; hash failures: {total_failed}.")
            print(f"[+] Detailed CSV report: {args.report}")
            return 0

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
    except (RetroAchievementsError, LibraryScanError, MatchError, PatchError) as exc:
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
