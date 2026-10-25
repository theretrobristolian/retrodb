#!/usr/bin/env bash
# Opt-in privileged bridge. Intentionally NOT run by the main deploy script.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo' >&2; exit 1; }
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ -s /etc/retrodb/profile-links.json ]] || {
  echo '[ERROR] First configure at least one approved RetroDB/xeRAbora profile link.' >&2
  exit 1
}
[[ -f /etc/systemd/system/xerabora.service ]] || {
  echo '[ERROR] No xeRAbora systemd service found.' >&2
  exit 1
}
install -d -o root -g root -m 0755 /etc/systemd/system/xerabora.service.d
install -o root -g root -m 0644 "$ROOT/server/retrodb-xerabora-switch.socket" /etc/systemd/system/retrodb-xerabora-switch.socket
install -o root -g root -m 0644 "$ROOT/server/retrodb-xerabora-switch.service" /etc/systemd/system/retrodb-xerabora-switch.service
systemctl daemon-reload
systemctl enable --now retrodb-xerabora-switch.socket
echo '[OK] Restricted xeRAbora switch socket is enabled for authenticated RetroDB players.'
echo 'The web process retains NoNewPrivileges and no sudo privileges.'
