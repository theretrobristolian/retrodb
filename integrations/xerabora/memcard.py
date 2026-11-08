#!/usr/bin/env python3
"""Manage PS2 .mc2 card images with mymc++ and optional MemCard PRO2 FTP.

Independent of RetroDB; uses only Python stdlib plus the mymcplusplus CLI.
No automatic upload, no modification of original source images.
"""
import argparse
from datetime import datetime, timezone
from ftplib import FTP
from getpass import getpass
from hashlib import sha256
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

APP = Path.home() / ".config" / "xerabora-memcard"
CONFIG = APP / "config.json"
CACHE = Path.home() / ".cache" / "xerabora-memcard"
SOURCE_ELF = Path("/opt/xerabora")
REMOTE = "/PS2/MemoryCard1/MemoryCard1-1.mc2"
MAX_IMAGE = 128 * 1024 * 1024
UA = {"User-Agent": "retrodb-community-memcard-manager", "Accept": "application/vnd.github+json"}


def secure_dir(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def save_config(data):
    secure_dir(APP)
    fd, tmp = tempfile.mkstemp(dir=APP, prefix=".config-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, CONFIG)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def config():
    if not CONFIG.exists():
        return {}
    if CONFIG.stat().st_mode & 0o077:
        raise RuntimeError(f"Unsafe credentials/config permissions: chmod 600 {CONFIG}")
    return json.loads(CONFIG.read_text())


def digest(path):
    h = sha256()
    with open(path, "rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def ask(label, default=""):
    value = input(f"{label} [{default}]: " if default else f"{label}: ").strip()
    return value or default


def yes(prompt):
    return input(f"{prompt} [y/N]: ").strip().lower() == "y"


def credentials():
    """Prefer OS Secret Service; never write FTP passwords in config or argv."""
    try:
        v = subprocess.run(
            ["secret-tool", "lookup", "application", "xerabora-memcard", "account", "ftp"],
            text=True, capture_output=True, timeout=8, check=False)
        if v.returncode == 0 and v.stdout.strip():
            return v.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return getpass("MemCard PRO2 FTP password (not saved): ")


def setup():
    d = config()
    d["host"] = ask("MemCard PRO2 address", d.get("host", ""))
    d["username"] = ask("FTP username", d.get("username", "ps2"))
    d["remote"] = ask("Remote default .mc2 file", d.get("remote", REMOTE))
    d["output_dir"] = ask("Local/share output directory", d.get("output_dir", str(CACHE / "output")))
    if not d["host"] or not d["username"] or not d["remote"].startswith("/PS2/") or not d["remote"].lower().endswith(".mc2"):
        raise ValueError("Host, FTP username, and an absolute /PS2/.../*.mc2 path required")
    save_config(d)
    print(f"[OK] Settings saved in {CONFIG} (0600). FTP password NOT saved to disk.")
    if shutil.which("secret-tool") and yes("Store password in system Secret Service keyring?"):
        password = getpass("FTP password: ")
        proc = subprocess.run(
            ["secret-tool", "store", "--label=xeRAbora MemCard PRO2 FTP",
             "application", "xerabora-memcard", "account", "ftp"],
            input=password, text=True, check=False)
        if proc.returncode:
            print("[WARN] Secret Service storage unavailable; future connections will prompt.")
    else:
        print("[INFO] FTP password will be requested each time.")


def trouble(exc):
    print(f"[ERROR] MemCard PRO2 FTP: {exc}")
    print("Check device IP/hostname, ensure no other FTP client is connected.")
    print("If port 21 refuses connections: toggle FTP off/on in MemCard PRO2 settings,")
    print("re-enter FTP username/password, press Save Credentials, then retry.")
    print("Use plain FTP in passive mode; this device may allow only one session.")


def ftp_connect(d):
    ftp = FTP()
    try:
        ftp.connect(d["host"], 21, timeout=25)
        print(f"[OK] FTP: {ftp.getwelcome()}")
        ftp.login(d["username"], credentials())
        ftp.set_pasv(True)
        return ftp
    except Exception:
        try:
            ftp.close()
        except Exception:
            pass
        raise


def test_connection():
    d = config()
    if not d.get("host"):
        return print("[STOP] Configure the MemCard PRO2 connection first.")
    try:
        ftp = ftp_connect(d)
        try:
            print("[OK] FTP login successful. Root listing:")
            ftp.retrlines("LIST")
        finally:
            ftp.close()
    except Exception as exc:
        trouble(exc)


def timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def transfer(ftp, remote, path, upload=False):
    total = path.stat().st_size if upload else 0
    done = 0
    last = -1
    def progress(chunk):
        nonlocal done, last
        done += len(chunk)
        # Progress without hundreds of terminal lines.
        tick = done // (512 * 1024)
        if tick != last:
            last = tick
            suffix = f"/{total:,}" if total else ""
            print(f"\r[FTP] {done:,}{suffix} bytes", end="", flush=True)
        if not upload:
            stream.write(chunk)
    if upload:
        with path.open("rb") as stream:
            ftp.storbinary(f"STOR {remote}", stream, blocksize=32768, callback=progress)
    else:
        with path.open("xb") as stream:
            ftp.retrbinary(f"RETR {remote}", progress, blocksize=32768)
    print()


def validate_image(path):
    size = path.stat().st_size
    if size < 8 * 1024 * 1024 or size > MAX_IMAGE or size % (1024 * 1024):
        raise ValueError(f"Unexpected memory-card image size: {size} bytes (8-128 MiB expected)")
    return size


def backup_remote(ftp, d, dest):
    dest = Path(dest)
    secure_dir(dest.parent)
    remote = d["remote"]
    print(f"[INFO] Downloading {remote} (read-only FTP)")
    try:
        transfer(ftp, remote, dest)
        validate_image(dest)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    print(f"[OK] Backup: {dest} ({digest(dest)})")
    return dest


def mymc():
    binary = Path.home() / "mymc-env" / "bin" / "mymcplusplus"
    if not binary.is_file():
        raise RuntimeError("mymcplusplus missing; select Install dependencies first")
    return str(binary)


def install_deps():
    import venv
    env = Path.home() / "mymc-env"
    binary = env / "bin" / "mymcplusplus"
    if binary.is_file():
        print(f"[OK] mymc++ already installed: {binary}")
        return
    if not yes("Create ~/mymc-env and install mymcplusplus from PyPI?"):
        return
    venv.EnvBuilder(with_pip=True).create(env)
    subprocess.run([str(env / "bin" / "python"), "-m", "pip",
                    "install", "mymcplusplus"], check=True)
    print(f"[OK] Installed {binary}")


def run_mymc(image, *args):
    command = [mymc(), str(image), *map(str, args)]
    subprocess.run(command, check=True)


def extract(image, item, destination):
    if destination.exists():
        raise FileExistsError(f"Won't overwrite extraction: {destination}")
    run_mymc(image, "extract", "-o", destination, "/APPS/" + item)
    if not destination.exists():
        raise RuntimeError(f"Extraction failed: {item}")


def download_release():
    """Fetch both ELFs when available and require matching upstream SHA256SUMS."""
    secure_dir(CACHE)
    req = urllib.request.Request(
        "https://api.github.com/repos/hacan359/xerabora/releases?per_page=30",
        headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        releases = json.load(r)
    release = next((x for x in releases if not x.get("draft") and
                    {"OPL-RA.ELF", "SHA256SUMS"} <=
                    {a["name"] for a in x.get("assets", [])}), None)
    if not release:
        raise RuntimeError("No upstream release with ELF and SHA256SUMS")
    assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
    version = release["tag_name"]
    destination = CACHE / version
    secure_dir(destination)
    names = ["SHA256SUMS", "OPL-RA.ELF"]
    if "OPL-RA-debug.ELF" in assets:
        names.append("OPL-RA-debug.ELF")
    for name in names:
        url = assets[name]
        file = destination / name
        if not file.is_file():
            print(f"[DOWNLOAD] {version}: {name}", flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
            with urllib.request.urlopen(req, timeout=90) as r, file.open("wb") as out:
                shutil.copyfileobj(r, out)
    checksums = {}
    for line in (destination / "SHA256SUMS").read_text().splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and len(parts[0]) == 64:
            checksums[parts[1].lstrip("*")] = parts[0].lower()
    for name in names[1:]:
        if name not in checksums or digest(destination / name) != checksums[name]:
            (destination / name).unlink(missing_ok=True)
            raise RuntimeError(f"Missing/mismatched upstream checksum: {name}")
        print(f"[OK] {name} checksum verified")
    if "OPL-RA-debug.ELF" not in names:
        print("[NOTE] Upstream release does not include a debug ELF.")
    return destination


def choose_elfs():
    local = SOURCE_ELF / "OPL-RA.ELF"
    print("  1) Fetch verified normal + debug ELF from latest upstream release")
    print("  2) Use locally installed /opt/xerabora binaries")
    choice = ask("Choose", "1")
    if choice == "1":
        folder = download_release()
    elif choice == "2":
        folder = SOURCE_ELF
    else:
        raise ValueError("Invalid ELF source")
    names = [n for n in ("OPL-RA.ELF", "OPL-RA-debug.ELF") if (folder / n).is_file()]
    if not names:
        raise FileNotFoundError(f"No ELF binaries found in {folder}")
    if "OPL-RA-debug.ELF" in names and not yes("Include debug ELF alongside regular OPL-RA?"):
        names.remove("OPL-RA-debug.ELF")
    return {name: folder / name for name in names}


def build_image(source, binaries, output):
    validate_image(source)
    secure_dir(output.parent)
    if output.exists():
        raise FileExistsError(f"Output already exists; not overwriting: {output}")
    shutil.copy2(source, output)
    try:
        print("[INFO] Patching working image only, preserving source.")
        for name, binary in binaries.items():
            current = output.parent / f".{name}-{timestamp()}-before"
            try:
                extract(output, name, current)
                if digest(current) == digest(binary):
                    print(f"[SKIP] {name} already matches")
                    continue
                run_mymc(output, "remove", f"/APPS/{name}")
            except subprocess.CalledProcessError:
                print(f"[INFO] {name} not present, adding to /APPS/")
            finally:
                current.unlink(missing_ok=True)
            run_mymc(output, "add", "-d", "/APPS", binary)
            copied = output.parent / f".{name}-{timestamp()}-verify"
            try:
                extract(output, name, copied)
                if digest(copied) != digest(binary):
                    raise RuntimeError(f"ELF verification failed: {name}")
            finally:
                copied.unlink(missing_ok=True)
            print(f"[OK] {name}: SHA-256 verified within card image")
        run_mymc(output, "check")
        if validate_image(output) != validate_image(source):
            raise RuntimeError("Memory card image size changed")
        print(f"[READY] {output} (SHA256 {digest(output)})")
        return output
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def make_offline():
    d = config()
    supplied = ask("Path to original .mc2 image (e.g. extracted Free McBoot 8 MiB image)")
    source = Path(supplied).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".mc2":
        raise ValueError("Supply an existing .mc2 image, not a ZIP archive")
    binaries = choose_elfs()
    directory = Path(d.get("output_dir", str(CACHE / "output"))).expanduser()
    output = directory / f"{source.stem}-OPL-RA-{timestamp()}.mc2"
    build_image(source, binaries, output)
    print("[NEXT] Copy the patched .mc2 to your SD card using its device's documented")
    print("layout, or retrieve it from the configured share via SMB. No device was changed.")


def update_ftp():
    d = config()
    if not d.get("host"):
        return print("[STOP] Run Setup first.")
    binaries = choose_elfs()
    directory = Path(d.get("output_dir", str(CACHE / "output"))).expanduser()
    secure_dir(directory)
    ftp = None
    try:
        ftp = ftp_connect(d)
        original = directory / f"MemCardPRO2-original-{timestamp()}.mc2"
        backup_remote(ftp, d, original)
        updated = directory / f"MemCardPRO2-patched-{timestamp()}.mc2"
        build_image(original, binaries, updated)
        if digest(original) == digest(updated):
            return print("[OK] Image unchanged; upload unnecessary.")
        print(f"Remote: {d['host']}:{d['remote']}")
        print(f"Original backup: {original}")
        print(f"Updated image:   {updated}")
        print("[WARNING] Never upload while a game/save operation is active.")
        print("PS2 dashboard alone may not guarantee the current image is unmounted.")
        print("Confirm the card is idle or switched away. Upload is not atomic.")
        if input("Type UPLOAD to replace the selected remote card: ").strip() != "UPLOAD":
            return print("[CANCELLED] No upload.")
        # Detect remote changes between initial backup and write.
        second = directory / f"MemCardPRO2-before-write-{timestamp()}.mc2"
        backup_remote(ftp, d, second)
        if digest(second) != digest(original):
            raise RuntimeError("Remote card changed during preparation; refusing overwrite.")
        print("[UPLOAD] Transferring modified image (recovery backups preserved)")
        transfer(ftp, d["remote"], updated, upload=True)
        verification = directory / f"MemCardPRO2-readback-{timestamp()}.mc2"
        backup_remote(ftp, d, verification)
        if digest(verification) != digest(updated):
            raise RuntimeError("REMOTE READBACK HASH MISMATCH. Restore original from backup.")
        print("[SUCCESS] Remote image verified. Reload/remount card or restart PS2.")
    except Exception as exc:
        trouble(exc)
    finally:
        if ftp:
            ftp.close()


def menu():
    while True:
        print("\nxeRAbora — PS2 memory-card / OPL-RA manager")
        print("  1) Setup MemCard PRO2 FTP and output path")
        print("  2) Install/check mymc++ dependencies")
        print("  3) Test MemCard PRO2 FTP (read-only)")
        print("  4) Download & verify latest normal/debug OPL-RA ELFs")
        print("  5) Update MemCard PRO2 default card over FTP (backup and confirmation)")
        print("  6) Patch a local .mc2 image for SD card / SMB distribution")
        print("  0) Back")
        choice = input("Choose: ").strip()
        try:
            if choice == "1": setup()
            elif choice == "2": install_deps()
            elif choice == "3": test_connection()
            elif choice == "4": print("[READY]", download_release())
            elif choice == "5": update_ftp()
            elif choice == "6": make_offline()
            elif choice == "0": return
            else: print("Invalid choice.")
        except (Exception, KeyboardInterrupt) as exc:
            print(f"\n[STOP] {exc}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="menu",
                        choices=["menu", "setup", "deps", "test", "download", "ftp", "offline"])
    args = parser.parse_args()
    try:
        {"menu": menu, "setup": setup, "deps": install_deps, "test": test_connection,
         "download": download_release, "ftp": update_ftp, "offline": make_offline}[args.command]()
    except (Exception, KeyboardInterrupt) as exc:
        print(f"[STOP] {exc}", file=sys.stderr)
        sys.exit(1)
