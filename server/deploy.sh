#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

APP_USER=retrodb
APP_GROUP=retrodb
APP_ROOT=/opt/retrodb
CONFIG_FILE=/etc/retrodb/retrodb.env
SERVICE_FILE=/etc/systemd/system/retrodb.service
SOURCE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
VERBOSE=false

log()  { printf '[+] %s\n' "$*"; }
die()  { printf '[ERROR] %s\n' "$*" >&2; exit 1; }
trap 'die "Unexpected deployment failure at line $LINENO."' ERR

run_step() {
    local description=$1
    shift
    printf '[RUN] %s...\n' "$description"
    if [[ $VERBOSE == true ]]; then
        if "$@"; then printf '[OK]  %s\n' "$description"; return 0; fi
    else
        local output_file
        output_file=$(mktemp /tmp/retrodb-deploy.XXXXXX)
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

[[ ${1:-} == --verbose ]] && VERBOSE=true
[[ $# -le 1 ]] || die 'Usage: sudo bash server/deploy.sh [--verbose]'
[[ $EUID -eq 0 ]] || die 'Run this script with sudo or as root.'
command -v rsync >/dev/null || die 'rsync is missing; run sudo bash server/build.sh first.'
command -v psql >/dev/null || die 'PostgreSQL is missing; run sudo bash server/build.sh first.'
getent passwd "$APP_USER" >/dev/null || die 'RetroDB service account is missing.'

if ! grep -q '^RETRODB_DATABASE_URL=' "$CONFIG_FILE" 2>/dev/null; then
    DB_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
    DATABASE_URL="postgresql+psycopg://retrodb:$DB_PASSWORD@/retrodb?host=/var/run/postgresql"
    printf 'RETRODB_DATABASE_URL=%s\n' "$DATABASE_URL" >> "$CONFIG_FILE"
    chown root:"$APP_GROUP" "$CONFIG_FILE"
    chmod 0640 "$CONFIG_FILE"
    NEW_DATABASE_PASSWORD=true
else
    DATABASE_URL=$(sed -n 's/^RETRODB_DATABASE_URL=//p' "$CONFIG_FILE" | tail -n 1)
    DB_PASSWORD=
    NEW_DATABASE_PASSWORD=false
fi

provision_database() {
    if [[ $NEW_DATABASE_PASSWORD == true ]]; then
        runuser -u postgres -- psql --set=ON_ERROR_STOP=1 --set=role_password="$DB_PASSWORD" postgres <<'SQL'
SELECT format('CREATE ROLE retrodb LOGIN PASSWORD %L', :'role_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'retrodb') \gexec
SELECT format('ALTER ROLE retrodb LOGIN PASSWORD %L', :'role_password') \gexec
SQL
    elif ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='retrodb'" | grep -q 1; then
        printf 'Database role is missing but no new password was generated.\n' >&2
        return 1
    fi

    runuser -u postgres -- psql --set=ON_ERROR_STOP=1 postgres <<'SQL'
SELECT 'CREATE DATABASE retrodb OWNER retrodb'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'retrodb') \gexec
SQL
}

sync_application() {
    rsync -a --delete \
        --exclude='.git/' \
        --exclude='.venv/' \
        --exclude='__pycache__/' \
        --exclude='.pytest_cache/' \
        "$SOURCE_ROOT/" "$APP_ROOT/"
    chown -R root:"$APP_GROUP" "$APP_ROOT"
    chmod 0750 "$APP_ROOT"
}

run_step 'Provisioning PostgreSQL database and role' provision_database
run_step 'Synchronising application files' sync_application
run_step 'Creating Python virtual environment' python3 -m venv "$APP_ROOT/.venv"
run_step 'Installing Python dependencies' "$APP_ROOT/.venv/bin/pip" install --disable-pip-version-check --requirement "$APP_ROOT/requirements.txt"
run_step 'Applying Python environment ownership' chown -R root:"$APP_GROUP" "$APP_ROOT/.venv"
run_step 'Applying Python environment permissions' chmod -R g+rX "$APP_ROOT/.venv"
run_step 'Applying database migrations' runuser -u "$APP_USER" -- env RETRODB_DATABASE_URL="$DATABASE_URL" "$APP_ROOT/.venv/bin/alembic" -c "$APP_ROOT/alembic.ini" upgrade head
run_step 'Installing systemd service' install -o root -g root -m 0644 "$APP_ROOT/server/retrodb.service" "$SERVICE_FILE"
run_step 'Reloading systemd' systemctl daemon-reload
run_step 'Enabling RetroDB at boot' systemctl enable retrodb.service
run_step 'Restarting RetroDB' systemctl restart retrodb.service
run_step 'Checking RetroDB service' systemctl is-active --quiet retrodb.service
run_step 'Checking application health' curl --fail --silent --show-error http://127.0.0.1:8000/health

printf '\n'
log 'RetroDB application deployment is healthy.'
printf '  Local health endpoint: http://127.0.0.1:8000/health\n'
printf '  Service status       : systemctl status retrodb\n'
printf '  Service logs         : journalctl -u retrodb\n'
