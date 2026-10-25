#!/usr/bin/env bash
# Opt-in boot reliability: leave the existing SMB .mount configuration unchanged.
set -Eeuo pipefail
MOUNT=/mnt/retrodb-retronas
[[ $EUID -eq 0 ]] || { echo 'Run using sudo.' >&2; exit 1; }
mount_unit="$(systemd-escape --path --suffix=mount "$MOUNT")"
auto_unit="$(systemd-escape --path --suffix=automount "$MOUNT")"
mount_file="/etc/systemd/system/$mount_unit"
auto_file="/etc/systemd/system/$auto_unit"
[[ -f "$mount_file" ]] || { echo "[ERROR] Missing $mount_file" >&2; exit 1; }
[[ ! -f "$auto_file" ]] || { echo "[INFO] Automount already configured at $auto_file"; exit 0; }
echo 'This enables an on-demand RetroNAS mount after boot.'
echo 'The existing SMB target, credentials, access mode and dialect are preserved.'
echo 'The current share may be briefly disconnected. Do not run during an audit.'
read -rp 'Proceed? [y/n] (default: no) ' answer
[[ "$answer" =~ ^[Yy]$ ]] || exit 0
# Write the new unit first; do not modify or expose credentials.
cat > "$auto_file" <<EOF
[Unit]
Description=RetroDB on-demand RetroNAS automount
Wants=network-online.target
After=network-online.target

[Automount]
Where=$MOUNT
TimeoutIdleSec=0

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$auto_file"
systemctl daemon-reload
# Stop the old boot-mounted unit before enabling the automount point.
# A busy mount will refuse to stop; avoid forcing it.
if ! systemctl stop "$mount_unit"; then
  echo '[ERROR] RetroNAS is in use; could not stop existing mount.'
  echo "        No boot configuration changed. Retry when idle."
  rm -f "$auto_file"
  systemctl daemon-reload
  exit 1
fi
if ! systemctl enable --now "$auto_unit"; then
  echo '[ERROR] Could not start the automount. Existing .mount unit is retained.'
  systemctl disable "$auto_unit" 2>/dev/null || true
  rm -f "$auto_file"
  systemctl daemon-reload
  systemctl start "$mount_unit" || true
  exit 1
fi
systemctl disable "$mount_unit" >/dev/null
echo '[OK] RetroNAS now mounts on first access, instead of requiring DNS during boot.'
echo "     Check: systemctl status '$auto_unit'"
