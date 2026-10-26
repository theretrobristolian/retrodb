# RetroDB server

**Work in progress — Debian VM reference deployment.** These are the current entry points for the RetroDB application. For the project's purpose, see the [main README](../README.md). Dated experiment logs and older installation advice have been preserved in [server development notes](../docs/development-notes/SERVER-README-HISTORY.md).

## Existing VM: update RetroDB

```bash
cd ~/retrodb
git switch main
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

Before running any bulk patch, rename, import or enrichment, review that tool's options and start in its preview/dry-run mode if available. GameDB matching deliberately leaves ambiguous releases unresolved for manual inspection.

## Operations

```bash
systemctl status retrodb
journalctl -u retrodb -n 80 --no-pager
curl -fsS http://127.0.0.1:8000/health
```

The live environment and secrets reside outside Git, commonly in `/etc/retrodb/retrodb.env`; see [the example configuration](../config/retrodb.env.example). Never commit credentials, ROMs or downloaded game artwork.

This remains a developing application and **is not a hardened public hosting guide**. Refer to [current status](../docs/CURRENT-STATUS.md), [architecture](../docs/architecture.md) and [historical notes](../docs/development-notes/SERVER-README-HISTORY.md) for design context.
