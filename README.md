# RetroDB

**Very much a work in progress.** RetroDB is a personal, open-source companion application for managing and exploring a retro-game collection. It currently runs **standalone on a Debian 13 VM**, with the longer-term ambition of becoming an optional application that can run **alongside or on top of RetroNAS**.

The starting focus is **original PlayStation (PS1) and PlayStation 2 (PS2)**. The goal is not to replace RetroNAS or a console's loader; it's to make a collection easier to **audit, identify, organise, repair where supported, and browse**.

## What it's for

- **Audit ROM/disc-image libraries:** index files, identify serials and releases, check filenames and flag questionable or unmatched copies.
- **Match RetroAchievements:** identify supported games and known-good hashes, and help spot versions that may need attention.
- **Help repair and organise games:** support individually confirmed PS1 BIN/CUE and PS2 patching workflows, reversible `OLD_` backups, OPL-compatible naming and rename reports—without silently modifying a library.
- **Provide a web-based catalogue:** browse the games actually in your collection on a desktop, tablet or phone, with artwork, platform/region information, search and available game metadata.
- **Bring metadata together:** enrich the collection using sources such as RetroAchievements and GameDB/IGDB while caching results responsibly.
- **Connect related services:** optionally link RetroAchievements profiles and xeRAbora for supported real-hardware PS2 setups.

Eventually RetroDB could offer better release/disc auditing, collection curation, compatibility data, manuals, game features and age-appropriate lists, and be packaged as an optional RetroNAS integration. Those are **goals, not promises of completed features**.

## Current state

The application has a functioning FastAPI/PostgreSQL backend, a responsive read-only game-library web interface, PS1/PS2 indexing, RetroAchievements auditing and metadata/artwork enrichment. It also has optional helpers for PS1/PS2 patch verification and PS1 NAS deployment, OPL filenames, online-service catalogues and xeRAbora integration.

**Expect rough edges.** This is an actively evolving personal project, not a supported production release. Some imports require manual review, regional identification is sometimes inferred from disc prefixes, and metadata such as exact player counts or peripherals is incomplete. No game ROMs or commercial artwork are included in this repository.

## Running it

Development currently targets Debian with PostgreSQL, Python/FastAPI and systemd. Installation and configuration are documented in [server/README.md](server/README.md); the maintained branch is `main`.

For an *existing* deployment:

```bash
cd ~/retrodb
git pull --ff-only
sudo bash server/deploy.sh
```

This deploys RetroDB; it **does not automatically update** the separate xeRAbora Linux service or replace the OPL-RA ELF on a physical PS2.

## Auditing, patching and multi-disc names

Run `retrodb` for the interactive terminal manager. **1) Audit games** scans the read-only RetroNAS collection and creates compatibility and naming reports. **2) Patch PS1 / PS2** selects one RetroAchievements game ID; compatible sources are verified before local patching. For PS1, the manager can then offer a separately confirmed writable NAS deployment that preserves the original CUE/BIN files under `OLD_` names and verifies the patched pair. PS2's older network deployment mechanism is not yet integrated into this new menu flow. **3) Rename games** previews and confirms paired PS1 BIN/CUE or OPL PS2 ISO renames. See the [RetroNAS procedures](docs/retronas-scanning.md) for the exact safety rules and limitations.

PS1 multi-disc titles display `(Disc N)` when supported by an explicitly reviewed disc serial or an existing filename label. RetroDB never determines disc order from alphabetical sorting; unrecognised, unlabelled discs still require review. Revision text is omitted from friendly display names; this does not alter the game's underlying data.

## Further reading

- [Server installation and administration](server/README.md)
- [Current project status and known limitations](docs/CURRENT-STATUS.md)
- [Architecture](docs/architecture.md) · [Data model](docs/data-model.md)
- [RetroNAS scanning](docs/retronas-scanning.md) · [RetroAchievements setup](docs/retroachievements-setup.md)
- [xeRAbora integration](integrations/xerabora/README.md)
- [Development notes and historical decisions](docs/development-notes/ROOT-README-HISTORY.md)
- [Historical server development notes](docs/development-notes/SERVER-README-HISTORY.md)

## Project approach

Keep local collections and credentials private; prefer reversible, reviewed changes; cache external lookups rather than repeatedly querying community services. RetroDB is intended as a **companion to your own legitimately obtained game collection**, not a source of games.
