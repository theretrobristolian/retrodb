#!/usr/bin/env bash
# RetroDB LAN reverse proxy with mandatory authentication.
# App stays bound to loopback and never runs as root.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run using sudo.' >&2; exit 1; }
MODE=${1:-}
HOST='retrodb.it.gattaca.house'
case "$MODE" in http|https) ;; *) echo 'Usage: sudo bash server/configure-web-access.sh http|https [fullchain.pem privatekey.pem]' >&2; exit 2;; esac
if [[ "$MODE" == https && ( ! -s "${2:-}" || ! -s "${3:-}" ) ]]; then
  echo 'HTTPS requires a certificate chain and matching private key.' >&2; exit 2
fi
if ! command -v nginx >/dev/null || ! command -v htpasswd >/dev/null; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y nginx apache2-utils
fi
install -d -o root -g www-data -m 0750 /etc/retrodb
AUTH_FILE=/etc/retrodb/web-users.htpasswd
if [[ ! -s "$AUTH_FILE" ]]; then
  echo 'Create a browser login for RetroDB. Password is requested interactively.'
  read -rp 'Login name [retrodb]: ' LOGIN
  LOGIN=${LOGIN:-retrodb}
  [[ "$LOGIN" =~ ^[A-Za-z0-9_-]{1,32}$ ]] || { echo '[ERROR] Invalid username.' >&2; exit 1; }
  htpasswd -cB "$AUTH_FILE" "$LOGIN"
  chmod 0640 "$AUTH_FILE"
  chown root:www-data "$AUTH_FILE"
fi
tls=''
redirect=''
if [[ "$MODE" == https ]]; then
  install -d -o root -g root -m 0700 /etc/retrodb/tls
  install -o root -g root -m 0644 "$2" /etc/retrodb/tls/fullchain.pem
  install -o root -g root -m 0600 "$3" /etc/retrodb/tls/privkey.pem
  tls='listen 443 ssl; ssl_certificate /etc/retrodb/tls/fullchain.pem; ssl_certificate_key /etc/retrodb/tls/privkey.pem;'
  redirect='server { listen 80; server_name retrodb.it.gattaca.house; return 301 https://retrodb.it.gattaca.house$request_uri; }'
else
  tls='listen 80;'
fi
install -d -m 0755 /etc/nginx/sites-available /etc/nginx/sites-enabled
# Maintain existing Nginx virtual hosts. Do not disable other applications.
config_tmp="$(mktemp)"
trap 'rm -f "$config_tmp"' EXIT
cat > "$config_tmp" <<EOF
$redirect
server {
  $tls
  server_name $HOST;
  server_tokens off;
  add_header X-Content-Type-Options nosniff always;
  add_header Referrer-Policy no-referrer always;
  add_header X-Frame-Options DENY always;
  auth_basic "RetroDB";
  auth_basic_user_file $AUTH_FILE;
  client_max_body_size 1m;
  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_read_timeout 30s;
  }
}
EOF
config_backup="$(mktemp)"
existing_config=false
if [[ -e /etc/nginx/sites-available/retrodb.conf ]]; then
  cp -p /etc/nginx/sites-available/retrodb.conf "$config_backup"
  existing_config=true
fi
install -o root -g root -m 0644 "$config_tmp" /etc/nginx/sites-available/retrodb.conf
ln -sfn /etc/nginx/sites-available/retrodb.conf /etc/nginx/sites-enabled/retrodb.conf
if ! nginx -t; then
  if [[ "$existing_config" == true ]]; then
    cp -p "$config_backup" /etc/nginx/sites-available/retrodb.conf
  else
    rm -f /etc/nginx/sites-available/retrodb.conf /etc/nginx/sites-enabled/retrodb.conf
  fi
  rm -f "$config_backup"
  echo "[ERROR] Nginx config invalid; prior config restored." >&2
  exit 1
fi
rm -f "$config_backup"
systemctl enable --now nginx
systemctl reload nginx
echo "[OK] Protected RetroDB web access configured: $MODE://$HOST/"
echo '[INFO] Authentication is mandatory. Restrict firewall to trusted LAN; prefer HTTPS.'
echo '[SAFE] No sudo delegation or browser-executable maintenance commands were added.'
