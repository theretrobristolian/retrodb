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
SOURCE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
CHECK_ONLY=false
VERBOSE=false

log()  { printf '[+] %s\n' "$*"; }
warn() { printf '[!] %s\n' "$*" >&2; }
die()  { printf '[ERROR] %s\n' "$*" >&2; exit 1; }
trap 'die "Unexpected failure at line $LINENO."' ERR

usage() {
    printf '%s\n' 'Usage: sudo bash server/build.sh [--check] [--verbose] [--help]'
    printf '%s\n' '  --check    Validate the host without changing it.'
    printf '%s\n' '  --verbose  Stream the underlying command output.'
}

run_step() {
    local description=$1
    shift
    printf '[RUN] %s...\n' "$description"

    if [[ $VERBOSE == true ]]; then
        if "$@"; then
            printf '[OK]  %s\n' "$description"
            return 0
        fi
    else
        local output_file
        output_file=$(mktemp /tmp/retrodb-build.XXXXXX)
        if "$@" >"$output_file" 2>&1; then
            rm -f "$output_file"
            printf '[OK]  %s\n' "$description"
            return 0
        fi
        printf '[FAILED] %s\n\n' "$description" >&2
        cat "$output_file" >&2
        rm -f "$output_file"
    fi

    trap - ERR
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check) CHECK_ONLY=true ;;
        --verbose) VERBOSE=true ;;
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

PACKAGES=(ca-certificates cifs-utils curl unzip git jq postgresql python3 python3-pip python3-venv rsync xdelta3)

if [[ $CHECK_ONLY == true ]]; then
    missing=()
    for package in "${PACKAGES[@]}"; do
        dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed' || missing+=("$package")
    done
    ((${#missing[@]})) && warn "Missing packages: ${missing[*]}" || log 'All base packages are installed.'
    getent passwd "$APP_USER" >/dev/null || warn "Service account $APP_USER does not exist."
    [[ -d $CONFIG_DIR ]] || warn "Missing $CONFIG_DIR"
    [[ -d $DATA_DIR ]] || warn "Missing $DATA_DIR"
    [[ -x /opt/retrodb-tools/RAHasher ]] || warn "RAHasher is not installed."
    if command -v systemctl >/dev/null && systemctl is-active --quiet postgresql; then
        log 'PostgreSQL is running.'
    elif dpkg-query -W postgresql >/dev/null 2>&1; then
        warn 'PostgreSQL is installed but not running.'
    fi
    log 'Check complete; no changes were made.'
    exit 0
fi

export DEBIAN_FRONTEND=noninteractive
run_step 'Refreshing APT package metadata' apt-get update
run_step 'Installing base dependencies' apt-get install -y --no-install-recommends "${PACKAGES[@]}"

if ! getent group "$APP_GROUP" >/dev/null; then
    run_step "Creating service group $APP_GROUP" groupadd --system "$APP_GROUP"
else
    log "Service group $APP_GROUP already exists."
fi

if ! getent passwd "$APP_USER" >/dev/null; then
    run_step "Creating service account $APP_USER" useradd --system --gid "$APP_GROUP" --home-dir "$APP_ROOT" --shell /usr/sbin/nologin --comment 'RetroDB service account' "$APP_USER"
else
    log "Service account $APP_USER already exists."
fi

run_step 'Creating application directories' install -d -o root -g "$APP_GROUP" -m 0750 "$APP_ROOT" "$CONFIG_DIR" "$BACKUP_DIR"
run_step 'Creating writable data directories' install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$DATA_DIR" "$CACHE_DIR" "$LOG_DIR"
run_step 'Installing verified RetroAchievements hash engine' bash "$SOURCE_ROOT/server/install-rahasher.sh"

if [[ ! -f $CONFIG_DIR/retrodb.env ]]; then
    run_step 'Creating protected configuration file' install -o root -g "$APP_GROUP" -m 0640 /dev/null "$CONFIG_DIR/retrodb.env"
    printf '%s\n' '# RetroDB local configuration' 'RETRODB_ENV=production' > "$CONFIG_DIR/retrodb.env"
else
    log 'Protected configuration file already exists.'
fi

configure_postgresql() {
    if command -v pg_lsclusters >/dev/null && command -v pg_conftool >/dev/null; then
        while read -r version cluster rest; do
            [[ -n $version && -n $cluster ]] || continue
            pg_conftool "$version" "$cluster" set listen_addresses localhost
        done < <(pg_lsclusters --no-header 2>/dev/null || true)
    else
        return 1
    fi
}

run_step 'Restricting PostgreSQL to loopback' configure_postgresql
run_step 'Enabling PostgreSQL at boot' systemctl enable postgresql
run_step 'Restarting PostgreSQL' systemctl restart postgresql
systemctl is-active --quiet postgresql || die 'PostgreSQL did not start.'

printf '\n'
log 'RetroDB base host preparation is complete.'
printf '  Application root : %s\n  Configuration    : %s\n  Data             : %s\n' "$APP_ROOT" "$CONFIG_DIR" "$DATA_DIR"
printf '\n'
log 'Host prerequisites are ready.'
log 'Run server/deploy.sh to install or update the application.'
warn 'No network-facing service is enabled by the host bootstrap.'
