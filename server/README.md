# RetroDB server

**Work in progress — Debian VM reference deployment.** These are the current entry points for the RetroDB application. For the project's purpose, see the [main README](../README.md). Dated experiment logs and older installation advice have been preserved in [server development notes](../docs/development-notes/SERVER-README-HISTORY.md).

## Existing VM: update RetroDB

```bash
cd ~/retrodb
git pull --ff-only
sudo bash server/deploy.sh
curl -fsS http://127.0.0.1:8000/health
```

This updates the RetroDB application and its configured service. It does **not** replace a manually installed xeRAbora Linux binary or the PS2's OPL-RA ELF.

## Rename regression checks

`server/build.sh` installs Debian's `python3-pytest` alongside other build prerequisites. The installed RetroDB application itself does **not** require pytest to run. After pulling source changes, validate rename scripts before allowing a writable rename:

```bash
cd ~/retrodb
python3 -m py_compile server/ps1_ra_conflict.py server/ps1_rename.py server/report_ps1_audit.py server/ps2_live_rename.py server/ps3_rename.py server/ps3_dedup.py
bash -n server/manager.sh
python3 -m pytest tests/test_ps1_verified_conflicts.py tests/test_ps3_rename.py tests/test_ps3_dedup.py -q
```

For eligible PS1 CUE/BIN collisions, menu 3 previews and requires explicit `RENAME ALL` confirmation for eligible bulk renames. Verified RA alternatives take priority. When an existing canonical pair and another image share a verified game identity and the same internal disc serial, the canonical pair remains active and the extra pair is preserved as `OLD_`, even if their BIN files differ. The resolver compares live RA hashes against the audit before writing, retains a recovery journal, and refuses ambiguous disc, mode, or special-edition pairs. Without a reviewed RA identity, differing hashes still require manual review. An unmatched source is never preferred over an RA-matched canonical image. Collisions may be applied individually with journals; `OLD_` pairs must be reviewed before manual deletion. Never delete or rename a `SKIP - REVIEW` pair based only on RA hashes.

## Main tools

| Task | Tool |
|---|---|
| Build prerequisites | `server/build.sh` |
| Deploy or update | `server/deploy.sh` |
| Terminal management menu | `retrodb` / `server/manager.sh` |
| Configure RetroNAS collection access | `server/configure-retronas.sh` |
| RetroAchievements procedures | [Setup guide](../docs/retroachievements-setup.md) |
| Conservative GameDB metadata enrichment | `server/enrich-gamedb.py` |
| Cached artwork prefetch | `server/prefetch-artwork.py` |
| xeRAbora service/profile management | [Integration guide](../integrations/xerabora/README.md) |
| PS2 MemCard PRO2 FTP / offline `.mc2` builder | xeRAbora menu option 8; [Memory-card guide](../integrations/xerabora/README.md#memcard-pro2-and-offline-memory-card-image-manager-menu-8) |

The normal **Audit games** workflow is fast and read-only: stage 7 checks
cached/downloaded official patch packages but does **not** verify patch
source image checksums. The previous full-source checksum pass read many
gigabytes over RetroNAS even when no patch was being applied. Mandatory
source verification remains in **2) Patch PS1 / PS2**, before any patch
operation or NAS deployment. Normal audit reports do not reuse potentially
stale `patch-prepare.json` as evidence that a source is currently verified.

The full audit's PS3 stage writes **every record** into
`~/retrodb-exports/RetroDB-PS3-Audit.csv`, but the terminal displays a
compact status summary and up to 20 exceptions. Full per-file previews
remain visible under **3) Rename games → PlayStation 3**.

Patching is **one RA game ID at a time**, never a bulk patch operation. Review the selected game's source, expected RA hash and the separate NAS-write confirmation. For renames, review the preview before the explicit apply confirmation. Imported metadata and uncertain identity matches require manual review. GameDB matching deliberately leaves ambiguous releases unresolved for manual inspection.

## Current interactive manager

Run `retrodb` as your normal user:

| Menu | Operation |
|---|---|
| 1 | Full PS1/PS2/PS3, Sega 32X and Wii audit; exports compatibility data and refreshes console listings |
| 2 | Patch one verified RA game ID locally; for PS1, offer confirmed deployment to RetroNAS with verified `OLD_` BIN/CUE backups |
| 3 | PS1 BIN/CUE, PS2 OPL ISO, PS3 ISO/extracted, Sega 32X ZIP and Nintendo Wii folder naming; all preview before confirmation |
| 4 | More options: exports, diagnostics, maintenance and connection settings (32X/Wii run in the full audit) |

The normal collection mount stays read-only. The confirmed PS1 deployment temporarily mounts the same share writable, validates the supplied patched CUE/BIN pair, copies and checksum-verifies `OLD_` backups, then publishes the verified patch. The PS2 legacy network deployment code still exists but is **not** part of the current menu-2 completion path. Check journals before retrying an interrupted write. Detailed instructions: [RetroNAS scanning](../docs/retronas-scanning.md).

### Nintendo Wii read-only WBFS integration

The regular **Audit games** action now detects `roms/nintendo/wii` on the
existing RetroNAS mount and inventories Wii game folders (for example
`Attack of the Movies 3D [S3AE5G]/S3AE5G.wbfs`). Wii is included in the normal full audit; no separate More options entry is needed.

The scan verifies folder/file **disc-ID consistency**, caches the official
RetroAchievements Wii **system 19** catalogue, and indexes Wii titles into the
normal `/consoles/wii` and `/library/wii` pages. Optional downloaded
GameTDB English-locale XML may enrich titles by exact six-character disc ID.
This stage **does not compute Wii RA hashes**: a title candidate is not an
exact hash match and earns no verified trophy. No Wii images or mounts are
changed. See [Wii integration documentation](../docs/wii-integration.md).

### Nintendo Wii folder naming

Choose **Rename games → 5 Nintendo Wii** to preview ID-preserving folder title corrections. The tool fetches and caches GameTDB's English title list keyed by exact six-character Wii disc ID, or conservatively normalises ALL-CAPS folder names when no authoritative title is available. Only the directory changes; its WBFS file remains named by disc ID and is never rewritten. A temporary writable RetroNAS mount, collision preflight, explicit `RENAME WII` confirmation and write-ahead journal protect changes. On success the normal Wii audit refreshes database paths. See [Wii integration](../docs/wii-integration.md).

### Sega 32X concise ZIP rename

Open `retrodb → 3 Rename games → 4 Sega 32X`. After a read-only preview,
eligible ZIPs can be renamed using an explicit `RENAME 32X` confirmation,
using a temporary writable RetroNAS mount that is unmounted afterward.

Names follow a **No-Intro-inspired display convention**, not an assertion of
No-Intro ROM verification: `Knuckles' Chaotix (Japan, USA).zip` instead of
`[32X] Knuckles' Chaotix (Japan, USA) (En).zip`. Language and platform tags
are removed; title and explicit region are retained. An exact registered RA
MD5 may supply the region from the matching registered hash description if
the original ZIP has no region. Unmatched titles rely on their original
filename, not an unverified catalogue suggestion.

**Only the outside ZIP filename is renamed**. The ROM filename *inside* the
ZIP is left unchanged, preserving archive contents and hash compatibility.
Auditing already validates the ZIP contains a single ROM member; it does
not require rewriting that member to rename the outer archive.

ZIPs with absent/uncertain region, malformed contents, special build markers
(prototypes, revisions, hacks and patches), or destination collisions are
reported for manual review rather than changed. The script checks
case-insensitive target collisions, re-audits immediately before the
confirmed writable operation and writes a per-file journal under
`~/retrodb-exports/32x-rename-journals/`. Never retry an interrupted
rename without inspecting its journal.

After successful renaming, the manager automatically runs the read-only
32X audit again to refresh the web library's indexed paths.

### Sega 32X RetroAchievements audit (read-only)

A normal `retrodb → 1 Audit games` run now includes Sega 32X as stage 9/9 whenever its collection folder exists. To run only the 32X audit, use `retrodb → 4 More options → 11`. It scans `/mnt/retrodb-retronas/roms/sega/32x` and writes
`~/retrodb-exports/RetroDB-Sega-32X-Audit.csv`.

- Ignores .txt files, Mac resource forks and ZIPs containing `bios` in
  their filenames (including `[32X] 32xbios.zip`).
- Identifies the **single 32X ROM member inside each ZIP**, streaming the
  uncompressed ROM content through MD5. This follows RetroAchievements'
  official Sega 32X content-hashing method, not an MD5 of the ZIP itself.
  Ambiguous ZIPs (multiple ROMs), invalid archives and oversized members
  are flagged for review and never silently assumed compatible.
- Synchronises the official **RetroAchievements Sega 32X system ID 10**
  catalogue to its own cache, without changing the PS1/PS2 caches.
- Uses the **verified RA title** as the authoritative display name for
  exact hash matches. An unmatched ZIP can receive an RA catalogue title
  candidate through conservative filename matching, explicitly labelled
  *unverified* rather than presented as an approved hash match. This
  audit now also synchronises ROM records into the website's Sega 32X
  console and library pages. Only exact MD5 matches receive verified RA
  IDs and gold trophies; all title candidates remain unverified.
- Reports `EXACT_RA`, `EXACT_NO_SET`, `ALTERNATIVE_REVIEW`,
  `SOFT_PASS_VARIANT`, `NO_SET_CANDIDATE`, `UNMATCHED`,
  `AMBIGUOUS_TITLE`, or `REVIEW`. A soft pass means another local ZIP
  hashes exactly to the same RA game; the unmatched regional ZIP **does
  not inherit** that compatible hash. The CSV names the local usable
  alternative, rather than falsely claiming the mismatched ZIP works.
- When per-game RA hash descriptions are already cached, reports the
  supported release names/regions for manual review. Otherwise provides
  the official registered MD5s as evidence, never fabricated download
  URLs or alternate ZIP filenames. Reviewed aliases identify Doom 32X:
  Resurrection (RA 18179, separate from original Doom), Pinocchio
  prototype (16800), Soul Star X (15989), and Virtua Racing Deluxe
  (11823), without asserting their modified ROM hashes are supported.

The **audit** remains deliberately read-only. It never renames or edits ZIPs,
patches ROM data, deletes duplicates, or writes to the RetroNAS collection.
The audit requires configured RA Web API credentials and the existing
RetroNAS read-only mount. After pulling changes, run
`sudo bash server/deploy.sh` once to install the backend scanner and website
integration; the menu then publishes to `/consoles/sega-32x` and
`/library/sega-32x`. The PostgreSQL inventory is updated, but the ROM
collection stays read-only. Raw export can also run directly:

```bash
python3 server/report_32x_audit.py \
  --root /mnt/retrodb-retronas/roms/sega/32x \
  --ra-catalogue /var/cache/retrodb/providers/retroachievements/sega-32x.json \
  --output ~/retrodb-exports/RetroDB-Sega-32X-Audit.csv
```

### PS3 rename and extracted-folder deduplication

Under `retrodb → 3 → 3`, the PS3 workflow refreshes the cached PS3 GameDB catalogue and previews ISO/sidecar and extracted-folder filenames. Nothing is renamed without the separate `RENAME ALL` confirmation. An optional **read-only** check compares extracted game directories to matching disc-ID ISOs by file path, size and SHA-256. The process prints per-game and per-100-file progress and writes:

- `~/retrodb-exports/RetroDB-PS3-Dedup.csv` — summary per extracted game.
- `~/retrodb-exports/RetroDB-PS3-Dedup-Files.csv` — per-file differences, sizes and hashes.

`NO_EXACT_ISO`, `DIFFERENT` and `INCONCLUSIVE` do **not** authorise deletion. Only the two explicitly approved Red Dead releases (`BLES00680`, `BLES01179`) can currently qualify for cleanup, and only when every extracted file matches the ISO contents byte-for-byte, with the **only** ISO-only path being `PS3_UPDATE/PS3UPDAT.PUP`. The script lists eligible folders, asks for removal approval, requires the exact phrase `DELETE VERIFIED`, and rehashes before deletion via a temporary writable RetroNAS mount. ISO files are preserved. This checks content equivalence, **not console boot behaviour**. A normal scan does not remove anything.

PS2's `retrodb → 3 → 2` workflow now independently refreshes its **PS2-only** GameDB cache and rebuilds OPL rename proposals from the live collection before previewing them; it does not require a previous export.

PS1 friendly titles show verified disc numbers, including the four Geppy-X discs; unknown disc numbering is not invented. Revision labels are omitted from friendly titles.

## Operations

```bash
systemctl status retrodb
journalctl -u retrodb -n 80 --no-pager
curl -fsS http://127.0.0.1:8000/health
```

The live environment and secrets reside outside Git, commonly in `/etc/retrodb/retrodb.env`; see [the example configuration](../config/retrodb.env.example). Never commit credentials, ROMs or downloaded game artwork.

This remains a developing application and **is not a hardened public hosting guide**. Refer to [current status](../docs/CURRENT-STATUS.md), [architecture](../docs/architecture.md) and [historical notes](../docs/development-notes/SERVER-README-HISTORY.md) for design context.
