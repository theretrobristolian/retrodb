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

latest_release() {
  # GitHub /releases/latest excludes prereleases; xeRAbora currently publishes alpha releases.
  curl -fsSL --retry 2 --connect-timeout 10 \
    'https://api.github.com/repos/hacan359/xerabora/releases?per_page=30' |
    python3 -c 'import json,sys; releases=json.load(sys.stdin); required={"SHA256SUMS","xerabora-linux-x86_64","OPL-RA.ELF"}; match=next((r for r in releases if not r["draft"] and required <= {a["name"] for a in r["assets"]}),None); print(match["tag_name"] if match else "")'
}
installed_version() {
  if [[ -f /opt/xerabora/VERSION ]]; then cat /opt/xerabora/VERSION; else echo unknown; fi
}
check_version() {
  local installed upstream
  installed="$(installed_version)"
  echo "Installed: $installed"
  if upstream="$(latest_release)" && [[ -n "$upstream" ]]; then
    echo "Latest upstream: $upstream"
    [[ "$installed" == "$upstream" ]] && echo "Up to date" || echo "Update available (or installation unmanaged)"
  else
    echo "Cannot retrieve GitHub release information" >&2
    return 1
  fi
}
install_client() {
  for cmd in curl sha256sum sudo mktemp python3; do command -v "$cmd" >/dev/null || { echo "Missing: $cmd" >&2; exit 1; }; done
  local version old base tmp file confirm
  old="$(installed_version)"
  version="$(latest_release)"
  [[ "$version" =~ ^[a-zA-Z0-9._-]+$ ]] || { echo "Unable to validate release tag" >&2; exit 1; }
  echo "Installed: $old | Newest: $version"
  if [[ "$old" == "$version" && -x /opt/xerabora/xerabora-linux-x86_64 ]]; then
    echo "Already current; no changes needed."
    return
  fi
  read -rp "Download, verify, install $version and restart service? [y/N] " confirm
  [[ "$confirm" =~ ^[Yy]$ ]] || { echo "No changes made."; return; }
  base="https://github.com/hacan359/xerabora/releases/download/$version"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  for file in SHA256SUMS xerabora-linux-x86_64 OPL-RA.ELF; do
    curl -fL --retry 3 --connect-timeout 15 -o "$tmp/$file" "$base/$file"
  done
  for file in xerabora-linux-x86_64 OPL-RA.ELF; do
    grep -Eq "^[a-fA-F0-9]{64} [* ]$file$" "$tmp/SHA256SUMS" || { echo "Missing checksum for $file" >&2; exit 1; }
    (cd "$tmp"; grep -E "^[a-fA-F0-9]{64} [* ]$file$" SHA256SUMS | sha256sum -c -) || { echo "Checksum failure" >&2; exit 1; }
  done
  sudo install -d -m 0755 /opt/xerabora
  for file in xerabora-linux-x86_64 OPL-RA.ELF VERSION; do
    [[ -f "/opt/xerabora/$file" ]] && sudo cp -p "/opt/xerabora/$file" "/opt/xerabora/$file.previous"
  done
  sudo install -m 0755 "$tmp/xerabora-linux-x86_64" /opt/xerabora/xerabora-linux-x86_64
  sudo install -m 0644 "$tmp/OPL-RA.ELF" /opt/xerabora/OPL-RA.ELF
  printf '%s\n' "$version" | sudo tee /opt/xerabora/VERSION >/dev/null
  local unit
  unit="$(mktemp)"
  cat > "$unit" <<EOF
[Unit]
Description=xeRAbora headless RetroAchievements PS2 client
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$USER_NAME
Group=$(id -gn "$USER_NAME")
WorkingDirectory=/opt/xerabora
Environment=HOME=$HOME_PATH
ExecStart=/opt/xerabora/xerabora-linux-x86_64 --no-ui --no-sound
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
  sudo install -m 0644 "$unit" /etc/systemd/system/xerabora.service
  rm -f "$unit"
  sudo systemctl daemon-reload
  sudo systemctl enable xerabora.service
  if [[ "$old" == unknown && ! -d "$HOME_PATH/.config/xerabora" ]]; then
    read -rp "Authenticate now? [Y/n] " confirm
    if [[ ! "$confirm" =~ ^[Nn]$ ]]; then login; else echo "Run login and then start when ready"; return; fi
  fi
  sudo systemctl restart xerabora.service
  if systemctl is-active --quiet xerabora.service; then
    echo "Service active: $version"
  else
    echo "Service not active. Check logs; previous binary backed up as .previous" >&2
    return 1
  fi
  echo "Matching PS2 ELF: /opt/xerabora/OPL-RA.ELF (copy to your PS2 when upgrading)"
}

case "${1:-install}" in
  install|update) install_client ;;
  version|versions|check) check_version ;;
  login) login ;;
  doctor) doctor ;;
  status) systemctl --no-pager status xerabora.service || true ;;
  logs) journalctl -u xerabora.service -n 60 --no-pager ;;
  start|stop|restart) sudo systemctl "$1" xerabora.service ;;
  *) echo "Usage: bash install.sh [install|check|update|login|doctor|status|logs|start|stop|restart]"; exit 2 ;;
esac
