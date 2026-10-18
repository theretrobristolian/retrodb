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

The repository is used only to distribute two shell scripts and documentation; **no other RetroDB installation step is required**. If prerequisites are missing, the script can offer to install required Debian packages through apt, using sudo; it never silently grants sudo access. If you prefer to copy only the `integrations/xerabora/` directory to another machine, both `install.sh` and `profiles.sh` must remain together. You can also download those two files manually; `git` is not required after the download.

The manager (default with no arguments) offers installation/update, version check, Web API key setup, API test, service status/restart, network diagnostics, logs, login and numbered multi-account switching. Choose **1) Install / update**. The installer queries the xeRAbora GitHub *releases list*, including pre-releases, downloads `xerabora-linux-x86_64`, `OPL-RA.ELF` and `SHA256SUMS`, and validates both assets against the release checksums before installation. It installs to `/opt/xerabora`, configures and enables `xerabora.service`, then offers initial RetroAchievements login. Type your password only at the hidden prompt. The client stores an account **token**, not your password.

Configure a **RetroAchievements Web API key** from https://retroachievements.org/settings (Keys) via menu option **2**. The key is saved as a permission-protected file. Accounts require independent keys. The manager can test API access with option **3**.

## PS2 setup (manual)

The downloaded matching PS2 executable is **`/opt/xerabora/OPL-RA.ELF`**. Copy it to a USB drive or other console-accessible medium, then configure your PS2 to launch it (e.g., wLaunchELF / Free McBoot). Replace this ELF when updating to a release that changes the OPL-RA build; the installer does not update the PS2 remotely.

Example from a second computer:

```bash
scp YOUR_LINUX_USERNAME@YOUR_VM_IP:/opt/xerabora/OPL-RA.ELF .
```

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

## Multiple RetroAchievements profiles

Use **9) Manage RetroAchievements profiles** from the main installer menu (or execute `bash integrations/xerabora/profiles.sh`). Each household account has its own login token, API key, cache and logs under `~/.config/xerabora-profiles/<profile>/xerabora/`. Profile switching uses a **numbered selection** with 0 to return, requests confirmation, stops the running service, points it at the selected configuration, then starts it again. It prints a reminder to reboot/relaunch OPL-RA and select that player's memory-card image and save. **Only one account is active at a time.**

On an existing installation, menu option **2) Import existing RetroDB login** copies the original `~/.config/xerabora` credentials and key without removing them. Fresh users can choose **3) Create another account profile**, then add a profile API key and activate it. You do not have to use RetroDB to use the profile manager; the import menu is specifically for legacy installations.

**Security:** Profiles are filesystem permission-protected, **not encrypted at rest**. Anyone with control of the Linux service account can read its saved tokens. Keep the VM and its backups private and do not commit credentials or API keys to Git.

Game saves are held by the PS2's actual/virtual memory cards, *not* by xeRAbora's Linux profiles; choose each player's correct save/card separately.

## Troubleshooting

```bash
sudo systemctl status xerabora.service
sudo journalctl -u xerabora.service -n 80 --no-pager
bash integrations/xerabora/install.sh doctor
```

The logs live in `~/.config/xerabora/xerabora.log` for the original default account or in the active profile's `xerabora` directory. Being able to see UDP 18194 listening does not by itself prove that PS2 discovery works. Check that both devices share a broadcast domain and that no firewall is blocking traffic.

The updater retains prior executable, OPL ELF and version files with `.previous` suffix for **manual** rollback. It does not implement automatic rollback. Releases are selected dynamically from upstream; nothing here guarantees compatibility with future xeRAbora releases.
