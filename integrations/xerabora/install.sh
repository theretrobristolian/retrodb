#!/usr/bin/env bash
# Standalone Debian xeRAbora headless installer / updater / manager.
set -Eeuo pipefail
DIR=/opt/xerabora
BIN=xerabora-linux-x86_64
USER_NAME="$(id -un)"
[[ -n "$USER_NAME" && "$USER_NAME" != root ]] || { echo "Run as a normal user (without sudo bash)." >&2; exit 1; }
HOME_PATH="$(getent passwd "$USER_NAME" | cut -d: -f6)"
[[ -n "$HOME_PATH" && -d "$HOME_PATH" ]] || { echo "Could not resolve user home" >&2; exit 1; }
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ "$(uname -m)" == x86_64 ]] || { echo "x86_64 required" >&2; exit 1; }
command -v systemctl >/dev/null || { echo "systemd required" >&2; exit 1; }

prerequisites() {
  [[ -f /etc/os-release ]] || { echo "Linux distribution unknown" >&2; return 1; }
  . /etc/os-release
  [[ "${ID:-}" == debian || " ${ID_LIKE:-} " == *" debian "* || "${ID:-}" == ubuntu ]] || {
    echo "This installer supports Debian-family Linux only." >&2; return 1;
  }
  for cmd in sudo curl python3 sha256sum getent ip ss mktemp install systemctl; do
    command -v "$cmd" >/dev/null && continue
    echo "Missing prerequisite: $cmd"
    if ! command -v sudo >/dev/null; then
      echo "Ask an administrator to install sudo, configure your user for sudo, then retry." >&2
      return 1
    fi
    if ! command -v apt-get >/dev/null; then
      echo "apt-get not found; install Debian prerequisites manually." >&2
      return 1
    fi
    read -rp "Install required packages with apt-get now? [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]] || return 1
    sudo -v || return 1
    sudo apt-get update || return 1
    sudo apt-get install -y sudo curl python3 coreutils passwd iproute2 ca-certificates util-linux || return 1
    break
  done
  for cmd in sudo curl python3 sha256sum getent ip ss mktemp install systemctl; do
    command -v "$cmd" >/dev/null || { echo "Still missing $cmd" >&2; return 1; }
  done
  sudo -v || { echo "This user needs sudo privileges." >&2; return 1; }
  echo "Debian prerequisites and sudo access: OK"
}

active_config_dir() {
  local current
  current="$(cat "$HOME_PATH/.config/xerabora-profiles/active" 2>/dev/null || true)"
  if [[ "$current" =~ ^[a-zA-Z0-9_-]{1,48}$ && -d "$HOME_PATH/.config/xerabora-profiles/$current/xerabora" ]]; then
    printf '%s' "$HOME_PATH/.config/xerabora-profiles/$current/xerabora"
  else
    printf '%s' "$HOME_PATH/.config/xerabora"
  fi
}

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
  if [[ -f "$(active_config_dir)/xerabora.log" ]]; then
    tail -n 30 "$(active_config_dir)/xerabora.log"
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
  prerequisites || return 1
  local version old base tmp file confirm
  old="$(installed_version)"
  version="$(latest_release)"
  [[ "$version" =~ ^[a-zA-Z0-9._-]+$ ]] || { echo "Unable to validate release tag" >&2; exit 1; }
  echo "Installed: $old | Newest: $version"
  if [[ "$old" == "$version" && -x /opt/xerabora/xerabora-linux-x86_64 ]]; then
    echo "Already current; no changes needed."
    prompt_api_key
    return
  fi
  read -rp "Download, verify, install $version and restart service? [y/N] " confirm
  [[ "$confirm" =~ ^[Yy]$ ]] || { echo "No changes made."; return; }
  base="https://github.com/hacan359/xerabora/releases/download/$version"
  tmp="$(mktemp -d)"
  trap 'rm -rf "${tmp:-}"' EXIT
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
  if [[ "$old" == unknown && ! -s "$HOME_PATH/.config/xerabora/credentials" ]]; then
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
  prompt_api_key
}


api_key_present() { [[ -s "$(active_config_dir)/apikey" ]]; }
set_api_key() {
  local key answer keytmp
  if api_key_present; then
    read -rp "Web API key exists. Replace? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || return 0
  fi
  echo "Get your key from https://retroachievements.org/settings (Keys)"
  read -rsp "Paste Web API key (hidden, blank cancels): " key
  echo
  [[ -n "$key" ]] || { echo "Cancelled"; return 0; }
  umask 077
  local cfg
  cfg="$(active_config_dir)"
  install -d -m 700 "$cfg"
  keytmp="$(mktemp "$cfg/.apikey.XXXXXX")"
  printf '%s\n' "$key" > "$keytmp"
  unset key
  chmod 600 "$keytmp"
  mv -f "$keytmp" "$cfg/apikey"
  echo "API key saved."
  if systemctl is-active --quiet xerabora.service; then
    sudo systemctl restart xerabora.service
    echo "Service restarted."
  fi
}
prompt_api_key() {
  local answer
  if api_key_present; then
    echo "Web API key: configured"
  else
    echo "Web API key: missing"
    read -rp "Add Web API key? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then set_api_key; fi
  fi
}
test_api() {
  [[ -x "$DIR/$BIN" ]] || { echo "Not installed" >&2; return 1; }
  api_key_present || { echo "Missing Web API key" >&2; return 1; }
  local current
  current="$(cat "$HOME_PATH/.config/xerabora-profiles/active" 2>/dev/null || true)"
  if [[ "$current" =~ ^[a-zA-Z0-9_-]{1,48}$ ]]; then
    XDG_CONFIG_HOME="$HOME_PATH/.config/xerabora-profiles/$current" "$DIR/$BIN" --recent
  else
    "$DIR/$BIN" --recent
  fi
}
menu() {
  local choice installed latest state api
  while true; do
    installed="$(installed_version)"
    latest="$(latest_release 2>/dev/null || true)"
    [[ -n "$latest" ]] || latest="unavailable"
    state="$(systemctl is-active xerabora.service 2>/dev/null || true)"
    if api_key_present; then api="configured"; else api="missing"; fi
    echo
    echo "========= xeRAbora manager ========="
    echo "Installed: $installed | Latest: $latest"
    echo "Service: $state | Web API key: $api"
    echo " 1) Install / update"
    echo " 2) Add / update Web API key"
    echo " 3) Test Web API"
    echo " 4) Service status"
    echo " 5) Restart service"
    echo " 6) Network / port diagnostics"
    echo " 7) Logs"
    echo " 8) RetroAchievements login"
    echo " 9) Manage RetroAchievements profiles"
    echo " 0) Exit"
    read -rp "Select [Enter=install/update]: " choice || break
    case "$choice" in
      ""|1) install_client ;;
      2) set_api_key ;;
      3) test_api ;;
      4) systemctl --no-pager status xerabora.service || true ;;
      5) sudo systemctl restart xerabora.service ;;
      6) doctor ;;
      7) journalctl -u xerabora.service -n 60 --no-pager ;;
      8) login ;;
      9) if [[ -f "$SCRIPT_DIR/profiles.sh" ]]; then bash "$SCRIPT_DIR/profiles.sh"; else echo "profiles.sh missing. Download the full integrations/xerabora directory."; fi ;;
      0|q|Q) break ;;
      *) echo "Invalid choice" ;;
    esac
  done
}

case "${1:-menu}" in
  menu) menu ;;
  install|update) install_client ;;
  version|versions|check) check_version ;;
  api-key) set_api_key ;;
  test-api) test_api ;;
  login) login ;;
  doctor) doctor ;;
  prerequisites|prereqs) prerequisites ;;
  status) systemctl --no-pager status xerabora.service || true ;;
  logs) journalctl -u xerabora.service -n 60 --no-pager ;;
  start|stop|restart) sudo systemctl "$1" xerabora.service ;;
  *) echo "Usage: bash install.sh [menu|prerequisites|install|check|update|api-key|test-api|login|doctor|status|logs|start|stop|restart]"; exit 2 ;;
esac
