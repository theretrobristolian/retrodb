#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

# RetroDB idempotent server bootstrap.
# Primary: Debian Stable. Secondary: Ubuntu Server LTS.

APP_USER=retrodb
APP_GROUP=retrodb
APP_ROOT=/opt/retrodb
CONFIG_DIR=/etc/retrodb
DATA_DIR=/var/lib/retrodb
CACHE_DIR=/var/cache/retrodb
LOG_DIR=/var/log/retrodb
BACKUP_DIR=/var/backups/retrodb
CHECK_ONLY=false

log()  { printf '[+] %s\n' "$*"; }
warn() { printf '[!] %s\n' "$*" >&2; }
die()  { printf '[ERROR] %s\n' "$*" >&2; exit 1; }
trap 'die "Bootstrap failed at line $LINENO."' ERR

usage() {
    printf '%s\n' 'Usage: sudo bash server/build.sh [--check] [--help]'
    printf '%s\n' '  --check  Validate the host without changing it.'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check) CHECK_ONLY=true ;;
        --help|-h) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
    shift
done

[[ $EUID -eq 0 ]] || die 'Run this script with sudo or as root.'
[[ -r /etc/os-release ]] || die 'Cannot identify the operating system.'
# shellcheck disable=SC1091
source /etc/os-release

case "$ID" in
    debian) log "Detected Debian $VERSION_ID." ;;
    ubuntu) log "Detected Ubuntu $VERSION_ID." ;;
    *) die "Unsupported OS: $ID. Use Debian Stable or Ubuntu Server LTS." ;;
esac

command -v apt-get >/dev/null || die 'APT is required.'
command -v systemctl >/dev/null || die 'systemd is required.'
[[ -d /run/systemd/system ]] || die 'systemd is not running.'

PACKAGES=(ca-certificates curl git jq postgresql python3 python3-pip python3-venv)

if [[ $CHECK_ONLY == true ]]; then
    missing=()
    for package in "${PACKAGES[@]}"; do
        dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed' || missing+=("$package")
    done
    ((${#missing[@]})) && warn "Missing packages: ${missing[*]}" || log 'All base packages are installed.'
    getent passwd "$APP_USER" >/dev/null || warn "Service account $APP_USER does not exist."
    [[ -d $CONFIG_DIR ]] || warn "Missing $CONFIG_DIR"
    [[ -d $DATA_DIR ]] || warn "Missing $DATA_DIR"
    log 'Check complete; no changes were made.'
    exit 0
fi

export DEBIAN_FRONTEND=noninteractive
log 'Refreshing APT package metadata...'
apt-get update
log 'Installing base dependencies...'
apt-get install -y --no-install-recommends "${PACKAGES[@]}"

if ! getent group "$APP_GROUP" >/dev/null; then
    log "Creating service group $APP_GROUP..."
    groupadd --system "$APP_GROUP"
fi

if ! getent passwd "$APP_USER" >/dev/null; then
    log "Creating unprivileged service account $APP_USER..."
    useradd --system --gid "$APP_GROUP" --home-dir "$APP_ROOT" --shell /usr/sbin/nologin --comment 'RetroDB service account' "$APP_USER"
fi

log 'Creating and repairing application directories...'
install -d -o root -g "$APP_GROUP" -m 0750 "$APP_ROOT" "$CONFIG_DIR" "$BACKUP_DIR"
install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$DATA_DIR" "$CACHE_DIR" "$LOG_DIR"

if [[ ! -f $CONFIG_DIR/retrodb.env ]]; then
    log 'Creating protected environment-file placeholder...'
    install -o root -g "$APP_GROUP" -m 0640 /dev/null "$CONFIG_DIR/retrodb.env"
    printf '%s\n' '# RetroDB local configuration' 'RETRODB_ENV=production' > "$CONFIG_DIR/retrodb.env"
fi

log 'Restricting PostgreSQL to loopback interfaces...'
if command -v pg_lsclusters >/dev/null && command -v pg_conftool >/dev/null; then
    while read -r version cluster rest; do
        [[ -n $version && -n $cluster ]] || continue
        pg_conftool "$version" "$cluster" set listen_addresses localhost
    done < <(pg_lsclusters --no-header 2>/dev/null || true)
else
    warn 'PostgreSQL cluster tools not found; inspect listen_addresses manually.'
fi

systemctl enable postgresql
systemctl restart postgresql
systemctl is-active --quiet postgresql || die 'PostgreSQL did not start.'

log 'RetroDB base host preparation is complete.'
printf '  Application root : %s\n  Configuration    : %s\n  Data             : %s\n' "$APP_ROOT" "$CONFIG_DIR" "$DATA_DIR"
warn 'The application, schema, HTTPS and web service are not implemented yet.'
warn 'No network-facing service has been enabled.'
