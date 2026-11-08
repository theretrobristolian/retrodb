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

Patching is **one RA game ID at a time**, never a bulk patch operation. Review the selected game's source, expected RA hash and the separate NAS-write confirmation. For renames, review the preview before the explicit apply confirmation. Imported metadata and uncertain identity matches require manual review. GameDB matching deliberately leaves ambiguous releases unresolved for manual inspection.

## Current interactive manager

Run `retrodb` as your normal user:

| Menu | Operation |
|---|---|
| 1 | Full PS1/PS2 read-only audit and Excel/CSV export |
| 2 | Patch one verified RA game ID locally; for PS1, offer confirmed deployment to RetroNAS with verified `OLD_` BIN/CUE backups |
| 3 | PS1 BIN/CUE, PS2 OPL ISO and PS3 ISO/extracted-folder rename workflows, each with preview and explicit confirmation; optional PS3 read-only dedup audit |
| 4 | More options: exports, diagnostics, maintenance and connection settings |

The normal collection mount stays read-only. The confirmed PS1 deployment temporarily mounts the same share writable, validates the supplied patched CUE/BIN pair, copies and checksum-verifies `OLD_` backups, then publishes the verified patch. The PS2 legacy network deployment code still exists but is **not** part of the current menu-2 completion path. Check journals before retrying an interrupted write. Detailed instructions: [RetroNAS scanning](../docs/retronas-scanning.md).

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
