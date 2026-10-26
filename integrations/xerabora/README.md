# xeRAbora — standalone Linux installer and manager

**Community-maintained helper · work in progress.** This is a standalone installer, updater and terminal manager for [xeRAbora](https://github.com/hacan359/xerabora), the RetroAchievements companion for supported **real PlayStation 2 hardware**. xeRAbora itself is made by **hacan359 and contributors**; this installation helper is maintained by **The Retro Bristolian**.

**You do not need RetroDB, RetroNAS, PostgreSQL or the RetroDB web application.** The integration scripts can run independently on a Debian-family Linux machine.

## Requirements

- Debian or a Debian-family Linux distribution, **x86-64**, with systemd.
- A normal user account with **sudo** privileges. **Do not run the installer as root** or with `sudo bash`.
- Network access to GitHub, your PS2, and RetroAchievements; a RetroAchievements account.
- The installer checks required commands and can offer to install missing Debian packages. A PS2 running a compatible **OPL-RA.ELF** is needed for achievements on real hardware.

The server and PS2 must be able to communicate across the network. See diagnostics below before changing firewall settings. This is intended for a **trusted private LAN**, not an internet-exposed service.

## Install on a fresh Debian machine

```bash
sudo apt-get update
sudo apt-get install -y sudo git ca-certificates curl python3
git clone https://github.com/theretrobristolian/retrodb.git
cd retrodb
bash integrations/xerabora/install.sh prerequisites
bash integrations/xerabora/install.sh
```

The clone is **only a convenient way to obtain the scripts**. No RetroDB service or database needs to be installed. If copying the scripts instead, copy the **entire `integrations/xerabora/` directory**, not `install.sh` alone: it uses companion files such as `ui.sh`, `profiles.sh` and `rollback.sh`.

The menu checks for an upstream xeRAbora release and offers an **explicit**, checksum-verified installation. Follow its prompts to configure authentication and the systemd service. Never blindly replace a working manually installed binary.

After installation, launch the menu with `xerabora` if its launcher was registered, or run `bash integrations/xerabora/install.sh` from your checkout.

## Everyday use

| Menu | What it does |
|---|---|
| **1 Switch player** | Select a previously configured RetroAchievements profile |
| **2 Manage players** | Add/import profiles and manage credentials |
| **3 Follow game log** | Watch achievements, connections and leaderboard events; Ctrl+C returns |
| **4 Service controls** | Show status, start, stop or restart |
| **5 Binary check/install** | Check the latest release; install only after confirmation |
| **6 Update manager scripts** | Refresh community scripts separately from the xeRAbora binary |
| **7 Advanced options** | Network/API diagnostics, startup settings, ELF guidance, rollback and uninstall |

Useful direct commands, from the checkout:

```bash
bash integrations/xerabora/install.sh doctor
bash integrations/xerabora/install.sh check
bash integrations/xerabora/install.sh follow-log
bash integrations/xerabora/install.sh status
```

The service is managed by systemd. The standard install location is `/opt/xerabora/`; player configuration is stored privately under `~/.config/xerabora-profiles/`. Each profile has independent xeRAbora data. Switching players **restarts the service**; the PS2 may need an OPL-RA restart/reconnection.

## Version reporting and compatible binaries

The manager shows **Recorded version** (the `/opt/xerabora/VERSION` marker) separately from **Binary identity** (identified by the executable's SHA-256 where known). These can differ after a manual or community test-build installation.

**Known situation, October 2026:** the upstream **v1.0.0** Linux binary is blocked by a conservative CPU compatibility guard on some x86-64 hosts. A separate community test build has been tested successfully on a real PS2, but it is **not the same file** as the official v1.0.0 binary and may have a stale version marker. The manager must not replace that working binary automatically or claim it is official v1.0.0. Future upstream patch releases need their own checksum/CPU validation.

To inspect an installation without changing it:

```bash
cat /opt/xerabora/VERSION
sha256sum /opt/xerabora/xerabora-linux-x86_64
systemctl cat xerabora.service
```

**Linux executable vs console ELF:** `xerabora-linux-x86_64` runs on the Linux server; `OPL-RA.ELF` runs on the PS2. Updating one does **not** update the other. Back up working files before replacing either.

## Troubleshooting

Run `bash integrations/xerabora/install.sh doctor` to inspect networking, service health, UDP listener and logs. Check the PS2's **OPL-RA → Triangle → RA: test PC connection** workflow. A listening port alone does not prove console connectivity. Watch live activity using menu option **3**.

For service logs:

```bash
journalctl -u xerabora.service -n 80 --no-pager
```

If the update checker cannot access GitHub, it does not establish that an installed build is outdated. Prefer a verified known-good setup over speculative upgrades.

## Safety and scope

Installation requires confirmation before binary replacement and checks upstream download checksums where provided. Profile switching and service controls can interrupt an active PS2 session. Do not publish the web dashboard or service ports to the public internet. API keys, tokens and game files must not be committed to Git.

This helper is **experimental and community supported**, with no guarantee of compatibility across all CPUs, PS2 loaders or networks.

For implementation history and older troubleshooting, see the [archived xeRAbora development notes](../../docs/development-notes/XERABORA-README-HISTORY.md).
