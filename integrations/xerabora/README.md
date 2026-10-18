# xeRAbora headless client for RetroDB

Standalone install and manual updater for [xeRAbora](https://github.com/hacan359/xerabora), which connects PS2 OPL-RA to RetroAchievements. RetroDB's existing services, Python environment, PostgreSQL and ROM collection are unchanged.

## On Debian 13 RetroDB

```bash
cd ~/retrodb
git pull --ff-only origin main
bash integrations/xerabora/install.sh check
bash integrations/xerabora/install.sh
```

Run as the normal `david` account, **not** `sudo bash`. Requires sudo, curl, Python 3, sha256sum and systemd. Installation prompts before making changes. On first installation it offers a one-time interactive RetroAchievements login. After login is complete, press Ctrl+C if the program stays running. Password is only provided to that child process for login and is not written to a configuration file by the installer.

## Version checking and updates

```bash
bash integrations/xerabora/install.sh check     # installed versus newest upstream release
bash integrations/xerabora/install.sh update    # ask to download, verify, install and restart
bash integrations/xerabora/install.sh doctor    # addresses, routes, UDP listener, service and logs
bash integrations/xerabora/install.sh status
bash integrations/xerabora/install.sh logs
bash integrations/xerabora/install.sh restart
```

The updater queries GitHub's **releases list**, not `/releases/latest`, because xeRAbora publishes *pre-releases*. It chooses the newest published non-draft release containing Linux, PS2 ELF and SHA256SUMS assets. For both files it checks the SHA256 against the matching release's manifest **before changing the installed files**. The managed version is recorded at `/opt/xerabora/VERSION`. Existing executable, ELF and VERSION are backed up with `.previous` suffix for manual rollback. The authentication data at `~/.config/xerabora` is preserved. Updates are manual, never automatic.

**Important:** A new xeRAbora release may require the matching `OPL-RA.ELF` on your PS2. The script downloads it to `/opt/xerabora/OPL-RA.ELF`; you must copy it to your console boot medium yourself. Updating the VM does not update the console.

## Network

The VM and PS2 should share a subnet/broadcast domain. xeRAbora receives console discovery on **UDP 18194**. The doctor command checks the local listener, addresses, routes, firewall status and log, but a listening UDP port alone does not prove the PS2 can communicate. From OPL-RA use **Triangle > RA: test PC connection**, followed by **RA: check game support** for each game before playing. The installer does **not** change firewall rules.

The upstream application remains experimental alpha software. These scripts have not yet been exercised on your actual Debian VM. Check the systemd journal if the service cannot start. The installer does not perform automatic rollback on failure.


## Interactive manager (default)

Run `bash integrations/xerabora/install.sh` without arguments for a menu that shows the installed and newest upstream versions, service status and whether the Web API key exists. Press Enter to install/update, or select API-key setup, API test, service status/restart, network/port diagnostics, logs, login or exit.

From the CLI you can also use:

```bash
bash integrations/xerabora/install.sh api-key
bash integrations/xerabora/install.sh test-api
bash integrations/xerabora/install.sh menu
```

Web API key entry is hidden in the terminal, saved to `/home/david/.config/xerabora/apikey` with file permissions 0600, and the service is restarted to load it. A pre-existing key is preserved unless replacement is confirmed. The presence check is not a validity check: `test-api` uses the upstream `--recent` command to test the key. Never paste API keys into GitHub or chat.

## PS2 / MemCard Pro reminder

**Fully power-cycle/reboot the PS2 before copying the ELF** so that MemCard Pro restores the default memory-card-slot-1 image you intend to edit. In wLaunchELF, copy the USB `mass:/APPS/OPL-RA.ELF` to the chosen card location (for example `mc0:/APPS/OPL-RA.ELF`), then add that exact executable path in the Free McBoot Configurator and save the FMCB configuration. You may test the ELF directly from USB first. Check that the destination card image has enough free space and is the correct MemCard Pro virtual card before copying.
