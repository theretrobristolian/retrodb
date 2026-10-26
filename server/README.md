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

Patching is **one RA game ID at a time**, never a bulk patch operation. Review the selected game's source, expected RA hash and the separate NAS-write confirmation. For renames, review the preview before the explicit apply confirmation. Imported metadata and uncertain identity matches require manual review. GameDB matching deliberately leaves ambiguous releases unresolved for manual inspection.

## Current interactive manager

Run `retrodb` as your normal user:

| Menu | Operation |
|---|---|
| 1 | Full PS1/PS2 read-only audit and Excel/CSV export |
| 2 | Patch one verified RA game ID locally; for PS1, offer confirmed deployment to RetroNAS with verified `OLD_` BIN/CUE backups |
| 3 | PS1 paired BIN/CUE renames or PS2 OPL rename workflow, with preview and explicit confirmation |
| 4 | More options: exports, diagnostics, maintenance and connection settings |

The normal collection mount stays read-only. The confirmed PS1 deployment temporarily mounts the same share writable, validates the supplied patched CUE/BIN pair, copies and checksum-verifies `OLD_` backups, then publishes the verified patch. The PS2 legacy network deployment code still exists but is **not** part of the current menu-2 completion path. Check journals before retrying an interrupted write. Detailed instructions: [RetroNAS scanning](../docs/retronas-scanning.md).

PS1 friendly titles show verified disc numbers, including the four Geppy-X discs; unknown disc numbering is not invented. Revision labels are omitted from friendly titles.

## Operations

```bash
systemctl status retrodb
journalctl -u retrodb -n 80 --no-pager
curl -fsS http://127.0.0.1:8000/health
```

The live environment and secrets reside outside Git, commonly in `/etc/retrodb/retrodb.env`; see [the example configuration](../config/retrodb.env.example). Never commit credentials, ROMs or downloaded game artwork.

This remains a developing application and **is not a hardened public hosting guide**. Refer to [current status](../docs/CURRENT-STATUS.md), [architecture](../docs/architecture.md) and [historical notes](../docs/development-notes/SERVER-README-HISTORY.md) for design context.
