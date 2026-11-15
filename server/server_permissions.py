#!/usr/bin/env python3
"""Root-only terminal editor for RetroDB web server-management permissions.

Read usernames (never password hashes) from the web htpasswd file. Commit is
explicit and atomic; no edit is persisted by moving/toggling menu selections.
"""
from __future__ import annotations

import curses
import grp
import json
import os
import pwd
import re
import stat
import tempfile
from pathlib import Path

WEB_USERS = Path("/etc/retrodb/web-users-app.htpasswd")
ADMINS = Path("/etc/retrodb/server-admins.json")
VALID = re.compile(r"^[A-Za-z0-9_-]{1,48}$")


def web_usernames(path=WEB_USERS):
    users = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        name, _ = line.split(":", 1)
        if not VALID.fullmatch(name):
            raise ValueError("Invalid username in web account file")
        if name in users:
            raise ValueError("Duplicate username in web account file")
        users.add(name)
    return sorted(users, key=str.casefold)


def admin_usernames(path=ADMINS):
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or set(data) != {"admins"}
            or not isinstance(data["admins"], list)
            or any(not isinstance(u, str) or not VALID.fullmatch(u)
                   for u in data["admins"])
            or len(set(data["admins"])) != len(data["admins"])):
        raise ValueError("Invalid server administrator allowlist")
    return set(data["admins"])


def write_admins(selected, path=ADMINS):
    """Validate and atomically replace only the root-controlled allowlist."""
    if os.geteuid() != 0:
        raise PermissionError("Root privileges required")
    if any(not isinstance(u, str) or not VALID.fullmatch(u) for u in selected):
        raise ValueError("Invalid username selected")
    # Re-read live accounts and permissions before saving; don't grant access to
    # an account which was removed from htpasswd while the menu was open.
    current_users = set(web_usernames(WEB_USERS))
    if not set(selected).issubset(current_users):
        raise ValueError("Web accounts changed; reopen the permissions menu")
    current = admin_usernames(path)
    st = path.lstat() if path.exists() or path.is_symlink() else None
    if st and (not stat.S_ISREG(st.st_mode) or st.st_uid != 0):
        raise PermissionError("Refusing unsafe or non-root-owned permissions file")
    # This menu never deletes previously authorised accounts that have gone
    # missing from htpasswd. They remain unavailable while absent, and can be
    # reviewed when the account is restored.
    inactive = current - current_users
    updated = sorted(set(selected) | inactive, key=str.casefold)
    parent = path.parent
    directory = parent.stat()
    if directory.st_uid != 0 or directory.st_mode & 0o022:
        raise PermissionError("Permissions directory must be root-owned and not writable by others")
    group = grp.getgrnam("retrodb").gr_gid
    tmp = None
    try:
        fd, name = tempfile.mkstemp(prefix=".server-admins-", dir=str(parent))
        tmp = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchown(stream.fileno(), 0, group)
            os.fchmod(stream.fileno(), 0o640)
            json.dump({"admins": updated}, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return updated


def editor(stdscr, accounts, initially):
    curses.curs_set(0)
    stdscr.keypad(True)
    selected = set(initially) & set(accounts)
    initial = set(selected)
    position = 0
    offset = 0
    status = ""
    while True:
        rows, cols = stdscr.getmaxyx()
        stdscr.erase()
        if rows < 12 or cols < 47:
            stdscr.addnstr(0, 0, "Terminal too small (minimum 47x12).", max(1, cols - 1))
            stdscr.refresh()
            key = stdscr.getch()
            if key in (27, ord("q"), ord("Q")):
                return None
            continue

        def write(y, x, label, attr=0):
            if 0 <= y < rows and x < cols:
                stdscr.addnstr(y, x, label, max(0, cols - x - 1), attr)

        write(0, 2, "RetroDB | Permissions", curses.A_BOLD)
        write(1, 2, "Server management: restart xeRAbora / reboot Debian")
        write(2, 2, "Arrow keys: select   Space: toggle   Enter: choose")
        write(3, 2, "Only configured RetroDB website accounts appear.")
        list_start = 5
        visible = max(1, rows - 11)
        options = len(accounts) + 2
        position = min(position, options - 1)
        if position < len(accounts):
            if position < offset:
                offset = position
            if position >= offset + visible:
                offset = position - visible + 1
        for slot, username in enumerate(accounts[offset:offset + visible]):
            index = offset + slot
            marker = "x" if username in selected else " "
            text = f"  ({marker}) {username}"
            attr = curses.A_REVERSE if index == position else 0
            write(list_start + slot, 2, text, attr)
        write(rows - 6, 2, f"Accounts: {len(accounts)}   Selected: {len(selected)}   Changes: {'yes' if selected != initial else 'no'}")
        for index, text in enumerate(("Confirm / Update", "Cancel")):
            attr = curses.A_REVERSE | curses.A_BOLD if position == len(accounts) + index else curses.A_BOLD
            write(rows - 4 + index, 2, f"  {text}  ", attr)
        write(rows - 1, 2, status or "No changes are saved until Confirm / Update.")
        stdscr.refresh()
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            position = (position - 1) % options
        elif key in (curses.KEY_DOWN, ord("j")):
            position = (position + 1) % options
        elif key in (ord(" "),):
            if position < len(accounts):
                user = accounts[position]
                if user in selected:
                    selected.remove(user)
                else:
                    selected.add(user)
            else:
                status = "Select a username to toggle its permission."
        elif key in (10, 13, curses.KEY_ENTER):
            if position < len(accounts):
                user = accounts[position]
                if user in selected:
                    selected.remove(user)
                else:
                    selected.add(user)
            elif position == len(accounts) + 1:
                return None
            else:
                if selected == initial:
                    return None
                stdscr.erase()
                write(2, 2, "Apply server management permissions?", curses.A_BOLD)
                write(4, 2, "To add: " + (", ".join(sorted(selected - initial)) or "(none)"))
                write(5, 2, "To remove: " + (", ".join(sorted(initial - selected)) or "(none)"))
                write(7, 2, "Press Y to save, any other key to return.")
                stdscr.refresh()
                if stdscr.getch() in (ord("y"), ord("Y")):
                    return selected
                status = "Not saved."
        elif key in (27, ord("q"), ord("Q")):
            return None


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run via RetroDB's Permissions option (sudo is required).")
    accounts = web_usernames()
    current = admin_usernames()
    inactive = current - set(accounts)
    if not accounts:
        raise SystemExit("No RetroDB web accounts found. Configure a web login first.")
    try:
        selected = curses.wrapper(editor, accounts, current)
    except curses.error:
        raise SystemExit("Cannot open interactive terminal permissions menu.")
    if selected is None:
        print("[INFO] Permissions unchanged.")
        return
    write_admins(selected)
    print("[OK] Server management permissions updated.")
    if inactive:
        print("[INFO] Previously approved, currently absent web accounts were preserved:", ", ".join(sorted(inactive)))


if __name__ == "__main__":
    main()
