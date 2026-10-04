#!/usr/bin/env bash
set -Eeuo pipefail

APP_USER=retrodb
APP_ROOT=/opt/retrodb
CONFIG_FILE=/etc/retrodb/retrodb.env

die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die 'Run this script with sudo or as root.'
[[ -x "$APP_ROOT/.venv/bin/python" ]] || die 'RetroDB is not deployed.'
[[ -r "$CONFIG_FILE" ]] || die 'RetroDB configuration is missing.'

case ${1:-} in
    test)
        [[ $# -eq 1 ]] || die 'Usage: sudo bash server/retroachievements.sh test'
        exec runuser -u "$APP_USER" -- \
            env PYTHONPATH="$APP_ROOT/backend" \
            "$APP_ROOT/.venv/bin/python" -m retrodb.cli \
            --env-file "$CONFIG_FILE" ra-test
        ;;
    sync)
        [[ $# -le 2 ]] || die 'Usage: sudo bash server/retroachievements.sh sync [--force]'
        [[ $# -eq 1 || ${2:-} == --force ]] || \
            die 'Usage: sudo bash server/retroachievements.sh sync [--force]'
        exec runuser -u "$APP_USER" -- \
            env PYTHONPATH="$APP_ROOT/backend" \
            "$APP_ROOT/.venv/bin/python" -m retrodb.cli \
            --env-file "$CONFIG_FILE" ra-sync ${2:+"$2"}
        ;;
    *)
        die 'Usage: sudo bash server/retroachievements.sh {test|sync [--force]}'
        ;;
esac
