# RetroDB

RetroDB is an open-source, self-hosted catalogue and browser for retro-game collections.

The long-term aim is a fast, secure web front end for a physical game room or private collection: closer to **Plex for locally stored games** than a launcher or ROM-distribution service. It will catalogue what is available, explain how to use each console, and present curated game lists through tablets, phones and QR codes.

> **Project status (October 2026):** working self-hosted backend, PostgreSQL/API health endpoints, read-only PS1/PS2 RetroNAS inventory, RetroAchievements hash audits, GameDB title matching, formatted Excel reports, OPL filename management, and checksum-verified official PS2 patch deployment. The planned polished browsing/guest web application is **not yet complete**.

## Vision

RetroDB should eventually:

- catalogue games across many platforms without using console-specific database tables
- distinguish a game from its regional releases, discs and dump/media variants
- map identifiers from sources such as RetroAchievements, Redump, No-Intro, OPL and PSBBN
- record developers, publishers, release dates, regions, languages and historical age ratings
- store external review scores separately from personal ratings and curated collections
- identify locally available files without committing games, ROMs, disc images or copyrighted artwork
- show cover art, synopses, controls, manuals and collection availability
- document physical console instances, modifications, controllers and reset/menu shortcuts
- support child-appropriate and owner-approved collections through a separate policy layer
- provide read-only guest pages suitable for QR codes and a front-desk kiosk
- integrate with an existing RetroNAS installation or run on a separate Linux server
- later provide safe tools for building curated storage media and backing up compatible save devices

The initial reference platforms are **PlayStation and PlayStation 2**, but the data model and provider interfaces will be platform-neutral.

## Guiding principles

### The database is the source of truth

PostgreSQL will store structured metadata and relationships. Large files such as artwork, manuals, metadata snapshots and local game files remain on storage; the database records their location and integrity information.

### One model for every platform

RetroDB will use relationships such as:

```text
Game
└── Release (platform, region, language, edition)
    └── Media (disc, serial, product code, hashes)
        └── Library item (local storage path and availability)
```

Platforms are data, not separate schemas or tables.

### Providers are replaceable

Every upstream source will have its own adapter and follow the same broad pipeline:

```text
fetch → validate → cache → normalise → import
```

Application code should not depend directly on one provider's API or data format.

### Cache responsibly

RetroAchievements and similar community services must not be repeatedly queried during development or ordinary browsing.

RetroDB will keep:

1. an immutable raw response cache
2. a normalised, provider-independent snapshot
3. the local PostgreSQL representation

Normal refreshes should be infrequent—initially every six months for largely static metadata—with manual refresh available. Tests and normal development must use fixtures and never contact upstream services by default.

Cached third-party datasets will not be redistributed until their licences and redistribution permissions have been confirmed.

### Secure by design

- PostgreSQL is local/private-network only and is never published directly.
- Public collection pages are read-only.
- Administration is a separate authenticated surface intended for a trusted network.
- Secrets live outside Git and receive restrictive permissions.
- The application runs as an unprivileged service account.
- RetroDB does not make RetroNAS's legacy protocols safe; a RetroNAS host must remain behind a firewall on a private network.
- No installer will silently expose an Internet-facing service.

## Intended architecture

```text
Browser / kiosk / QR link
          │ HTTPS
          ▼
     Reverse proxy
          │
          ▼
  RetroDB web + API
          │
          ├── PostgreSQL
          ├── background workers
          └── local/NAS storage
                ├── artwork
                ├── manuals
                ├── provider cache
                └── collection files
```

The planned application stack is:

- **Operating system:** Debian Stable (primary), Ubuntu Server LTS (secondary)
- **Database:** PostgreSQL
- **Backend/API:** Python and FastAPI
- **Web UI:** server-rendered templates with lightweight progressive enhancement
- **Service management:** systemd
- **Provisioning:** idempotent Bash bootstrap initially; Ansible role for RetroNAS integration later
- **Reverse proxy:** to be selected and hardened before the first web release

## Why Debian Stable?

RetroNAS currently uses Bash, APT, Ansible and systemd-oriented services. Debian Stable therefore provides the closest standalone development target and the least-friction route to a future RetroNAS installer.

Ubuntu Server LTS remains a sensible VM test platform and will be supported where practical, but RetroDB will avoid becoming Ubuntu-specific.

## Deployment models

### Standalone

RetroDB runs on its own Debian/Ubuntu VM or small server and reads collection storage through a deliberately configured mount. This is the recommended development and security model.

### Alongside RetroNAS

For smaller private home networks, RetroDB may run on the RetroNAS host and use its storage paths directly. The application must still use an unprivileged account, a local database connection and explicit network boundaries.

### Future RetroNAS component

Once the standalone application is mature, `deployment/retronas/` will contain an Ansible role or installer suitable for review and potential integration with RetroNAS. RetroDB will not be built tightly inside RetroNAS first.

## Server build

The starter build script is at:

```text
server/build.sh
```

### Debian host preparation

A minimal Debian installation may not include `sudo`. Sign in with the normal account created during setup, become root, then install `sudo` and grant that account administrative access. Replace `david` if a different username was created:

```bash
su -c 'apt update && apt install -y sudo && /usr/sbin/usermod -aG sudo david'
su -c '/usr/sbin/reboot'
```

Reconnect after the reboot, then fully update the base operating system:

```bash
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove --purge -y
sudo reboot
```

Reconnect once more before installing RetroDB.

On a fresh test VM:

```bash
sudo apt install -y git
git clone https://github.com/theretrobristolian/retrodb.git
cd retrodb

sudo bash server/build.sh --check
sudo bash server/build.sh
sudo bash server/build.sh --check
```

The first check is read-only. Missing package, service-account and directory warnings are expected on an unprepared host. The build applies the configuration, and the final check verifies that the machine reached the intended state.

The script is designed to be safely rerun. At this stage it:

- supports Debian and Ubuntu through APT
- validates that systemd is available
- installs the initial OS dependencies
- creates an unprivileged `retrodb` service account
- creates application, configuration, data, cache, log and backup directories
- applies restrictive ownership and permissions
- configures PostgreSQL to listen only on loopback
- enables and validates PostgreSQL
- reports what it changed and what remains unimplemented

Normal output shows concise `[RUN]` and `[OK]` status lines. Underlying command output is captured and displayed automatically when a step fails. For live diagnostic output, run:

```bash
sudo bash server/build.sh --verbose
```

The host bootstrap prepares the operating system but does not expose a website. Once its check passes, deploy the v0.1 application foundation:

```bash
git pull
sudo bash server/build.sh
sudo bash server/deploy.sh
```

The deployment creates the local PostgreSQL role/database, generates protected credentials outside Git, installs the Python environment, applies migrations, starts the hardened systemd service and validates:

```text
http://127.0.0.1:8000/live
http://127.0.0.1:8000/health
```

The application remains loopback-only until an HTTPS reverse proxy and explicit LAN access policy are added.

## Configure RetroAchievements

RetroAchievements credentials are stored only in the protected server file:

```text
/etc/retrodb/retrodb.env
```

The deployment creates a clearly labelled section for the username and **Web API key**. Follow the [RetroAchievements setup guide](docs/retroachievements-setup.md) to obtain the correct key and enter it safely.

Do not put a real API key in Git, screenshots, issues or support messages.

## Connect a RetroNAS collection

RetroDB mounts the standard RetroNAS SMB share read-only for PS1/PS2 inventory and RetroAchievements audits. Explicitly confirmed OPL renames and PS2 patch deployment use a **separate temporary writable SMB mount**, never changing the default read-only audit mount. Follow the [RetroNAS scanning guide](docs/retronas-scanning.md). Credentials remain root-only and collection files are never modified.

### Launch the menus from anywhere

Run this **once** from your checkout as your normal user (it asks for sudo only to write into `/usr/local/bin`):

```bash
cd ~/retrodb
git pull --ff-only origin main
bash server/install-launchers.sh
```

Then from any directory, type `retrodb` for the collection manager or `xerabora` / `xeRAbora` for the xeRAbora installer/profile manager. Arguments are forwarded to the underlying scripts (e.g. `retrodb audit`, `xerabora status`). Both commands use your **current shell user's profile and HOME**, not root's; don't prefix them with `sudo`. The wrappers target this checkout and stay current as you `git pull`. If you move the checkout to a new path, rerun the installer.

Fresh installs now register command-line shortcuts automatically: the RetroDB deployment installs `retrodb` and prints how to launch the menu, while the xeRAbora installer registers `xerabora` / `xeRAbora`. You can still rerun `bash server/install-launchers.sh` manually.

The streamlined RetroDB main menu includes **Audit game collection**, **Patch a PS2 game**, **Rename PS2 games**, and **More options**. The submenu houses export-only reports, local patch downloads, service status and operation journals. Export-only is useful to regenerate a workbook or proposals from an existing audit; it never scans or refreshes hashes. 

**Automatic updates on menu launch:** Typing `retrodb` checks the trusted project's `origin/main` and fast-forwards the repository before showing the menu, if the tracked working tree is clean and the checkout is on `main`. A timeout, offline GitHub connection, local modifications or diverged branch **never causes a forced reset**; RetroDB opens the already-installed menu and prints a warning. Only the interactive menu triggers this check; `retrodb audit` and other non-menu commands do not. This updates checked-out menu/scripts, **not** the deployed backend service under `/opt/retrodb`, which still requires `sudo bash server/deploy.sh` after backend changes. For existing installations, first run `cd ~/retrodb && git pull --ff-only origin main` once to install the new auto-update logic.

### Maintenance from the RetroDB menu

In **More options**, select **6 — Update RetroDB** for a complete, explicitly confirmed application update. It validates the trusted GitHub checkout, pulls clean `main` changes via fast-forward, checks/repairs the required host dependencies when necessary, runs `server/deploy.sh` (including database migrations and a controlled service restart), and validates the health endpoint. The updater does not patch game images, rename ROMs or update xeRAbora itself. The launch-time updater still refreshes only menu/source scripts and never restarts services without confirmation.

Select **7 — Upgrade Debian** for host operating-system maintenance. This refreshes APT metadata, displays a `full-upgrade` **simulation**, requires typing `UPGRADE SYSTEM`, and then runs the actual package upgrade. It does not reboot or autoremove automatically; a required reboot is reported for manual scheduling. System upgrades can interrupt other services, so review the preview and perform them during a maintenance window.

These actions are distinct: the first updates the RetroDB application and its service; the second updates the Debian/Ubuntu host's packages. Both are implemented in `server/maintenance.sh`, and neither runs just because you opened the menu.

### Cross-platform Action Required report

The standard `RetroDB-Compatibility.xlsx` now has an **Action Required** worksheet immediately after Summary, combining PS1, PS2 and any other platforms exported by the report generator. It includes only unresolved games, unverified RA-supported releases, checksum-verified patch opportunities and hash failures that still need action. It excludes verified games, no-set/no-listing games, and redundant entries already covered by a verified copy of the same RA game. Rows are sorted by error, patch, replacement release and identity investigation.

The sheet includes platform, game name, full filename, disc ID, current status, proposed action, recommended release and region, RA ID, an existing verified copy when identifiable, reason, alternative RA candidates, local RA hash, accepted hashes and source path. The original per-platform sheets remain unchanged. Download **`RetroDB-Compatibility.xlsx`** as normal; no additional workbook or command is necessary. A **full audit** refreshes the underlying identity/hash data; export-only recreates the workbook from the previous audit.

## Current collection-management workflow

On a configured Debian host, update and launch the interactive manager:

```bash
cd ~/retrodb
git pull --ff-only origin main
bash server/manager.sh
```

Main-menu **1) Audit games** performs the full eight-stage audit. **More options → 1) Export reports** regenerates reports from the existing audit (no new scan): `~/retrodb-exports/RetroDB-Compatibility.xlsx`, `RetroDB-OPL-Rename-Proposals.xlsx`, the machine-readable OPL rename CSV, and the raw compatibility CSV. Both Excel reports include frozen/filterable headers; the compatibility workbook has Summary, PS1 and PS2 tabs.

Main-menu **2) Patch PS2 game** handles the controlled, checksum-verified patch workflow. The default audit collection mount remains read-only. The patch workflow verifies clean base images before applying any patches, and does not silently replace original ROMs. Only explicitly selected verified output may be deployed through a separate, confirmed operation. Keep original CRT/light-gun disc images: optional *No GunCon Flash* patches are not mandatory for all light-gun games.

Main-menu **3) Rename PS2 games** previews and confirms conservative OPL renames with collision safeguards. **More options** contains report exports, patch downloads, service details, rename recovery, patch journals, application maintenance, Debian upgrades, and **8) RetroNAS settings**.

**RetroNAS settings:** The submenu shows the SMB share, mount status and configuration, allows retrying the existing mount and reading its journal, and can run `server/configure-retronas.sh` after confirmation to change server/share/credentials. **4) Enable reliable on-demand mount at boot** runs `server/enable-retronas-automount.sh`, replacing eager boot-time mounting with a systemd automount. The helper preserves the original SMB 3.1.1 read-only mount definition and protected credentials; the user must confirm because the mount is briefly stopped. Status reports `on-demand`, `mounted`, or `unmounted`. This prevents a DNS-not-ready-at-boot failure from permanently blocking the initial mount, but does not guarantee recovery from every runtime disconnect.

**Patch-stage timing:** Stage 7 prints wall-clock start/end times and elapsed seconds for patch download/cache lookup, source-image checksum verification and the overall stage. Downloads may be reused while checksum verification still reads large ISOs across SMB. Repeated source verification is not yet skipped automatically based on these timings.

After a renaming or patch deployment operation, run a fresh audit; export-only cannot refresh hashes or paths.

Full safeguards, recovery steps and notes are in [Server operations](server/README.md) and [RetroNAS scanning](docs/retronas-scanning.md). Always test games and artwork on the target PS2/OPL-RA setup before removing retained original copies.

## PS2 RetroAchievements and xeRAbora

RetroDB's longer-term goal is not just to catalogue a ROM library, but also to **audit PS1 and PS2 game images against recognised release identifiers and RetroAchievements-supported hashes**. A title being present on RetroNAS does not necessarily mean that its particular region, revision, dump or patched image is compatible with RetroAchievements. RetroDB can help identify those differences, maintain a verified inventory, and eventually prepare a curated collection of compatible images for use on original hardware. This work is separate from the live achievements client.

For actual PS2 gameplay, the intended workflow is:

```text
RetroNAS game collection (canonical/read-only source)
      |
      v
RetroDB inventory, metadata and compatibility/hash checks
      |
      v
Select verified RetroAchievements-compatible game images
      |
      v
Copy to PS2-accessible storage (internal HDD or MMCE)
      |
      v
Real PS2 running a compatible OPL-RA build
      |
      v
Headless xeRAbora on Debian <--> RetroAchievements
```

**Important storage distinction:** In this setup, RetroNAS is the **source library and auditing target**, not the game-loading source for these OPL-RA/MMCE tests. Compatible images need to be **copied to the appropriate PS2-accessible HDD/MMCE storage** before running them. Do not assume that a game catalogued on RetroNAS can be launched directly from that NAS through this workflow. RetroDB's collection management does not itself install games onto the console.

### Standalone xeRAbora installer

The repository also contains a community installer/updater for [xeRAbora by hacan359](https://hacan359.github.io/xerabora/#top):

**[xeRAbora Debian installer, multi-player profile manager and setup guide](integrations/xerabora/README.md)**

It installs the xeRAbora headless client, matching `OPL-RA.ELF`, systemd service and RetroAchievements account configuration on a Debian x86-64 server or VM. The installer includes prerequisite checks, release checksum verification, live per-player logging, multi-profile switching, browser dashboard access (localhost by default, optional trusted-LAN exposure on TCP 18280), service management and a confirmed uninstall option. Startup mode can be set to **Automatic**, **Manual** or **Disabled**: Automatic enables systemd startup after network readiness with a 20-second delay and restarts the client after unexpected exits with a 10-second interval. These settings remain available through the terminal manager.

**This integration is intentionally standalone:** anyone can use it with a fresh Debian host and compatible PS2 **without installing or configuring the RetroDB database, backend, RetroNAS integration or ROM auditing tools**. Likewise, RetroDB can audit and catalogue a collection without xeRAbora. They complement each other rather than requiring one another.

The xeRAbora/OPL-RA integration has been tested on a real PS2 Slim with MemCard Pro 2 in MMCE mode, with game identification and successful achievement unlocks in *Crash of the Titans* and *The Lord of the Rings: The Return of the King*. Two independent RetroAchievements profiles have been switched successfully on the existing Debian VM, with the selected player shown correctly in the xeRAbora Web UI and live achievement progression tracked. A fresh Debian install on a separate clean host remains to be tested. PS2 ELF installation and copying game images to console storage are manual steps.

**Future hardening:** The xeRAbora integration currently runs under the installing Linux account. Optional support for a dedicated, non-interactive, unprivileged xeRAbora service account is planned, but **not yet implemented**; existing installations and profile ownership are unchanged. See the [integration guide](integrations/xerabora/README.md) for details.

## Planned repository layout

```text
retrodb/
├── backend/                 # API, models, services and security
├── frontend/                # templates and static assets
├── providers/               # external metadata adapters
├── workers/                 # sync, artwork and library jobs
├── migrations/              # PostgreSQL schema migrations
├── tests/
│   └── fixtures/            # offline provider fixtures
├── server/                  # standalone host bootstrap
├── deployment/
│   └── retronas/            # future RetroNAS/Ansible integration
├── docs/                    # design and operator documentation
├── .gitignore
└── README.md
```

Empty directories contain placeholder files until implementation begins.

## Initial roadmap

1. Define the PostgreSQL schema for games, releases, media and external identifiers.
2. Add PS1 and PS2 sample records and migrations.
3. Implement the provider contract and offline fixtures.
4. Import a responsibly cached RetroAchievements snapshot.
5. Add local library scanning and storage mappings.
6. Build the read-only web catalogue and search.
7. Add age-rating and owner-approval policy.
8. Add console inventory, instructions and QR-friendly pages.
9. Harden and document administration.
10. Package a standalone release, then build the RetroNAS role.

## Data and legal boundaries

RetroDB is metadata and collection-management software. The repository will not contain ROMs, disc images, BIOS files, copyrighted manuals or unlicensed artwork. Users are responsible for the legality of their own media, backups and imported metadata.

External services retain ownership of their data. Provider modules must respect API terms, licences, attribution requirements and rate limits.

## Contributing

The project is intentionally modular so new platforms and metadata providers can be added without changing the core application. Contribution guidance and coding standards will be added once the initial schema and provider interface are stable.

---

Created by [The Retro Bristolian](https://github.com/theretrobristolian).
