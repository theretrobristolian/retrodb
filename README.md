# RetroDB

RetroDB is an open-source, self-hosted catalogue and browser for retro-game collections.

The long-term aim is a fast, secure web front end for a physical game room or private collection: closer to **Plex for locally stored games** than a launcher or ROM-distribution service. It will catalogue what is available, explain how to use each console, and present curated game lists through tablets, phones and QR codes.

> **Project status:** very early design and scaffolding. RetroDB is not yet a usable application.

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
