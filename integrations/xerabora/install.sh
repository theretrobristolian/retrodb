#!/usr/bin/env bash
# RetroDB companion: xeRAbora install / status / diagnostics.
set -Eeuo pipefail
VERSION=v0.1.0-alpha.18
SHA=aefaf770612c17b4ae03121638122b4c5cc085ba63dd9b1fc075f5d9786aaa29
OPL_SHA=774f00c5d09c8d2963c2d3e07c02664b1ccb143f01ce30fbaa37d9455d83d87b
BASE=https://github.com/hacan359/xerabora/releases/download/$VERSION
DIR=/opt/xerabora
BIN=xerabora-linux-x86_64
USER_NAME="$USER"
[[ -n "$USER_NAME" && "$USER_NAME" != root ]] || { echo "Run as a normal user (without sudo bash)." >&2; exit 1; }
HOME_PATH="$(getent passwd "$USER_NAME" | cut -d: -f6)"
[[ "$(uname -m)" == x86_64 ]] || { echo "x86_64 required" >&2; exit 1; }
command -v systemctl >/dev/null || { echo "systemd required" >&2; exit 1; }

login() {
  [[ -x "$DIR/$BIN" ]] || { echo "Install first" >&2; exit 1; }
  read -rp "RetroAchievements username: " RA_USER
  read -rsp "RetroAchievements password (not saved): " RA_PASSWORD
  echo
  [[ -n "$RA_USER" && -n "$RA_PASSWORD" ]] || { echo "Credentials required" >&2; exit 1; }
  echo "Once signed in, press Ctrl+C to finish first-run login."
  set +e
  XERABORA_PASSWORD="$RA_PASSWORD" "$DIR/$BIN" --user "$RA_USER" --no-ui
  rc=$?
  set -e
  unset RA_PASSWORD
  if [[ "$rc" != 0 && "$rc" != 130 ]]; then
    echo "Warning: login exited with code $rc; check xeRAbora log" >&2
  fi
}

doctor() {
  echo "=== Host / IPv4 ==="
  hostname -f || hostname
  ip -br -4 addr || true
  ip -4 route || true
  echo "=== xeRAbora service ==="
  systemctl --no-pager --full status xerabora.service || true
  echo "=== UDP 18194 listener ==="
  sudo ss -lunp 'sport = :18194' || true
  echo "=== UFW (read-only) ==="
  if command -v ufw >/dev/null; then sudo ufw status || true; fi
  echo "=== Logs ==="
  if [[ -f "$HOME_PATH/.config/xerabora/xerabora.log" ]]; then
    tail -n 30 "$HOME_PATH/.config/xerabora/xerabora.log"
  else
    echo "No xeRAbora log found yet."
  fi
  echo "Note: UDP listener != proof of PS2 broadcast connectivity."
  echo "End-to-end check: OPL-RA > Triangle > RA: test PC connection."
}

install_client() {
  for cmd in curl sha256sum sudo mktemp; do command -v "$cmd" >/dev/null || { echo "Missing: $cmd" >&2; exit 1; }; done
  echo "Installing xeRAbora $VERSION for $USER_NAME (RetroDB is unchanged)."
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  curl -fL --retry 3 -o "$TMP/$BIN" "$BASE/$BIN"
  printf '%s  %s\n' "$SHA" "$TMP/$BIN" | sha256sum -c -
  curl -fL --retry 3 -o "$TMP/OPL-RA.ELF" "$BASE/OPL-RA.ELF"
  printf '%s  %s\n' "$OPL_SHA" "$TMP/OPL-RA.ELF" | sha256sum -c -
  sudo install -d -m 0755 "$DIR"
  sudo install -m 0755 "$TMP/$BIN" "$DIR/$BIN"
  sudo install -m 0644 "$TMP/OPL-RA.ELF" "$DIR/OPL-RA.ELF"
  UNIT="$(mktemp)"
  cat > "$UNIT" <<EOF
[Unit]
Description=xeRAbora headless RetroAchievements PS2 client
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$USER_NAME
Group=$(id -gn "$USER_NAME")
WorkingDirectory=$DIR
Environment=HOME=$HOME_PATH
ExecStart=$DIR/$BIN --no-ui --no-sound
Restart=on-failure
RestartSec=10
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
  sudo install -m 0644 "$UNIT" /etc/systemd/system/xerabora.service
  rm -f "$UNIT"
  sudo systemctl daemon-reload
  sudo systemctl enable xerabora.service
  if [[ ! -d "$HOME_PATH/.config/xerabora" ]]; then
    read -rp "Authenticate now? [Y/n] " CONFIRM
    if [[ "$CONFIRM" =~ ^[Nn]$ ]]; then
      echo "Run bash install.sh login followed by bash install.sh start."
      return
    fi
    login
  else
    echo "Existing config directory detected; use 'login' if not authenticated."
  fi
  sudo systemctl restart xerabora.service
  doctor
}
case "${1:-install}" in
  install|update) install_client ;;
  login) login ;;
  doctor|check) doctor ;;
  status) systemctl --no-pager status xerabora.service || true ;;
  logs) journalctl -u xerabora.service -n 60 --no-pager ;;
  start|stop|restart) sudo systemctl "$1" xerabora.service ;;
  *) echo "Usage: bash install.sh [install|update|login|doctor|status|logs|start|stop|restart]"; exit 2 ;;
esac
