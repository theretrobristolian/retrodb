#!/usr/bin/env python3
"""Root-only RetroDB to RetroAchievements identity mapping (no passwords)."""
import argparse
import json
import os
import pwd
import grp
import re
from pathlib import Path

PATH = Path("/etc/retrodb/profile-links.json")
USERS = Path("/etc/retrodb/web-users.htpasswd")
VALID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    add = sub.add_parser("link", help="Approve a RetroDB -> RA account association")
    add.add_argument("retrodb_username")
    add.add_argument("ra_username")
    add.add_argument("--xerabora-profile", default="", help="Pre-existing xeRAbora profile approved for web switching")
    delete = sub.add_parser("unlink", help="Remove association")
    delete.add_argument("retrodb_username")
    sub.add_parser("list", help="List associations (no API credentials)")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run with sudo; account mappings are administrator controlled")
    try:
        data = json.loads(PATH.read_text())
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        parser.error("Existing profile-link file is invalid")
    if args.operation == "list":
        for local, ra in sorted(data.items()):
            print(f"{local}: {ra}")
        return
    if not VALID.fullmatch(args.retrodb_username):
        parser.error("Invalid RetroDB username")
    if args.operation == "link":
        if not VALID.fullmatch(args.ra_username):
            parser.error("Invalid RetroAchievements username")
        known = [x.split(":", 1)[0] for x in USERS.read_text().splitlines() if ":" in x]
        if args.retrodb_username not in known:
            parser.error("RetroDB username not found in htpasswd")
        if args.xerabora_profile and not VALID.fullmatch(args.xerabora_profile):
            parser.error("Invalid xeRAbora profile name")
        data[args.retrodb_username] = {"ra_username": args.ra_username}
        if args.xerabora_profile:
            data[args.retrodb_username]["xerabora_profile"] = args.xerabora_profile
    else:
        data.pop(args.retrodb_username, None)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = PATH.with_suffix(".json.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, sort_keys=True, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.chown(temp, 0, grp.getgrnam("retrodb").gr_gid)
        os.chmod(temp, 0o640)
        os.replace(temp, PATH)
    finally:
        if temp.exists():
            temp.unlink()
    print(f"[OK] RetroDB RA profile mapping {args.operation} completed.")

if __name__ == "__main__":
    main()
