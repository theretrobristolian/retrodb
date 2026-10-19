# xeRAbora — standalone Debian headless installation

Community installer, updater and multi-account manager for [xeRAbora](https://github.com/hacan359/xerabora) and its matching PS2 `OPL-RA.ELF`. Maintained in the [RetroDB](https://github.com/theretrobristolian/retrodb) repository, but **RetroDB is not required**: no PostgreSQL, Python RetroDB application, RetroNAS, database, ROM scanner or existing VM image is involved.

**Status:** The xeRAbora client has been exercised successfully on a Debian 13 VM connected to a real UK PAL PS2 Slim, including game identification and achievement notifications for *Crash of the Titans* and *The Lord of the Rings: The Return of the King*. Fresh-machine provisioning and the new multi-account switching features are not yet end-to-end tested. Upstream xeRAbora remains alpha software.

## Fresh Debian 13 VM / server

Use a Debian **x86-64** installation with systemd, internet access and a normal (non-root) Linux user able to run `sudo`. For minimal installations, an administrator must first install sudo and grant your account sudo rights (log out and back in after joining the group). For example, as root:

```bash
apt-get update
apt-get install -y sudo git ca-certificates curl python3
usermod -aG sudo YOUR_LINUX_USERNAME
```

**Do not run the installer as root**. Re-login to the normal account, then:

```bash
git clone https://github.com/theretrobristolian/retrodb.git
cd retrodb
bash integrations/xerabora/install.sh prerequisites
bash integrations/xerabora/install.sh
```

The repository is used only to distribute three shell scripts and documentation; **no other RetroDB installation step is required**. If prerequisites are missing, the script can offer to install required Debian packages through apt, using sudo; it never silently grants sudo access. If you prefer to copy only the `integrations/xerabora/` directory to another machine, `install.sh`, `profiles.sh` and `ui.sh` must remain together. You can also download those three files manually; `git` is not required after the download.

The manager clears the terminal and displays a consistent ASCII xeRAbora banner, upstream project link, xeRAbora version, service state and active player, with the installer credit and Git update command in the footer. Both the installer and player-profile menus use the same header and footer. It offers installation/update, version checking, Web API key setup, API testing, service management, network diagnostics, live logs, login, numbered profile switching and uninstall. Choose **1) Install or update xeRAbora**. The installer queries the xeRAbora GitHub *releases list*, including pre-releases, downloads `xerabora-linux-x86_64`, `OPL-RA.ELF` and `SHA256SUMS`, and validates both assets against the release checksums before installation. It installs to `/opt/xerabora`, configures and enables `xerabora.service`, then offers initial RetroAchievements login. Type your password only at the hidden prompt. The client stores an account **token**, not your password.

Configure a **RetroAchievements Web API key** from https://retroachievements.org/settings (Keys) via main-menu option **2**. The key is saved as a permission-protected file. Accounts require independent keys. The main manager can test API access with option **3**.

## PS2 setup (manual)

The downloaded matching PS2 executable is **`/opt/xerabora/OPL-RA.ELF`**. Copy it to a USB drive or other console-accessible medium, then configure your PS2 to launch it (e.g., wLaunchELF / Free McBoot). Replace this ELF when updating to a release that changes the OPL-RA build; the installer does not update the PS2 remotely.

Example from a second computer:

```bash
scp YOUR_LINUX_USERNAME@YOUR_VM_IP:/opt/xerabora/OPL-RA.ELF .
```

### Copy the matching OPL-RA.ELF from a headless server

The Linux installer stores the **matching OPL-RA build for its installed xeRAbora release** at `/opt/xerabora/OPL-RA.ELF`. Because this is a headless server, download the ELF **to your own computer**, then copy it onto a USB stick or other PS2-accessible device.

Replace `YOUR_LINUX_USER` and `YOUR_SERVER` with your Debian account and its IP address or resolvable DNS name.

**macOS (Terminal):**

```bash
scp YOUR_LINUX_USER@YOUR_SERVER:/opt/xerabora/OPL-RA.ELF ~/Downloads/OPL-RA.ELF
```

**Linux (terminal):**

```bash
scp YOUR_LINUX_USER@YOUR_SERVER:/opt/xerabora/OPL-RA.ELF ~/Downloads/OPL-RA.ELF
```

**Windows 10/11 (PowerShell with OpenSSH Client installed):**

```powershell
scp YOUR_LINUX_USER@YOUR_SERVER:/opt/xerabora/OPL-RA.ELF "$env:USERPROFILE\\Downloads\\OPL-RA.ELF"
```

Windows users can also connect with WinSCP over SFTP and download `/opt/xerabora/OPL-RA.ELF` to their Downloads folder.

Once downloaded:

1. Insert a USB stick readable by your PS2 file manager (commonly FAT32) into your computer and copy `OPL-RA.ELF` onto it, e.g. under `APPS/`.
2. On the PS2, use wLaunchELF/uLaunchELF to run the ELF directly from USB or copy it to the appropriate PS2 app location, then configure your FMCB or other launcher.
3. If updating xeRAbora, replace the **older PS2 ELF with the matching new one** as needed. Save your game, exit, and relaunch OPL-RA.

**Important:** `scp` runs on your **Mac/Windows/Linux computer**, not in the SSH shell on the Debian server. It is a *download from the server to your local computer*. The server's ELF is not automatically deployed to the console. You only need to re-copy it when the installed OPL-RA ELF needs updating; you do not need to copy it on every game launch.

If using MemCard Pro 2, power-cycle the PS2 and check the selected virtual card before copying the ELF or editing Free McBoot's menu; these details are specific to your chosen PS2 setup, **not a requirement** of xeRAbora. MMCE or RetroNAS are not prerequisites of the Linux installer.

The PS2 and headless Linux machine should share a **broadcast domain / subnet** for discovery (the server listens on **UDP 18194**). Give the host a stable reachable address or DHCP reservation. Ensure any host firewall permits the traffic; this script does not open ports or modify routing/firewall policies. In OPL-RA use **Triangle → RA: test PC connection**, then **RA: check game support**. Confirm the logged-in account and an identified supported game in the server log.

## Commands and maintenance

```bash
bash integrations/xerabora/install.sh                # manager
bash integrations/xerabora/install.sh check          # upstream vs installed
bash integrations/xerabora/install.sh update         # manual checked update
bash integrations/xerabora/install.sh doctor         # IP, service, UDP, logs
bash integrations/xerabora/install.sh status
bash integrations/xerabora/install.sh logs
bash integrations/xerabora/install.sh restart
bash integrations/xerabora/install.sh api-key
bash integrations/xerabora/install.sh test-api
```

No reboot of Linux is required for an installer update, account switch or service restart. Save and exit a PS2 game before restarting the xeRAbora service, then relaunch/re-pair OPL-RA. An upstream update might require copying its **matching PS2 ELF** to the console.

## Built-in Web UI and dashboard URL

The xeRAbora client includes a browser dashboard on **TCP port 18280**. The installer now enables it by default on **localhost only**, without opening the LAN. The main installer has **12) Configure Web UI / LAN access** for existing installations, where you can enable or disable the interface and separately opt into LAN access. The terminal header shows the appropriate local URL and, only when LAN access is enabled, the detected server IPv4 URL and its FQDN (if one exists). A hostname link works only when your DNS resolves that name to the server.

For a new or already-running server:

```bash
cd ~/retrodb
git pull --ff-only origin main
bash integrations/xerabora/install.sh
# Choose 12 → 2 to enable LAN dashboard (after confirming trusted LAN access)
```

Then open `http://YOUR_SERVER_IP:18280/` or your resolvable server name on that local network.

**Security:** The dashboard uses **unencrypted HTTP** and shows account/library information; upstream xeRAbora normally binds to `127.0.0.1`. Do not expose this TCP port to the internet or untrusted VLANs. Keep your firewall rules restricted to trusted clients. If you prefer to keep it local, select option 12 → 1 and access it using SSH forwarding:

```bash
ssh -L 18280:127.0.0.1:18280 USER@YOUR_SERVER_IP
# Open http://127.0.0.1:18280/ on your computer
```

The settings restart only the xeRAbora service, **not the Debian host**. Save and close any running PS2 game first; relaunch OPL-RA to reconnect afterwards. The page follows the account currently selected by the profile manager.

## Multiple RetroAchievements profiles

Use **10) Manage player profiles** from the main installer menu (or execute `bash integrations/xerabora/profiles.sh`). Each household account has its own login token, API key, cache and logs under `~/.config/xerabora-profiles/<profile>/xerabora/`. Profile switching uses a **numbered selection** with 0 to return, requests confirmation, stops the running service, points it at the selected configuration, then starts it again. It prints a reminder to reboot/relaunch OPL-RA and select that player's memory-card image and save. **Only one account is active at a time.**

On an existing installation, player-menu option **2) Import an existing xeRAbora login** copies the original `~/.config/xerabora` credentials and key without removing them. Fresh users can choose **3) Add a new player**, then add a profile API key and activate it. You do not have to use RetroDB to use the profile manager; the import menu is specifically for legacy installations.

**Security:** Profiles are filesystem permission-protected, **not encrypted at rest**. Anyone with control of the Linux service account can read its saved tokens. Keep the VM and its backups private and do not commit credentials or API keys to Git.

Game saves are held by the PS2's actual/virtual memory cards, *not* by xeRAbora's Linux profiles; choose each player's correct save/card separately.

## Follow the active player's log live

When using multiple RetroAchievements profiles, logs move with the active account. To follow whichever player is currently selected (for example, `PoodingPower`), run:

```bash
PROFILE=$(cat ~/.config/xerabora-profiles/active)
tail -f ~/.config/xerabora-profiles/"$PROFILE"/xerabora/xerabora.log
```

This shows game identification, console connectivity, achievements, leaderboard events and snapshot statistics in real time. Press **Ctrl+C** to stop watching. If you switch players, rerun these commands so `PROFILE` reflects the new active account. For installations that have not yet activated a named profile, the original log is at `~/.config/xerabora/xerabora.log`.

## Troubleshooting

```bash
sudo systemctl status xerabora.service
sudo journalctl -u xerabora.service -n 80 --no-pager
bash integrations/xerabora/install.sh doctor
```

The logs live in `~/.config/xerabora/xerabora.log` for the original default account or in the active profile's `xerabora` directory. Being able to see UDP 18194 listening does not by itself prove that PS2 discovery works. Check that both devices share a broadcast domain and that no firewall is blocking traffic.

## Terminal menu and live log

Run `bash integrations/xerabora/install.sh` to open the main menu or `bash integrations/xerabora/profiles.sh` for player management. Both show the same ASCII banner, project link, service state, installed version, active profile and author/footer. The **main menu option 8** and **player menu option 7** follow the active player's log in real time; press **Ctrl+C** to stop viewing and return to the menu.

## Service startup, reboot delay and automatic recovery

The installer manages the `xerabora.service` systemd unit, including a **20-second startup delay** after network readiness and a **10-second restart interval** when automatic recovery is enabled. The main menu includes **13) Service startup / automatic recovery**:

| Mode | Boot | Unexpected exit | When selected |
| --- | --- | --- | --- |
| **Automatic** | Starts after network and delay | Restarts after 10 seconds (including a clean, unexpected process exit) | Starts the service if stopped |
| **Manual** | Does not start | No automatic restart | Leaves an already-running service alone |
| **Disabled** | Does not start | No automatic restart | Stops the service |

Automatic is the normal installation default. systemd `Restart=always` **does not restart after an intentional** `systemctl stop`. Manual and Disabled both disable boot-time activation; Disabled additionally stops the running service. Neither mode removes the application or accounts.

These choices are stored in the systemd drop-in at `/etc/systemd/system/xerabora.service.d/restart.conf`, separate from the profile switching drop-in, and preserved by future installer upgrades. Updating xeRAbora **respects the selected mode**: it won't unexpectedly start a disabled installation or a manually stopped installation.

To check settings and service status:

```bash
systemctl is-enabled xerabora.service
systemctl is-active xerabora.service
systemctl cat xerabora.service
```

After pulling the latest installer, run `bash integrations/xerabora/install.sh` and choose **13**, then **1** to apply automatic mode to an existing installation. This does not require a host reboot.

## Uninstalling

Choose **11) Uninstall xeRAbora and delete all local data** from the main menu, or run:

```bash
bash integrations/xerabora/install.sh uninstall
```

The command previews what will be deleted and requires typing the exact phrase `UNINSTALL XERABORA`. It then stops/disables the xeRAbora service, deletes its managed service unit and profile override, removes `/opt/xerabora`, deletes `~/.config/xerabora` and **all** profiles, credentials, keys, caches and logs under `~/.config/xerabora-profiles`. This deletion is irreversible. It does **not** remove Debian dependencies, change firewall rules, delete your RetroDB checkout, remove the ELF copied to the PS2 or clear the shared systemd journal (which would also affect other services). It refuses to remove a service unit that does not match this installer's xeRAbora executable path.

## Updating the community installer

If you cloned the full RetroDB repository:

```bash
cd ~/retrodb
git pull --ff-only origin main
bash integrations/xerabora/install.sh
```

If you copied the scripts to another directory, update those files using your original download method; the menu footer's `~/retrodb` command assumes a clone there.

The updater retains prior executable, OPL ELF and version files with `.previous` suffix for **manual** rollback. It does not implement automatic rollback. Releases are selected dynamically from upstream; nothing here guarantees compatibility with future xeRAbora releases.
