#!/usr/bin/env bash
set -Eeuo pipefail
APP_USER=retrodb
APP_ROOT=/opt/retrodb
CONFIG_FILE=/etc/retrodb/retrodb.env
MOUNT_POINT=/mnt/retrodb-retronas
UNIT_NAME=$(systemd-escape --path --suffix=mount "$MOUNT_POINT")
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die 'Run this script with sudo or as root.'
case ${1:-} in
    status) systemctl status "$UNIT_NAME" --no-pager ;;
    mount)
        systemctl start "$UNIT_NAME"
        printf '[OK] RetroNAS share mounted read-only.\n'
        ;;
    unmount)
        systemctl stop "$UNIT_NAME"
        printf '[OK] RetroNAS share unmounted.\n'
        ;;
    scan)
        [[ -x "$APP_ROOT/.venv/bin/python" ]] || die 'RetroDB is not deployed.'
        mountpoint -q "$MOUNT_POINT" || die 'RetroNAS is not mounted. Run configure-retronas.sh first.'
        exec runuser -u "$APP_USER" -- \
            env PYTHONPATH="$APP_ROOT/backend" \
            "$APP_ROOT/.venv/bin/python" -m retrodb.cli \
            --env-file "$CONFIG_FILE" library-scan --root "$MOUNT_POINT"
        ;;
    *) die 'Usage: sudo bash server/retronas.sh {status|mount|unmount|scan}' ;;
esac
