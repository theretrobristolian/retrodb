# xeRAbora for RetroDB

Standalone headless [xeRAbora](https://github.com/hacan359/xerabora) client for RetroAchievements on a real PS2. This installer **does not change RetroDB services, PostgreSQL, Python or ROMs**.

## One-command setup

On your Debian 13 x86_64 RetroDB host, from the cloned repo:

```bash
cd ~/retrodb/integrations/xerabora
bash install.sh
```

Run as the normal `david` user, **not** with `sudo bash`. Requires sudo, curl, sha256sum, systemd, ss/iproute2. It installs the pinned, checksum-verified upstream **v0.1.0-alpha.18** executable into `/opt/xerabora`, downloads the matching `OPL-RA.ELF`, creates an auto-start systemd service, and offers a one-time RetroAchievements password prompt. After the initial login saves a token, press Ctrl+C to return to the installer. Password is not written to disk by this script.

## Useful commands

```bash
bash install.sh doctor   # IP, route, UDP 18194 listener, firewall hints, service and log
bash install.sh login    # authenticate again
bash install.sh status
bash install.sh logs
bash install.sh restart
bash install.sh update   # reinstall same pinned version
```

The service runs as the installing user; config and logs live at `~/.config/xerabora/`. Note a directory alone is not proof of successful login; review logs if authentication failed.

## PS2 connection

Move the downloaded `/opt/xerabora/OPL-RA.ELF` onto the PS2 launch device; use this matching release. Host and console must share the same broadcast network (not merely IP-routable between VLANs). In OPL-RA select a game, press Triangle, run **RA: test PC connection**, then **RA: check game support** before playing. Inbound **UDP 18194** must be allowed from PS2 to RetroDB. The doctor command is read-only: it doesn't open firewall rules. `ss` detects a listening socket but cannot guarantee UDP broadcasts work; the PS2 connection-test option is authoritative. If your VLAN40 subnet is confirmed to be 10.1.4.0/24 and UFW is enabled, you may allow only this subnet with `sudo ufw allow from 10.1.4.0/24 to any port 18194 proto udp`.

Upstream is experimental alpha software. **Not tested on your live VM or PS2.** Review shell scripts before executing, and never commit credentials.
