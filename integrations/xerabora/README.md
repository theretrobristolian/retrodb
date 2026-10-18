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
