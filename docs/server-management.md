# Server management (Settings)

RetroDB's authenticated **Settings** page (`/settings`) has three sections in order:
- **System information**: read-only hostname, IPv4 addresses, operating system, hardware classification (VM, Raspberry Pi or physical/unknown), manufacturer/model, uptime, logical CPU count, CPU utilisation, memory, system disk and mounted RetroNAS capacity.
- **Services**: xeRAbora's current systemd status and a confirmed restart button. Additional supported services may be added later.
- **Library management**: unchanged inventory and maintenance preview, linked at `/settings/library` (the old `/management` bookmark redirects there).

Utilisation and service status are **snapshots**, not a live poll. Press **Refresh** for updated values. The **Restart server** button is at the bottom of System information; **Restart xeRAbora** belongs to the Services card. Both retain the existing confirmation dialogs. The older `/settings/server` deep link displays the consolidated Settings page.

The second area is privileged. Being signed into RetroDB does **not** make an
account a server administrator. Guests cannot visit Settings.

## Manage permissions from the RetroDB terminal menu

Run `retrodb` on your Debian machine and choose **5) Permissions**. The
menu reads website usernames from `/etc/retrodb/web-users-app.htpasswd`:

```text
RetroDB | Permissions
Server management: restart xeRAbora / reboot Debian

  (x) alice
  ( ) bob
  ( ) charlie

  Confirm / Update
  Cancel
```

Use the arrow keys to highlight a username, **Space** (or Enter) to toggle
`(x)` on/off, then move to **Confirm / Update** and press Enter. The menu
displays which accounts will gain/lose server permissions and requires **Y**
before saving. Cancel/Escape/Q leaves the JSON file untouched.

The menu requires sudo authentication for permission changes, and uses the
root-owned installed script under `/opt/retrodb/server/server_permissions.py`
rather than executing a checkout file with elevated privileges. The
allowlist is written atomically to `/etc/retrodb/server-admins.json`.
There is no need to restart RetroDB after a permissions change. Accounts
that no longer exist in the web-login file are not newly granted access.

## Authorise an administrator

After deploying the updated code, create or edit the root-owned
`/etc/retrodb/server-admins.json` allowlist. Deployment creates this file with
`{"admins":[]}` on first run and preserves subsequent edits.

Use the exact **RetroDB web login** username (the name before the colon in
`/etc/retrodb/web-users-app.htpasswd`), **not** the Linux shell username or
RetroAchievements account unless they happen to match.

Example, replace `YOUR_RETRODB_LOGIN` with your actual web login:

```bash
sudo python3 - <<'PY'
import json
from pathlib import Path
path = Path("/etc/retrodb/server-admins.json")
data = json.loads(path.read_text())
data["admins"] = sorted(set(data.get("admins", []) + ["YOUR_RETRODB_LOGIN"]))
path.write_text(json.dumps(data, indent=2) + "\n")
PY
sudo chown root:retrodb /etc/retrodb/server-admins.json
sudo chmod 0640 /etc/retrodb/server-admins.json
```

Log out of RetroDB and sign in with that account, then open **Settings →
Server management**. No service restart is needed for allowlist changes.

## How the controls work

The web app checks the signed login cookie against the allowlist and validates
a short-lived CSRF token plus an explicit confirmation word. Neither button
submits a systemd unit name, shell command or file path.

The already existing restricted
`retrodb-xerabora-switch.socket` forwards approved requests from the
unprivileged `retrodb` service account to its root-owned helper. The helper
checks the administrator allowlist again and runs **only** these fixed actions:

- `systemctl --no-block restart xerabora.service` — requests a restart without
  waiting for a potentially hung xeRAbora process. Acknowledgement means the
  job was queued, not that the service is healthy.
- `systemd-run --unit=retrodb-web-reboot --on-active=10s /usr/bin/systemctl reboot`
  — schedules reboot after the browser response has been sent. All services
  temporarily disappear.

The helper logs approved actions and denied/failed requests to its journal.

## Verify and troubleshoot

```bash
systemctl status retrodb-xerabora-switch.socket --no-pager
systemctl status retrodb-xerabora-switch.service --no-pager
journalctl -u retrodb-xerabora-switch.service -n 50 --no-pager
systemctl status xerabora.service --no-pager
```

The socket can be active while the helper service is inactive; the service is
started automatically on the first connection. An unapproved web login sees a
restricted-information page without action buttons.

**Security note:** Do not add ordinary users to the admin allowlist. A server
reboot is a privileged, system-wide operation and cannot be undone remotely
once queued.
