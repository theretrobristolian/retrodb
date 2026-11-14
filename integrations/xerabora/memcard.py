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
import zipfile
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
        ftp.connect(d["host"], 21, timeout=120)
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
        os.chmod(dest, 0o600)
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
    try:
        venv.EnvBuilder(with_pip=True).create(env)
    except Exception as exc:
        if not shutil.which("apt-get") or not yes(
                f"Virtualenv creation failed ({exc}). Install python3-venv with apt?"):
            raise
        subprocess.run(["sudo", "apt-get", "update"], check=True)
        subprocess.run(["sudo", "apt-get", "install", "-y", "python3-venv"], check=True)
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


def release_identity(folder):
    """Identify a verified cached release; never infer ELF versions from names."""
    manifest = folder / "SHA256SUMS"
    if not manifest.is_file():
        return None
    expected = {}
    for line in manifest.read_text().splitlines():
        fields = line.split()
        if len(fields) == 2 and len(fields[0]) == 64:
            expected[fields[1].lstrip("*")] = fields[0].lower()
    names = ("OPL-RA.ELF", "OPL-RA-debug.ELF")
    if not any((folder / name).is_file() for name in names):
        return None
    for name in names:
        file = folder / name
        if file.is_file() and (name not in expected or digest(file) != expected[name]):
            return None
    return {name: digest(folder / name) for name in names if (folder / name).is_file()}


def describe_elfs(binaries, reference):
    """Always show exact hashes before deciding to modify any memory-card image."""
    print("\n===== SELECTED ELF SOURCE =====")
    for name, file in binaries.items():
        sha = digest(file)
        official = reference.get(name)
        state = "MATCHES VERIFIED UPSTREAM" if official == sha else (
            "DIFFERS FROM LATEST UPSTREAM" if official else "NO UPSTREAM REFERENCE")
        print(f"{name}: {file}\n  SHA-256: {sha}\n  {state}")


def image_elf_hashes(image):
    """Read-only extraction from a card image, without changing the image."""
    found = {}
    with tempfile.TemporaryDirectory(prefix="xerabora-card-inspect-") as tmp:
        for name in ("OPL-RA.ELF", "OPL-RA-debug.ELF"):
            dest = Path(tmp) / name
            result = subprocess.run(
                [mymc(), str(image), "extract", "-o", str(dest), "/APPS/" + name],
                capture_output=True, text=True, check=False,
            )
            if result.returncode == 0 and dest.is_file():
                found[name] = digest(dest)
            else:
                found[name] = None
    return found


def display_image_comparison(image, selected, reference):
    print(f"\n===== MEMORY CARD: {image} =====")
    found = image_elf_hashes(image)
    for name in ("OPL-RA.ELF", "OPL-RA-debug.ELF"):
        existing = found[name]
        expected = digest(selected[name]) if name in selected else None
        upstream = reference.get(name)
        label = ("MISSING" if existing is None else
                 "MATCHES SELECTED" if expected and existing == expected else
                 "MATCHES VERIFIED UPSTREAM" if upstream and existing == upstream else
                 "DIFFERENT / UNKNOWN VERSION")
        print(f"{name}: {label} ({existing or 'absent'})")
    return found


def current_release():
    """Fetch and verify the latest available release's ELF assets."""
    folder = download_release()
    ref = release_identity(folder)
    if not ref:
        raise RuntimeError(f"Could not validate release identity at {folder}")
    return folder, ref


def inspect_local():
    """Read-only status for installed and cached ELFs. Never touches the PS2."""
    folder, reference = current_release()
    print(f"\nLatest verified upstream: {folder.name}")
    installed_version = SOURCE_ELF / "VERSION"
    print(f"Installed server version marker: {installed_version.read_text().strip() if installed_version.is_file() else 'unknown'}")
    for name in ("OPL-RA.ELF", "OPL-RA-debug.ELF"):
        local = SOURCE_ELF / name
        if local.is_file():
            sha = digest(local)
            verdict = "CURRENT" if reference.get(name) == sha else "OUTDATED / UNRECOGNISED"
            print(f"{name} local: {verdict} ({sha})")
        else:
            print(f"{name} local: MISSING")
    print("\nCached release folders:")
    for directory in sorted(CACHE.iterdir()):
        if directory.is_dir() and directory.name.startswith("v") and directory != folder:
            verified = release_identity(directory)
            print(f"  {directory}: {'verified cached files' if verified else 'unverified cache'}")
    print("\nNo memory-card or server files have been modified.")


def cleanup_old_releases():
    """Remove only old verified release asset directories; never backups or images."""
    latest, _ = current_release()
    candidates = []
    for folder in CACHE.iterdir():
        if (not folder.is_dir() or folder.is_symlink() or folder == latest
                or not folder.name.startswith("v")):
            continue
        if not release_identity(folder):
            print(f"[KEEP] {folder}: cannot verify cached binaries")
            continue
        contents = list(folder.iterdir())
        allowed = {"SHA256SUMS", "OPL-RA.ELF", "OPL-RA-debug.ELF"}
        if not contents or any(item.is_symlink() or not item.is_file()
                               or item.name not in allowed for item in contents):
            print(f"[KEEP] {folder}: contains unexpected content")
            continue
        candidates.append(folder)
    print(f"\nLatest verified release retained: {latest.name}")
    print("Backup images, patched images, /opt/xerabora and custom files are NEVER deleted.")
    if not candidates:
        return print("[OK] No safe old release downloads to remove.")
    for folder in candidates:
        print(f"[CANDIDATE] {folder}")
    if input("Type CLEAN OLD RELEASES to delete ONLY these cached ELF folders: ").strip() != "CLEAN OLD RELEASES":
        return print("[CANCELLED] No changes.")
    for folder in candidates:
        for file in folder.iterdir():
            file.unlink()
        folder.rmdir()
        print(f"[REMOVED] {folder}")


def choose_elfs():
    upstream, reference = current_release()
    print(f"\nLatest verified upstream release: {upstream.name}")
    print("  1) Verified latest upstream ELFs (recommended)")
    print("  2) Locally installed /opt/xerabora binaries (may be older)")
    choice = ask("Choose", "1")
    if choice == "1":
        folder = upstream
    elif choice == "2":
        folder = SOURCE_ELF
    else:
        raise ValueError("Invalid ELF source")
    names = [n for n in ("OPL-RA.ELF", "OPL-RA-debug.ELF") if (folder / n).is_file()]
    if not names:
        raise FileNotFoundError(f"No ELF binaries found in {folder}")
    if "OPL-RA-debug.ELF" in names and not yes("Include debug ELF alongside regular OPL-RA?"):
        names.remove("OPL-RA-debug.ELF")
    binaries = {name: folder / name for name in names}
    describe_elfs(binaries, reference)
    stale = [name for name in names if digest(binaries[name]) != reference.get(name)]
    if stale:
        print("[WARNING] These files DO NOT MATCH latest upstream:", ", ".join(stale))
        if input("Type USE OLD BINARIES to proceed anyway: ").strip() != "USE OLD BINARIES":
            raise RuntimeError("Stopped to avoid accidentally installing older OPL-RA executables")
    return binaries, reference


def build_image(source, binaries, output):
    validate_image(source)
    # Shared/NFS destinations need their existing group/SMB permissions preserved.
    output.parent.mkdir(parents=True, exist_ok=True)
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


def offline_source(path):
    """Accept a local .mc2 or one valid card image from a user-downloaded ZIP."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() == ".mc2":
        validate_image(source)
        return source
    if source.suffix.lower() != ".zip":
        raise ValueError("Supply a .mc2 file or a locally downloaded .zip containing one")
    secure_dir(CACHE)
    with zipfile.ZipFile(source) as archive:
        candidates = [entry for entry in archive.infolist()
                      if not entry.is_dir() and entry.filename.lower().endswith(".mc2")
                      and 8 * 1024 * 1024 <= entry.file_size <= MAX_IMAGE
                      and entry.file_size % (1024 * 1024) == 0]
        if not candidates:
            raise RuntimeError("ZIP contains no .mc2 files of supported sizes")
        for n, entry in enumerate(candidates, 1):
            print(f"  {n}) {entry.filename} ({entry.file_size // (1024 * 1024)} MiB)")
        selected = int(ask("Choose source card", "1"))
        if selected not in range(1, len(candidates) + 1):
            raise ValueError("Invalid source card selection")
        entry = candidates[selected - 1]
        target = CACHE / f"offline-source-{timestamp()}.mc2"
        with archive.open(entry) as inp, target.open("xb") as out:
            shutil.copyfileobj(inp, out)
        validate_image(target)
        print(f"[OK] Extracted working source: {target}")
        return target


def make_offline():
    d = config()
    print("Download a Free McBoot template ZIP from your trusted source first.")
    print("The supplied Dropbox folder is not bundled or automatically downloaded.")
    supplied = ask("Path to local .mc2 or .zip template")
    source = offline_source(supplied)
    binaries, reference = choose_elfs()
    directory = Path(d.get("output_dir", str(CACHE / "output"))).expanduser()
    output = directory / f"{source.stem}-OPL-RA-{timestamp()}.mc2"
    display_image_comparison(source, binaries, reference)
    build_image(source, binaries, output)
    if yes("Allow other local/SMB users to read this patched image (chmod 0644)?"):
        output.chmod(0o644)
    print("[NEXT] Copy the patched .mc2 to your SD card using its device's documented")
    print("layout, or retrieve it from the configured share via SMB. No device was changed.")


def update_ftp():
    d = config()
    if not d.get("host"):
        return print("[STOP] Run Setup first.")
    binaries = choose_elfs()
    directory = Path(d.get("output_dir", str(CACHE / "output"))).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    private_backups = CACHE / "backups"
    secure_dir(private_backups)
    ftp = None
    try:
        ftp = ftp_connect(d)
        original = private_backups / f"MemCardPRO2-original-{timestamp()}.mc2"
        backup_remote(ftp, d, original)
        found = display_image_comparison(original, binaries, reference)
        if all(found.get(name) == digest(binary) for name, binary in binaries.items()):
            return print("[OK] Selected ELFs are already on the card. No new image or FTP upload needed.")
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
        second = private_backups / f"MemCardPRO2-before-write-{timestamp()}.mc2"
        backup_remote(ftp, d, second)
        if digest(second) != digest(original):
            raise RuntimeError("Remote card changed during preparation; refusing overwrite.")
        print("[UPLOAD] Transferring modified image (recovery backups preserved)")
        transfer(ftp, d["remote"], updated, upload=True)
        verification = private_backups / f"MemCardPRO2-readback-{timestamp()}.mc2"
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
        print("  7) Inspect installed and cached ELF versions (read only)")
        print("  8) Clean verified old release ELF downloads (confirmation)")
        print("  0) Back")
        choice = input("Choose: ").strip()
        try:
            if choice == "1": setup()
            elif choice == "2": install_deps()
            elif choice == "3": test_connection()
            elif choice == "4": print("[READY]", download_release())
            elif choice == "5": update_ftp()
            elif choice == "6": make_offline()
            elif choice == "7": inspect_local()
            elif choice == "8": cleanup_old_releases()
            elif choice == "0": return
            else: print("Invalid choice.")
        except (Exception, KeyboardInterrupt) as exc:
            print(f"\n[STOP] {exc}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="menu",
                        choices=["menu", "setup", "deps", "test", "download", "ftp", "offline", "inspect", "cleanup"])
    args = parser.parse_args()
    try:
        {"menu": menu, "setup": setup, "deps": install_deps, "test": test_connection,
         "download": download_release, "ftp": update_ftp, "offline": make_offline,
         "inspect": inspect_local, "cleanup": cleanup_old_releases}[args.command]()
    except (Exception, KeyboardInterrupt) as exc:
        print(f"[STOP] {exc}", file=sys.stderr)
        sys.exit(1)
