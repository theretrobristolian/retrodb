#!/usr/bin/env bash
# Manage isolated xeRAbora account profiles. No passwords are saved by this script.
set -Eeuo pipefail
umask 077
ROOT="${HOME}/.config/xerabora-profiles"
CURRENT="${ROOT}/active"
BIN=/opt/xerabora/xerabora-linux-x86_64
SERVICE=xerabora.service
ORIGINAL="${HOME}/.config/xerabora"
[[ "$(id -u)" -ne 0 ]] || { echo "Run as normal service user, not root" >&2; exit 1; }
[[ -x "$BIN" ]] || { echo "Install xeRAbora first" >&2; exit 1; }
mkdir -p "$ROOT"
chmod 700 "$ROOT"
valid() { [[ "${1:-}" =~ ^[a-zA-Z0-9_-]{1,48}$ ]]; }
profile_dir() { printf '%s/%s' "$ROOT" "$1"; }
list_profiles() {
  echo "Profiles:"
  local d name active
  active="$(cat "$CURRENT" 2>/dev/null || true)"
  for d in "$ROOT"/*; do
    [[ -d "$d" ]] || continue
    name="${d##*/}"
    [[ "$name" == "$active" ]] && echo " * $name (active)" || echo "   $name"
  done
}
create_profile() {
  local name answer pass cfg
  read -rp "Profile name (letters, digits, underscore or dash): " name
  valid "$name" || { echo "Invalid profile name" >&2; return 1; }
  cfg="$(profile_dir "$name")"
  [[ ! -e "$cfg" ]] || { echo "Profile already exists; select it instead" >&2; return 1; }
  mkdir -m 700 "$cfg"
  # Login will create $cfg/xerabora/credentials; no stored password.
  read -rp "RetroAchievements username: " answer
  [[ -n "$answer" ]] || { echo "Username required" >&2; return 1; }
  echo "Authenticate once; when login succeeds, press Ctrl+C to stop the foreground client."
  read -rsp "RetroAchievements password (hidden): " pass
  echo
  [[ -n "$pass" ]] || { echo "Password required" >&2; return 1; }
  local rc=0
  XDG_CONFIG_HOME="$cfg" XERABORA_PASSWORD="$pass" "$BIN" --user "$answer" --no-ui --port 18196 --no-sound || rc=$?
  unset pass
  [[ "$rc" == 0 || "$rc" == 130 ]] || echo "Client exited $rc; inspect this profile before activating" >&2
  [[ -s "$cfg/xerabora/credentials" ]] || { echo "No saved login token. Authentication incomplete." >&2; return 1; }
  echo "Profile $name created. Add an API key using the menu, then activate it."
}
set_key() {
  local name cfg key tmp answer
  read -rp "Profile name: " name
  valid "$name" || return 1
  cfg="$(profile_dir "$name")"
  [[ -d "$cfg" ]] || { echo "Profile missing" >&2; return 1; }
  if [[ -s "$cfg/xerabora/apikey" ]]; then
    read -rp "Existing key found. Replace? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || return 0
  fi
  read -rsp "Paste Web API key (hidden; blank cancels): " key
  echo
  [[ -n "$key" ]] || return 0
  mkdir -p "$cfg/xerabora"
  chmod 700 "$cfg" "$cfg/xerabora"
  tmp="$(mktemp "$cfg/xerabora/.apikey.XXXXXX")"
  printf '%s\n' "$key" > "$tmp"
  unset key
  chmod 600 "$tmp"
  mv "$tmp" "$cfg/xerabora/apikey"
  echo "Key saved for $name"
  [[ "$(cat "$CURRENT" 2>/dev/null || true)" == "$name" ]] && sudo systemctl restart "$SERVICE" || true
}
activate() {
  local name cfg temp
  list_profiles
  read -rp "Activate profile: " name
  valid "$name" || { echo "Invalid profile name" >&2; return 1; }
  cfg="$(profile_dir "$name")"
  [[ -s "$cfg/xerabora/credentials" ]] || { echo "Profile has no login token" >&2; return 1; }
  # Stop the only client; a new process must load the new profile.
  sudo systemctl stop "$SERVICE"
  temp="$(mktemp)"
  cat > "$temp" <<EOF
[Service]
Environment=XDG_CONFIG_HOME=$cfg
EOF
  sudo install -d -m 755 /etc/systemd/system/xerabora.service.d
  sudo install -m 644 "$temp" /etc/systemd/system/xerabora.service.d/profile.conf
  rm -f "$temp"
  sudo systemctl daemon-reload
  sudo systemctl start "$SERVICE"
  if systemctl is-active --quiet "$SERVICE"; then
    printf '%s\n' "$name" > "$CURRENT"
    echo "Active account profile: $name"
  else
    echo "xeRAbora failed to start. Check journalctl -u xerabora -n 50" >&2
    return 1
  fi
}
import_existing() {
  local name cfg
  [[ -s "$ORIGINAL/credentials" ]] || { echo "No existing default credential token found" >&2; return 1; }
  read -rp "Name for existing account [theretrobristolian]: " name
  name="${name:-theretrobristolian}"
  valid "$name" || return 1
  cfg="$(profile_dir "$name")"
  [[ ! -e "$cfg" ]] || { echo "Profile exists; import cancelled" >&2; return 1; }
  mkdir -m 700 "$cfg" "$cfg/xerabora"
  # Copy rather than move, preserving your proven working configuration.
  cp -p "$ORIGINAL/credentials" "$cfg/xerabora/"
  [[ -f "$ORIGINAL/apikey" ]] && cp -p "$ORIGINAL/apikey" "$cfg/xerabora/"
  chmod 600 "$cfg/xerabora/credentials"
  [[ ! -f "$cfg/xerabora/apikey" ]] || chmod 600 "$cfg/xerabora/apikey"
  echo "Copied existing credentials and key into $name; original untouched."
}
menu() {
  local answer
  while :; do
    echo
    echo "=== xeRAbora account profiles ==="
    echo "Active: $(cat "$CURRENT" 2>/dev/null || echo original-default)"
    echo "1) List profiles"
    echo "2) Import existing RetroDB login"
    echo "3) Create another account profile"
    echo "4) Add / replace a profile API key"
    echo "5) Switch active profile"
    echo "6) Show active service account/log"
    echo "0) Exit"
    read -rp "Choose: " answer || return
    case "$answer" in
      1) list_profiles ;;
      2) import_existing ;;
      3) create_profile ;;
      4) set_key ;;
      5) activate ;;
      6) systemctl --no-pager status "$SERVICE" || true ;;
      0) return ;;
      *) echo "Invalid selection" ;;
    esac
  done
}
case "${1:-menu}" in
  menu) menu ;;
  list) list_profiles ;;
  import) import_existing ;;
  add) create_profile ;;
  key) set_key ;;
  switch) activate ;;
  *) echo "Usage: bash profiles.sh [menu|list|import|add|key|switch]" >&2; exit 2 ;;
esac
