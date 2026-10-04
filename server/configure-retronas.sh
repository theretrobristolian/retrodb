#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
APP_USER=retrodb
APP_GROUP=retrodb
MOUNT_POINT=/mnt/retrodb-retronas
CREDENTIAL_FILE=/etc/retrodb/retronas.credentials
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die 'Run this script with sudo or as root.'
command -v mount.cifs >/dev/null || die 'CIFS support is missing; run sudo bash server/build.sh first.'
getent passwd "$APP_USER" >/dev/null || die 'RetroDB service account is missing.'
printf 'RetroNAS DNS name or IP: '
read -r server
[[ $server =~ ^[A-Za-z0-9._:-]+$ ]] || die 'Invalid server name or address.'
printf 'SMB share [retronas]: '
read -r share
share=${share:-retronas}
[[ $share =~ ^[A-Za-z0-9._\$-]+$ ]] || die 'Invalid SMB share name.'
printf 'SMB username [pi]: '
read -r username
username=${username:-pi}
[[ -n $username ]] || die 'Invalid username.'
printf 'SMB password: '
read -r -s password
printf '\n'
[[ -n $password ]] || die 'A password is required.'
install -d -o root -g root -m 0755 "$MOUNT_POINT"
{
    printf 'username=%s\n' "$username"
    printf 'password=%s\n' "$password"
} > "$CREDENTIAL_FILE"
chown root:root "$CREDENTIAL_FILE"
chmod 0600 "$CREDENTIAL_FILE"
unset password
unit_name=$(systemd-escape --path --suffix=mount "$MOUNT_POINT")
unit_path="/etc/systemd/system/$unit_name"
cat > "$unit_path" <<EOF
[Unit]
Description=RetroDB read-only RetroNAS collection
After=network-online.target
Wants=network-online.target

[Mount]
What=//$server/$share
Where=$MOUNT_POINT
Type=cifs
Options=ro,credentials=$CREDENTIAL_FILE,vers=3.1.1,iocharset=utf8,uid=$APP_USER,gid=$APP_GROUP,file_mode=0440,dir_mode=0550,nosuid,nodev,noexec,_netdev
TimeoutSec=30

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$unit_path"
printf '[RUN] Connecting to RetroNAS read-only...\n'
systemctl daemon-reload
systemctl enable "$unit_name" >/dev/null
if ! systemctl restart "$unit_name"; then
    printf '[FAILED] Could not mount //%s/%s.\n' "$server" "$share" >&2
    systemctl status "$unit_name" --no-pager --full >&2 || true
    exit 1
fi
mountpoint -q "$MOUNT_POINT" || die 'Mount command completed but the share is not mounted.'
printf '[OK] RetroNAS is mounted read-only at %s.\n' "$MOUNT_POINT"
printf '[+] Credentials are protected at %s (root-only).\n' "$CREDENTIAL_FILE"
printf '[+] Next: sudo bash server/retronas.sh scan\n'
