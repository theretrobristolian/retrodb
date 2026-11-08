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
| **3 Follow game log** | See the last hour of achievements, leaderboards and connections, then follow new events; Ctrl+C returns |
| **4 Service controls** | Show status, start, stop or restart |
| **5 Binary check/install** | Check the latest release; install only after confirmation |
| **6 Update manager scripts** | Refresh community scripts separately from the xeRAbora binary |
| **7 Advanced options** | Network/API diagnostics, startup settings, ELF guidance, rollback and uninstall |
| **8 Manage PS2 memory cards** | FTP setup and diagnostics, upstream normal/debug ELF downloads, update MemCard PRO2, create offline Free McBoot images |

Useful direct commands, from the checkout:

```bash
bash integrations/xerabora/install.sh doctor
bash integrations/xerabora/install.sh check
bash integrations/xerabora/install.sh follow-log
bash integrations/xerabora/install.sh status
```

The service is managed by systemd. The standard install location is `/opt/xerabora/`; player configuration is stored privately under `~/.config/xerabora-profiles/`. Each profile has independent xeRAbora data. Switching players **restarts the service**; the PS2 may need an OPL-RA restart/reconnection.

### Gameplay monitor and unsupported achievements

Menu **3** provides a read-only gameplay monitor: current game when the local xeRAbora `/state` endpoint exposes it, the previous hour of meaningful logged events, and new unlocks/leaderboards as they occur. Routine HTTP polling and heartbeats are hidden. It uses Python 3 and the standard library; no RetroDB service is involved.

Some RetroAchievements sets contain **pointer-chain memory reads** that the current PS2 agent cannot evaluate. xeRAbora reports a count such as `3 cannot unlock here (pointer chains)`. The manager highlights this count at game load. **A count is not a list of achievement names**: specific IDs and names appear only if the running xeRAbora build emits its detailed unsupported-achievement trace messages. Do not assume a missed unlock is one of those limitations without matching it to a named warning. Enable upstream trace logging only deliberately; it requires modifying the client startup and restarting the service.

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

## Live game and unsupported achievements

**Menu option 3** reads the local xeRAbora `/state` endpoint to identify the currently running **PS2 game**, shows the previous hour of meaningful events, and follows new achievements, leaderboards, and compatibility warnings without displaying routine HTTP polls. It does not modify the running xeRAbora process.

xeRAbora's summary can report, for example, `3 cannot unlock here (pointer chains)`. That **count is authoritative for the loaded game, but it does not name the achievements**. The current xeRAbora source logs specific pointer-chain achievement IDs and titles only with its **`--trace` option enabled before the game loads**. With that option enabled, the manager will display lines naming those achievements as the set is loaded. The `/state` achievement list alone does not prove which pointer chains failed to compile.

To use detailed compatibility traces, add `--trace` to the service's existing xeRAbora invocation during planned downtime, restart the service and relaunch the game. Because service overrides and executable flags vary, inspect `systemctl cat xerabora.service` first and **do not add a second ExecStart**. Trace can produce substantially more disk logging; remove the flag and restart after diagnosing the game. The monitor itself does not enable tracing or restart the service.

## Troubleshooting

Run `bash integrations/xerabora/install.sh doctor` to inspect networking, service health, UDP listener and logs. Check the PS2's **OPL-RA → Triangle → RA: test PC connection** workflow. A listening port alone does not prove console connectivity. Menu option **3** scans the full log for events from the previous hour, shows a service/profile summary, then follows new gameplay events without HTTP polling or heartbeat noise. The full log remains unchanged.

For service logs:

```bash
journalctl -u xerabora.service -n 80 --no-pager
```

If the update checker cannot access GitHub, it does not establish that an installed build is outdated. Prefer a verified known-good setup over speculative upgrades.

## Safety and scope

Installation requires confirmation before binary replacement and checks upstream download checksums where provided. Profile switching and service controls can interrupt an active PS2 session. Do not publish the web dashboard or service ports to the public internet. API keys, tokens and game files must not be committed to Git.

This helper is **experimental and community supported**, with no guarantee of compatibility across all CPUs, PS2 loaders or networks.

For implementation history and older troubleshooting, see the [archived xeRAbora development notes](../../docs/development-notes/XERABORA-README-HISTORY.md).

## iPhone home-screen icon (upstream contribution)

The xeRAbora web client is **embedded into the upstream binary**, not hosted
by RetroDB. A user-added icon cannot become active on the existing xeRAbora
phone page solely by changing this installer.

For the creator to add a browser favicon and an iOS home-screen icon:

1. Generate opaque PNG assets from the xeRAbora logo:
   `apple-touch-icon.png` (180×180), `favicon-32.png` (32×32),
   `icon-192.png` (192×192), `icon-512.png` (512×512), plus `favicon.ico`.
2. Edit upstream **`client/ui/src/page.html`**, not generated
   `client/ui/index.html`, adding inside `<head>`:

   ```html
   <link rel="icon" href="/favicon.ico" sizes="any">
   <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
   <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
   <link rel="manifest" href="/site.webmanifest">
   <meta name="apple-mobile-web-app-title" content="xeRAbora">
   <meta name="apple-mobile-web-app-capable" content="yes">
   <meta name="theme-color" content="#000000">
   ```

3. **Expose the files over HTTP** from the client at those paths, with the
   correct MIME types. The upstream client embeds a generated HTML page;
   copying images beside the executable does **not** make those URLs work.
   Alternatively, embed a base64 PNG in the `apple-touch-icon` HTML link
   and serve or embed the favicon similarly. Test all endpoints on a phone.
4. Add `site.webmanifest` with `name`, `short_name`, `display:
   "standalone"`, dark colours and 192px/512px icons; this helps Android.
5. Run `python3 tools/build-page.py` from upstream `client/`, then
   rebuild/release the client. This regenerates `client/ui/index.html`,
   `client/src/ui_page.c` and `docs/demo.html`.
6. On the iPhone open xeRAbora in **Safari → Share → Add to Home Screen**.
   Remove and recreate existing home-screen bookmarks to refresh the icon.

The artwork and icon assets must be added upstream for a shared release.
The RetroDB integration does not attempt to rewrite the xeRAbora executable.



## MemCard PRO2 and offline memory-card image manager (menu 8)

Run `xerabora` → **8 Manage PS2 memory cards / OPL-RA updates**, or
`python3 integrations/xerabora/memcard.py menu`. This helper is independent
of the RetroDB server/database. It uses Python standard library plus
`mymcplusplus` (installed into `~/mymc-env` from PyPI on request).

### Setup (once)

1. Choose **1 Setup** to cache the MemCard PRO2 hostname/IP (e.g. an address
   on your LAN), FTP username, remote image path and output directory.
   Configuration is stored at `~/.config/xerabora-memcard/config.json`
   with permissions 0600. **Passwords are not written to this config**.
2. You can optionally store your password in your desktop Secret Service
   keyring if `secret-tool` is installed and usable. Otherwise the tool
   asks for the password on each FTP connection. FTP itself is **unencrypted**:
   use only on a trusted, isolated home LAN, never over the public internet.
3. Choose **2 Dependencies** to install `mymcplusplus` in an isolated
   `~/mymc-env` venv. Debian may need `python3-venv` installed first.
4. Choose **3 Test FTP** to confirm port 21, login and passive directory
   listing. MemCard PRO2 FTP supports limited concurrent connections.
   If port 21 refuses connections, verify the IP, toggle FTP off/on in the
   device WebUI, re-enter username/password, click **Save Credentials**,
   then retry. In testing, this restored FTP without rebooting the PS2.

### Updating a Wi-Fi MemCard PRO2 directly

Use **4** to download/check SHA256SUMS and normal/debug `OPL-RA.ELF`
binaries from the latest upstream release; the debug ELF is optional and
only included if the release publishes a verified copy. The standalone
xeRAbora installer now also installs the debug ELF (when provided) during
an explicit upstream binary upgrade.

Use **5 Update over FTP**. The tool:

- Downloads the selected remote `.mc2` to a timestamped, immutable-by-name
  local backup (does not overwrite an existing backup).
- Creates a separate working copy; replaces `/APPS/OPL-RA.ELF` and,
  optionally, adds `/APPS/OPL-RA-debug.ELF` using mymc++.
- Verifies each embedded ELF's SHA-256 against the source and runs the
  mymc++ filesystem check without changing the original backup.
- Prints the target and requires entering the exact confirmation `UPLOAD`.
- Downloads the remote card again to detect changes before the upload.
- Uploads using passive FTP, reports progress, downloads the remote image
  again and verifies its SHA-256 against the patched image.
- Preserves original, pre-write and readback images locally.

**Important:** The upload replaces the entire `.mc2` file and is not
atomic. Do not deploy while the PS2 is saving or accessing the card.
The PS2 dashboard alone does not prove the card is unmounted. Prefer
switching to another card before upload; keep an independently bootable
Free McBoot fallback. In the case of a partial FTP write, restore from
the timestamped backup manually. After success, remount/reselect the
card or power-cycle the PS2. The helper does not automatically send
PS2 reset/remount commands or modify the FMCB menu configuration. The
debug ELF will need a separate FMCB launch entry to be selected.

### Offline images for MemCard PRO2, Bitfunx and other SD-card devices

Choose **6 Patch local image** when the target has no Wi-Fi/FTP, or for
preparing an image for a second machine. Download a suitable Free McBoot
memory-card template from its original distributor, then supply the
local `.mc2` file **or a downloaded ZIP containing one**. The menu
lets you choose a card within a ZIP and outputs a timestamped patched
`.mc2` without overwriting the source. A useful starting point is
the [MemCard PRO2 FMCB image collection supplied by the user](https://www.dropbox.com/scl/fo/4ns7r30phoe0cpu3m53lt/h?rlkey=set4hi9uqjtnlgdexdz3m57rj&dl=0);
the helper does **not** download or validate that Dropbox folder
automatically, because its archive names, contents and licensing have
not been verified. Select the correct card format and capacity for your
hardware, firmware and boot exploit before writing it to SD.

The configured output folder can be an **already mounted RetroNAS/NFS
share** if the Linux user has write permission; SMB clients can then
retrieve the files without needing FTP access. Suggested **placeholder**
layout, not an enforced convention:

```text
roms/
  memory-cards/
    memcardpro2/
      templates/
      patched/
    bitfunx/
      templates/
      patched/
```

Only set `output_dir` to the desired `patched` directory: this
helper deliberately does not modify RetroNAS share configuration or
the core ROM library. It does not change the source image's permissions.
Actual SD card folder/filename conventions vary by device, and require
device-specific verification; the tool doesn't claim all Bitfunx
models accept MemCard PRO2 `.mc2` images unchanged.

For an existing Free McBoot card we verified this procedure on a
MemCard PRO2: edit `/APPS/OPL-RA.ELF` in an 8 MiB `.mc2`, validate the
embedded SHA-256 and image filesystem, upload and read back the whole
image, and restart PS2. Free McBoot remained present. Testing of other
formats and automatic remounts is still outstanding.
