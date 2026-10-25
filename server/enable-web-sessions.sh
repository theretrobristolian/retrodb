#!/usr/bin/env bash
# One-time HTTPS-only switch from proxy Basic auth to RetroDB app sessions.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
site=/etc/nginx/sites-available/retrodb.conf
[[ -f "$site" ]] || { echo '[ERROR] RetroDB nginx virtual host missing' >&2; exit 1; }
grep -q 'listen 443 ssl' "$site" || { echo '[ERROR] HTTPS is required for session cookies' >&2; exit 1; }
[[ -s /etc/retrodb/web-users-app.htpasswd ]] || { echo '[ERROR] App user hashes not deployed; run deploy.sh first' >&2; exit 1; }
[[ -s /etc/retrodb/retrodb.env ]] || exit 1
login_status=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/login)
home_status=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/)
health_status=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)
[[ "$login_status" == 200 && "$home_status" == 303 && "$health_status" == 401 ]] || {
 echo "[ERROR] Refusing unauthenticated Nginx cutover: login=$login_status home=$home_status health=$health_status" >&2; exit 1;
}
grep -q 'auth_basic "RetroDB";' "$site" || { echo '[INFO] Nginx basic auth already disabled, no change.'; exit 0; }
backup=$(mktemp)
cp -p "$site" "$backup"
trap 'rm -f "$backup"' EXIT
sed -i '/^[[:space:]]*auth_basic "RetroDB";/d; /^[[:space:]]*auth_basic_user_file /d' "$site"
if ! nginx -t; then
 cp -p "$backup" "$site"
 echo '[ERROR] Invalid Nginx config; original restored' >&2
 exit 1
fi
if ! systemctl reload nginx; then
 cp -p "$backup" "$site"
 systemctl reload nginx || true
 echo '[ERROR] Nginx reload failed; original restored' >&2
 exit 1
fi
echo '[OK] RetroDB now uses application HTTPS login sessions (30 days, Secure/HttpOnly cookies).'
echo '[INFO] Existing bcrypt usernames/passwords retained. Browser Basic auth replaced; localhost app routes remain protected.'
echo '[INFO] Do not re-run configure-web-access.sh: that installer intentionally reinstates Basic auth.'
