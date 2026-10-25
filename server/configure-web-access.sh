#!/usr/bin/env bash
# Opt-in LAN reverse proxy; RetroDB backend remains loopback-only.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run using sudo.' >&2; exit 1; }
MODE=${1:-}
case "$MODE" in http|https) ;; *) echo 'Usage: sudo bash server/configure-web-access.sh http|https [fullchain.pem privatekey.pem]' >&2; exit 2;; esac
if [[ "$MODE" == https && ( ! -f "${2:-}" || ! -f "${3:-}" ) ]]; then
  echo 'HTTPS requires an existing certificate chain and matching private key.' >&2; exit 2
fi
if ! command -v nginx >/dev/null; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y nginx
fi
mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
if [[ "$MODE" == https ]]; then
  install -d -m 0700 /etc/retrodb/tls
  install -m 0644 "$2" /etc/retrodb/tls/fullchain.pem
  install -m 0600 "$3" /etc/retrodb/tls/privkey.pem
  tls="listen 443 ssl; ssl_certificate /etc/retrodb/tls/fullchain.pem; ssl_certificate_key /etc/retrodb/tls/privkey.pem;"
  redirect='server { listen 80; server_name retrodb.it.gattaca.house; return 301 https://$host$request_uri; }'
else
  tls='listen 80;'
  redirect=''
fi
cat > /etc/nginx/sites-available/retrodb.conf <<EOF
$redirect
server {
  $tls
  server_name retrodb.it.gattaca.house;
  add_header X-Content-Type-Options nosniff always;
  add_header Referrer-Policy no-referrer always;
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
ln -sfn /etc/nginx/sites-available/retrodb.conf /etc/nginx/sites-enabled/retrodb.conf
nginx -t
systemctl enable --now nginx
systemctl reload nginx
echo "[OK] RetroDB LAN access configured for $MODE://retrodb.it.gattaca.house/"
echo '[INFO] DNS must resolve to this VM; firewall ports 80/443 must permit LAN clients.'
echo '[SAFE] RetroDB remains on 127.0.0.1:8000; this only configures a reverse proxy.'
