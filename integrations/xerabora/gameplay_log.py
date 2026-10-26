#!/usr/bin/env python3
"""Read-only, standalone xeRAbora gameplay monitor (Python standard library only)."""
import argparse
from collections import deque
from datetime import datetime, timedelta
import os
import re
import time
import json
from urllib.request import urlopen

STAMP = re.compile(r"^\s*(\d{2}:\d{2}:\d{2})\s")
NOISE = re.compile(r"http (?:get|post|put|delete) |console heartbeat:|\d+ snapshots\s*\||rx fifo", re.I)
EVENT = re.compile(
    r"achievement unlocked:|console acknowledged unlock notice|leaderboard|"
    r"console (?:found|connected|disconnected|lost|asked about)|"
    r"game (?:found|detected|identified|loaded|unsupported)|"
    r"achievements:|cannot unlock|pointer chain|unsupported|failed|error|"
    r"warning|timeout|unauthorized|wrong dump|no achievements|first complete snapshot",
    re.I,
)
UNLOCK = re.compile(r"achievement unlocked:\s*(.+)", re.I)
CONNECT = re.compile(r"console (?:connected|disconnected|lost)", re.I)
GAME = re.compile(r"(?:game (?:found|detected|identified|loaded):|game title:)\s*(.+)", re.I)


def event_lines(lines):
    """Yield gameplay events, retaining the descriptive line after an unlock."""
    description_pending = False
    for line in lines:
        line = line.rstrip("\n")
        if NOISE.search(line):
            continue
        if description_pending and line.strip():
            description_pending = False
            if not EVENT.search(line):
                yield line
                continue
        if EVENT.search(line):
            yield line
            description_pending = bool(UNLOCK.search(line))


def recent_lines(path, now):
    """Stream the entire log; timestamps have time-of-day but no date."""
    cutoff = now - timedelta(hours=1)
    with open(path, "r", errors="replace") as fh:
        for raw in fh:
            found = STAMP.match(raw)
            if not found:
                continue
            try:
                at = datetime.combine(now.date(), datetime.strptime(found.group(1), "%H:%M:%S").time(), now.tzinfo)
            except ValueError:
                continue
            # Handle the midnight boundary, but don't mistake later today for yesterday
            # except when today's timestamp would be in the future.
            if at > now + timedelta(seconds=5):
                at -= timedelta(days=1)
            if cutoff <= at <= now + timedelta(seconds=5):
                yield raw



def live_state():
    try:
        with urlopen("http://127.0.0.1:18280/state", timeout=2) as response:
            return json.load(response)
    except (OSError, ValueError, TimeoutError):
        return {}


def show_live_game(state):
    console = state.get("console") or {}
    game = state.get("game") or {}
    connected = bool(console.get("connected"))
    running = connected and not game.get("checked_only") and bool(game.get("id"))
    label = "Connected" if connected else "Not connected"
    print(f"Console now:   {label}")
    if running:
        print(f"Live game:     {game.get('title') or 'Unknown'} (RA ID {game['id']})")
        print("Compatibility: pointer-chain failures are counted by xeRAbora but their achievement IDs are not exposed by /state.")
    else:
        print("Live game:     None verified; awaiting console game data.")


def show_history(path, now, profile, service):
    recent = list(event_lines(recent_lines(path, now)))
    unlocks = [line for line in recent if UNLOCK.search(line)]
    connections = [line for line in recent if CONNECT.search(line)]
    games = [line for line in recent if GAME.search(line)]
    print("xeRAbora Gameplay Monitor")
    print("-" * 58)
    print(f"Service:       {service}")
    print(f"Player:        {profile}")
    show_live_game(live_state())
    print(f"Last link:     {connections[-1] if connections else 'No connection event in past hour'}")
    print(f"Last game:     {games[-1] if games else 'Not identified in past hour'}")
    print(f"Last unlock:   {unlocks[-1] if unlocks else 'None observed in past hour'}")
    print(f"Events:        {len(recent)} relevant log lines in past hour")
    print("-" * 58)
    print("Past hour's gameplay events:")
    if not recent:
        print("  (None observed; the monitor can still be connected and healthy.)")
    else:
        for line in recent:
            print(line)
    print("--- Listening for new events (Ctrl+C to return) ---", flush=True)


def follow(path):
    """Follow the file across simple log rotation, without changing it."""
    file = open(path, "r", errors="replace")
    try:
        file.seek(0, os.SEEK_END)
        desc_pending = False
        last_game = None
        next_poll = 0
        while True:
            if time.monotonic() >= next_poll:
                next_poll = time.monotonic() + 3
                state = live_state()
                game = state.get("game") or {}
                console = state.get("console") or {}
                current = (game.get("id"), game.get("title")) if console.get("connected") and game.get("id") and not game.get("checked_only") else None
                if current and current != last_game:
                    print(f"[LIVE GAME] {current[1] or 'Unknown'} (RA game ID {current[0]})", flush=True)
                    print("[LIMITATION] Pointer-chain achievement names are not exposed by xeRAbora.", flush=True)
                last_game = current
            line = file.readline()
            if line:
                clean = line.rstrip("\n")
                if NOISE.search(clean):
                    continue
                if desc_pending and clean.strip():
                    desc_pending = False
                    if not EVENT.search(clean):
                        print(clean, flush=True)
                        continue
                if EVENT.search(clean):
                    print(clean, flush=True)
                    desc_pending = bool(UNLOCK.search(clean))
                continue
            time.sleep(0.3)
            try:
                stat = os.stat(path)
            except FileNotFoundError:
                continue
            if stat.st_ino != os.fstat(file.fileno()).st_ino or stat.st_size < file.tell():
                file.close()
                file = open(path, "r", errors="replace")
    finally:
        file.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("log")
    parser.add_argument("profile")
    parser.add_argument("service")
    args = parser.parse_args()
    now = datetime.now().astimezone()
    show_history(args.log, now, args.profile, args.service)
    try:
        follow(args.log)
    except KeyboardInterrupt:
        print("\nReturning to manager.")


if __name__ == "__main__":
    main()
