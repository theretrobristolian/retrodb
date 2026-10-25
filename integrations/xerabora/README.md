## Recovery after an incompatible Linux CPU build (October 2026)

**Temporary upstream release block:** On CPUs identified as Intel Celeron J6412 or without both AVX and AVX2, the installer explicitly refuses upstream `v1.0.0` **before downloading or touching the working service**. The release-check menu reports it as blocked rather than recommending installation. This is in addition to executable ISA preflight and rollback safeguards. Later versions are not automatically blocked; they must pass the binary preflight before replacing anything. Remove or revise the v1.0.0 block only after a compatible upstream build is verified. The currently working `v0.1.0-alpha.19` and the `PoodingPower` profile should be left untouched.


The v1.0.0 x86-64 executable failed on a Debian 13 VM with an Intel Celeron J6412, reporting `CPU ISA level is lower than required`. Host CPU passthrough did **not** add missing AVX/AVX2 instructions. The previously installed executable worked.

To restore without deleting profiles:

```bash
cd ~/retrodb && git pull --ff-only
bash integrations/xerabora/rollback.sh
# Or open 'xerabora' → Advanced options → Rollback.
```

Rollback requires all three backed-up files under `/opt/xerabora`: `xerabora-linux-x86_64.previous`, `OPL-RA.ELF.previous` and `VERSION.previous`. It confirms the old version, stops the service, saves the failed files separately, restores the previous files, removes `--server` from the previous service's ExecStart, reloads systemd, waits through ExecStartPre, then checks the active service. It does **not** touch the saved player profiles, credentials, log files or systemd profile/auto-restart drop-ins. If these previous files are absent, it refuses rather than guessing.

New updates now run a bounded executable/ISA preflight *before* installing the downloaded binary. A detected unsupported ISA or illegal instruction prevents replacement. The installer also retains the old systemd unit and automatically restores previous files/unit when its post-upgrade service check fails. These checks reduce risk but aren't a guarantee against all runtime regressions; inspect `journalctl -u xerabora.service` if the service becomes unstable later.

## xeRAbora v1.0.0+ persistent server mode

As of upstream [v1.0.0](https://github.com/hacan359/xerabora/releases/tag/v1.0.0), xeRAbora supports `--server`. The client otherwise exits roughly 15 seconds after its last browser page closes. The RetroDB installer now adds `--server` to the **systemd service** only for stable v1.0.0 and newer versions, preserving `--no-sound`, the Web UI options, existing profiles and service recovery settings. Pre-v1 builds continue to run without the new flag.

Run `xerabora` → **Install/update** after updating RetroDB. Even when the v1.x binary is already current, the installer checks and repairs the existing systemd ExecStart and restarts an active service when necessary. To inspect the setting:

```bash
systemctl cat xerabora.service
systemctl show xerabora.service -p ExecStart
systemctl is-active xerabora.service
journalctl -u xerabora.service -n 40 --no-pager
```

Expected v1.x ExecStart includes `--server` alongside `--ui-port 18280` or `--no-ui`. This changes only the background service launch, not the one-off interactive login command. A PS2/OPL-RA reconnect or restart may still be needed after upgrading the binary.

# xeRAbora — standalone Debian headless installation

Community installer, updater and multi-account manager for [xeRAbora](https://github.com/hacan359/xerabora) and its matching PS2 `OPL-RA.ELF`. Maintained in the [RetroDB](https://github.com/theretrobristolian/retrodb) repository, but **RetroDB is not required**: no PostgreSQL, Python RetroDB application, RetroNAS, database, ROM scanner or existing VM image is involved.

**Status:** The xeRAbora client has been exercised successfully on a Debian 13 VM connected to a real UK PAL PS2 Slim, including game identification and achievement notifications for *Crash of the Titans* and *The Lord of the Rings: The Return of the King*. Multi-account switching has now been tested on the existing Debian VM: two separate RetroAchievements profiles were activated successfully, and the browser dashboard displayed the selected account while tracking live PS2 gameplay and achievement progress. Service auto-start and the 20-second pre-start delay have also been observed running on that VM. A clean, fresh-machine end-to-end install has **not** yet been tested. Upstream xeRAbora remains alpha software.

The full-repository xeRAbora installer now registers `xerabora` and `xeRAbora` automatically after a successful installation or when confirming the installed version is already current. The confirmation tells you the command to type. Copying only the standalone xeRAbora scripts remains supported, but that minimal layout omits the shared launcher helper.

## Optional global terminal command

From a full RetroDB checkout, run `bash server/install-launchers.sh` as your normal Linux user. It installs `/usr/local/bin/xerabora` and an equivalent mixed-case `xeRAbora` command. You can then type `xerabora` anywhere to open the same installer/profile management menu. The launchers refer to the current checkout, so `git pull` updates their behaviour; do not move or delete the checkout without rerunning the launcher installer.

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

The manager clears the terminal and shows a consistent banner, xeRAbora version, service status, active RetroAchievements player, local/LAN/DNS dashboard URLs, CPU compatibility warning and community footer. The footer now says `Launch manager: xerabora (automatically checks for script updates)`, not a manual `git pull` command.

**Current main menu:** 1) Switch player; 2) Manage players (add/import/credentials); 3) Follow game and achievement log; 4) Service controls; 5) Check/install xeRAbora binary (may restart service); 6) Update RetroDB manager scripts (no service restart); 7) Advanced options; 0) Exit. Rarely used features such as rollback, uninstall and diagnostics are under Advanced options. Player switching is numbered, displays the active profile and asks for confirmation before restarting the service; save your PS2 game first and reconnect OPL-RA afterwards. Confirmation prompts use `[y/n]` with an explicit default.

**Two independent update paths:** Opening the `xerabora` launcher from a clean trusted `main` Git checkout checks for and fast-forwards *community manager scripts only*. It does not replace the installed xeRAbora binary or restart the service. Option 5 is a separate, manual binary-install/update workflow; it checks GitHub releases, validates downloaded assets/checksums, enforces CPU/ISA preflight and maintains rollback safeguards. In particular, upstream `v1.0.0` is blocked on the Intel Celeron J6412 environment where it failed, and the working `v0.1.0-alpha.19` must not be silently upgraded.

Configure a per-player RetroAchievements Web API key via **2) Manage players**. Obtain the key at https://retroachievements.org/settings (Keys) and keep it private.

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

Use **2) Manage players** from the main installer menu (or execute `bash integrations/xerabora/profiles.sh`). Each household account has its own login token, API key, cache and logs under `~/.config/xerabora-profiles/<profile>/xerabora/`. Profile switching uses a **numbered selection** with 0 to return, requests confirmation, stops the running service, points it at the selected configuration, then starts it again. It prints a reminder to reboot/relaunch OPL-RA and select that player's memory-card image and save. **Only one account is active at a time.**

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

Run `bash integrations/xerabora/install.sh` to open the main menu or `bash integrations/xerabora/profiles.sh` for player management. Both show the same ASCII banner, project link, service state, installed version, active profile and author/footer. **Main menu option 3** follows the active player's log in real time; press **Ctrl+C** to stop viewing and return to the menu.

## Service startup, reboot delay and automatic recovery

The installer manages the `xerabora.service` systemd unit, including a **20-second startup delay** after network readiness and a **10-second restart interval** when automatic recovery is enabled. Use **4) Service controls** (and related advanced options) to configure service startup / automatic recovery:

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

## Future security improvement: dedicated service account

The installer currently runs xeRAbora as the normal Linux user who installs it; that account owns the protected RetroAchievements login tokens, API keys, cache and log files. A future hardening enhancement would support an optional dedicated, unprivileged systemd service account with no interactive shell or sudo rights. This would require careful ownership and permission management for all player profiles, plus a safe migration path for existing installations. **This is planned, not implemented:** do not change the service user manually without first migrating the profile directories and confirming profile switching still works. No service-account changes are necessary for the current working setup.

## Uninstalling

Use **7) Advanced options** for uninstall or run:

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

For a clean trusted Git checkout, running `xerabora` checks and updates the community scripts automatically. If you copied standalone scripts without the full Git checkout, update them using your original download method.

The updater retains prior executable, OPL ELF and version files with `.previous` suffix for **manual** rollback. It includes rollback safeguards during a failed installation and supports an explicit manual rollback using the previous files. Releases are selected dynamically from upstream; nothing guarantees compatibility with future xeRAbora releases.
