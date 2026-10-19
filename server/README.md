# Server build

This directory contains standalone Linux host provisioning for RetroDB.

## Supported targets

- Debian Stable — primary
- Ubuntu Server LTS — secondary

The bootstrap requires systemd and APT. RetroNAS follows the same broad Debian-family, Bash and Ansible model, keeping a future integration path straightforward.

## Prepare a minimal Debian installation

A minimal Debian installation may not include `sudo`. Become root, install it and add the normal administrator account to the `sudo` group. Replace `david` with the account created during installation when necessary:

```bash
su -c 'apt update && apt install -y sudo && /usr/sbin/usermod -aG sudo david'
su -c '/usr/sbin/reboot'
```

Reconnect so the new group membership applies, update the complete base OS, remove obsolete packages and reboot:

```bash
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove --purge -y
sudo reboot
```

Reconnect again before continuing.

## Installation sequence

Install Git, clone RetroDB and enter the repository:

```bash
sudo apt install -y git
git clone https://github.com/theretrobristolian/retrodb.git
cd retrodb
```

Run the read-only preflight first:

```bash
sudo bash server/build.sh --check
```

On a new Debian host, warnings about missing packages, the `retrodb` account and its directories are expected. Apply the build and then validate the finished state:

```bash
sudo bash server/build.sh
sudo bash server/build.sh --check
```

The final check should report that all base packages are installed, PostgreSQL is running, and no account or directory warnings remain.

The default run is idempotent: rerunning it restores required packages, accounts, directories, ownership and the PostgreSQL loopback setting.

## Output and diagnostics

Normal output is deliberately concise:

```text
[RUN] Installing base dependencies...
[OK]  Installing base dependencies
```

Underlying command output is captured. If a step fails, the step is marked `[FAILED]` and the captured diagnostic output is displayed automatically.

Use `--verbose` when live APT, PostgreSQL and system command output is needed:

```bash
sudo bash server/build.sh --verbose
```

`--check` remains read-only and can be combined with `--verbose`, although the check itself normally produces little underlying output.

## Application deployment

After the host bootstrap passes its check, deploy the application foundation:

```bash
git pull
sudo bash server/build.sh
sudo bash server/deploy.sh
```

The build step now includes `rsync`, which the deployment uses to copy the checked-out release into `/opt/retrodb`.

The deployment:

- generates a random PostgreSQL password when one does not already exist
- stores the database URL only in `/etc/retrodb/retrodb.env`
- creates the `retrodb` PostgreSQL role and database
- synchronises application files into `/opt/retrodb`
- creates an isolated Python virtual environment
- installs the pinned production dependencies
- applies Alembic migrations
- installs and starts the hardened systemd service
- calls the database-backed health endpoint

Normal output is concise. Add `--verbose` to display all underlying commands:

```bash
sudo bash server/deploy.sh --verbose
```

Validate the running service locally:

```bash
curl http://127.0.0.1:8000/live
curl http://127.0.0.1:8000/health
sudo systemctl status retrodb
```

The service deliberately binds only to loopback. LAN or guest access will be added later through a separately hardened HTTPS reverse proxy.

## RetroDB terminal manager

Run the standalone ASCII dashboard as your normal Debian user:

```bash
cd ~/retrodb
git pull --ff-only origin main
bash -n server/manager.sh
bash server/manager.sh
```

Its header shows RetroDB/PostgreSQL status, the RetroNAS mount, RAHasher, report availability and the xeRAbora service/Web UI. RetroDB currently provides a local API health endpoint at `http://127.0.0.1:8000/health`, **not a complete RetroDB browser frontend**.

The simplified menu focuses on three workflows:

- **1 — FULL AUDIT:** Seven clearly labelled stages: verify the RetroNAS mount and RAHasher, synchronise the RA catalogue (cache-aware), scan games, hash and match discs, generate a patch plan, download/reuse official patches and verify source checksums, then export the Excel workbook and raw CSV. The workflow stops on failed stages and **never modifies ROMs on RetroNAS**. The patch download stage may access the internet to fetch official patch packages.
- **2 — Download official patch packages:** Create/update the patch manifest and download/reuse official patch packages locally. No ROM patching occurs.
- **3 — Apply verified patches locally:** Requires typing `APPLY`, refreshes source checksum verification, and only applies patches to eligible clean images. Patched outputs are placed in `/var/lib/retrodb/patches/verified/` and validated using RAHasher. Review those outputs and copy them back to RetroNAS yourself; the original share remains read-only.
- **4 — Export latest Excel:** Rebuild Excel and copy raw CSV from the existing audit without scanning or downloading patches.
- **5 — Service/integration details:** Show RetroDB, xeRAbora and RetroNAS systemd status.

Run `bash server/manager.sh` for the menu, or `bash server/manager.sh audit`, `export`, `patches` or `patch-apply` directly.

The manager exports `~/retrodb-exports/RetroDB-Compatibility.xlsx` alongside the raw `retroachievements-compatibility.csv`. The Excel report has a **Summary** tab and separate **PlayStation 1** and **PlayStation 2** tabs. Console tabs are sorted by friendly game name and show the filename, disc ID, RA compatibility, a separate **Patchable** YES/NO field, clear issue/recommendation, RA game ID, recommended release, region and patch reference. The Summary tab separately totals verified RA-compatible games, confirmed patchable sources, other suggested ISO replacements, unknown games and hash errors. **RA compatible YES** means the existing ISO/disc image hash matches RA. **Patchable YES** requires a matching source entry in `/var/lib/retrodb/patches/patch-prepare.json` with state `clean-base-verified-ready-to-patch`, and the verified candidate must be the actual RetroNAS collection file, not a separately supplied incoming image. A mere patch URL or `rapatches` label does *not* qualify. Generate that verification with `sudo bash server/retronas.sh patch-plan`, `patch-download`, then `patch-prepare`. Re-run `patch-prepare` after changing any source files; the report reflects the *last preparation run*, not a new checksum test during Excel export. Patchability does not mean RA compatibility until the patched output passes RAHasher verification. It uses Python's standard library (no additional package installation). The export directory and files are private to the Linux account (directory `700`, files `600`), leaving the protected original in `/var/lib/retrodb/reports/` unchanged. It displays macOS/Linux and Windows PowerShell `scp` commands for downloading the CSV **from your computer**, outside the SSH session. The Excel workbook is the recommended download; the CSV is available when deeper technical troubleshooting is needed. Neither the audit nor the export modifies ROMs on RetroNAS.

Direct commands: `bash server/manager.sh status`, `bash server/manager.sh audit`, `bash server/manager.sh export`, `bash server/manager.sh patches`, `bash server/manager.sh patch-apply`.

## RetroAchievements credentials

The deployment adds a labelled RetroAchievements section to the protected configuration file:

```bash
sudo nano /etc/retrodb/retrodb.env
```

Enter only the account username and Web API key:

```text
RETRODB_RA_USERNAME=
RETRODB_RA_API_KEY=
```

See the [full credential setup guide](../docs/retroachievements-setup.md), including where to obtain the correct key and where redacted screenshots belong.

After saving the credentials and restarting RetroDB, test the connection and cache the achievement-enabled PlayStation and PlayStation 2 catalogues:

```bash
sudo bash server/retroachievements.sh test
sudo bash server/retroachievements.sh sync
```

The sync requests supported hashes and caches the response for 180 days. Use `sync --force` only for an intentional upstream refresh. Credentials are read from the protected file and are never placed on the command line or written to the cache.

## Security boundary

The bootstrap creates a non-login service user, protects configuration and data paths, and keeps PostgreSQL on loopback. It deliberately does not configure a firewall, mount collection shares, publish a port or place the application on the Internet.

Future work will add database creation, versioned application deployment, systemd units, migrations, health checks, backup/restore verification, reverse-proxy configuration and rollback handling.
