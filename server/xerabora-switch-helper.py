#!/usr/bin/env python3
"""Narrow root-owned unix socket service for activating configured xeRAbora players.

Only the retrodb service UID may connect. Only profiles explicitly approved in
/etc/retrodb/profile-links.json and holding cached xeRAbora credentials qualify.
No shell is invoked and no caller-controlled filesystem path is used.
"""
import grp
import json
import os
import pwd
import re
import socket
import struct
import subprocess
import tempfile
from pathlib import Path

LINKS = Path("/etc/retrodb/profile-links.json")
ACTIVE_SERVICE = "xerabora.service"
VALID = re.compile(r"^[A-Za-z0-9_-]{1,48}$")
DROP_DIR = Path("/etc/systemd/system/xerabora.service.d")
OVERRIDE = DROP_DIR / "profile.conf"
SOCKET_FD = 3

def command(*args):
    subprocess.run(args, check=True, timeout=35, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def execute_request(payload):
    if not isinstance(payload, dict) or set(payload) != {"account"}:
        raise ValueError("Invalid request")
    account = payload["account"]
    if not isinstance(account, str) or not VALID.fullmatch(account):
        raise ValueError("Invalid user")
    links = json.loads(LINKS.read_text(encoding="utf-8"))
    mapping = links.get(account) if isinstance(links, dict) else None
    if not isinstance(mapping, dict):
        raise ValueError("No authorised xeRAbora link")
    target = mapping.get("xerabora_profile")
    if not isinstance(target, str) or not VALID.fullmatch(target):
        raise ValueError("No approved xeRAbora player")
    service_user = subprocess.run(
        ["/usr/bin/systemctl", "show", "--property=User", "--value", ACTIVE_SERVICE],
        check=True, capture_output=True, text=True, timeout=8).stdout.strip()
    if not service_user or service_user == "root":
        raise ValueError("xeRAbora must run as an unprivileged service user")
    owner = pwd.getpwnam(service_user)
    home = Path(owner.pw_dir)
    profiles = home / ".config" / "xerabora-profiles"
    config = profiles / target
    cred = config / "xerabora" / "credentials"
    if config.is_symlink() or not config.is_dir() or not cred.is_file() or cred.is_symlink():
        raise ValueError("The approved player has no valid credentials")
    if config.stat().st_uid != owner.pw_uid or cred.stat().st_uid != owner.pw_uid:
        raise ValueError("Player directory ownership mismatch")
    current = profiles / "active"
    if current.is_file() and current.read_text(encoding="utf-8").strip() == target:
        return "Already active; no restart needed"
    new_value = "[Service]\nEnvironment=XDG_CONFIG_HOME=" + str(config) + "\n"
    # Write LAN preference to the selected profile like the existing xeRAbora
    # terminal switcher. Do not overwrite any existing unrelated credentials.
    lan_file = home / ".config" / "xerabora-server" / "lan"
    lan_enabled = "1" if lan_file.is_file() and lan_file.read_text().strip() == "1" else "0"
    lan_target = config / "xerabora" / "lan"
    if not lan_target.parent.is_dir() or lan_target.is_symlink():
        raise ValueError("Invalid profile config directory")
    fd = os.open(lan_target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(lan_enabled + "\n")
    os.chown(lan_target, owner.pw_uid, owner.pw_gid)
    os.chmod(lan_target, 0o600)

    old = OVERRIDE.read_bytes() if OVERRIDE.exists() else None
    DROP_DIR.mkdir(mode=0o755, parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=".profile-", dir=str(DROP_DIR))
    try:
        with os.fdopen(tmp_fd, "w") as out:
            out.write(new_value)
        os.chmod(tmp_path, 0o644)
        command("/usr/bin/systemctl", "stop", ACTIVE_SERVICE)
        os.replace(tmp_path, OVERRIDE)
        command("/usr/bin/systemctl", "daemon-reload")
        try:
            command("/usr/bin/systemctl", "start", ACTIVE_SERVICE)
            command("/usr/bin/systemctl", "is-active", "--quiet", ACTIVE_SERVICE)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if old is None:
                OVERRIDE.unlink(missing_ok=True)
            else:
                OVERRIDE.write_bytes(old)
                os.chmod(OVERRIDE, 0o644)
            command("/usr/bin/systemctl", "daemon-reload")
            command("/usr/bin/systemctl", "start", ACTIVE_SERVICE)
            raise RuntimeError("xeRAbora activation failed; previous configuration restored")
        fd, path = tempfile.mkstemp(prefix=".active-", dir=str(profiles))
        try:
            with os.fdopen(fd, "w") as out:
                out.write(target + "\n")
            os.chown(path, owner.pw_uid, owner.pw_gid)
            os.chmod(path, 0o600)
            os.replace(path, current)
        finally:
            if os.path.exists(path):
                os.unlink(path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return "Activated " + target + "; restart your PS2 / OPL-RA session"

def main():
    expected = pwd.getpwnam("retrodb").pw_uid
    server = socket.socket(fileno=SOCKET_FD)
    while True:
        conn, _ = server.accept()
        with conn:
            try:
                credentials = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                pid, uid, gid = struct.unpack("3i", credentials)
                if uid != expected:
                    raise PermissionError("Client not authorised")
                conn.settimeout(5)
                data = conn.recv(1024)
                if len(data) >= 1024:
                    raise ValueError("Request too large")
                outcome = execute_request(json.loads(data.decode("utf-8")))
                response = {"ok": True, "message": outcome}
            except (OSError, ValueError, KeyError, PermissionError, subprocess.CalledProcessError,
                    subprocess.TimeoutExpired, RuntimeError) as exc:
                response = {"ok": False, "message": "Unable to switch xeRAbora profile; check helper journal"}
                print("Switch denied/failed:", type(exc).__name__, str(exc), flush=True)
            conn.sendall(json.dumps(response).encode("utf-8"))

if __name__ == "__main__":
    main()
