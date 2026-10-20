#!/usr/bin/env bash
# Manage isolated xeRAbora account profiles. No passwords are saved by this script.
set -Eeuo pipefail
umask 077
ROOT="${HOME}/.config/xerabora-profiles"
CURRENT="${ROOT}/active"
BIN=/opt/xerabora/xerabora-linux-x86_64
SERVICE=xerabora.service
ORIGINAL="${HOME}/.config/xerabora"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$SCRIPT_DIR/ui.sh" ]] || { echo "Missing ui.sh; download the complete xerabora directory." >&2; exit 1; }
# shellcheck source=ui.sh
source "$SCRIPT_DIR/ui.sh"
[[ "$(id -u)" -ne 0 ]] || { echo "Run as normal service user, not root" >&2; exit 1; }
[[ -x "$BIN" ]] || { echo "Install xeRAbora first" >&2; exit 1; }
mkdir -p "$ROOT"
chmod 700 "$ROOT"
valid() { [[ "${1:-}" =~ ^[a-zA-Z0-9_-]{1,48}$ ]]; }
profile_dir() { printf '%s/%s' "$ROOT" "$1"; }
list_profiles() {
  echo "Available player profiles:"
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
  local choice name cfg temp active previous_cfg
  local -a names=()
  local d
  active="$(cat "$CURRENT" 2>/dev/null || true)"
  xr_draw_header "Switch active RetroAchievements player"
  for d in "$ROOT"/*; do
    [[ -d "$d" && -s "$d/xerabora/credentials" ]] || continue
    names+=("${d##*/}")
    if [[ "${d##*/}" == "$active" ]]; then
      printf ' %d) %s (active)\n' "${#names[@]}" "${d##*/}"
    else
      printf ' %d) %s\n' "${#names[@]}" "${d##*/}"
    fi
  done
  if [[ "${#names[@]}" -eq 0 ]]; then
    echo "No authenticated profiles. Import or create one first."
    return 0
  fi
  echo " 0) Return to player profiles menu"
  xr_draw_footer
  read -rp "Select profile number: " choice || return 0
  [[ "$choice" != 0 ]] || return 0
  [[ "$choice" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid selection."; return 0; }
  (( choice <= ${#names[@]} )) || { echo "Invalid selection."; return 0; }
  name="${names[choice-1]}"
  cfg="$(profile_dir "$name")"
  if [[ "$active" == "$name" ]]; then
    echo "$name is already active; service unchanged."
    return 0
  fi
  echo "Switching from ${active:-original-default} to $name."
  echo "Finish and save your PS2 game before switching accounts."
  local answer
  read -rp "Continue? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || { echo "Cancelled."; return 0; }
  # xeRAbora reads native LAN flag from each profile's XDG config directory.
  # Mirror the single server-wide preference into the selected profile before start.
  local lan_flag=0
  [[ "$(cat "$HOME/.config/xerabora-server/lan" 2>/dev/null || true)" == 1 ]] && lan_flag=1
  install -d -m 700 "$cfg/xerabora"
  printf '%s\\n' "$lan_flag" > "$cfg/xerabora/lan"
  chmod 600 "$cfg/xerabora/lan"
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
  if sudo systemctl start "$SERVICE" && systemctl is-active --quiet "$SERVICE"; then
    printf '%s\n' "$name" > "$CURRENT"
    echo "Active RetroAchievements profile: $name"
    echo "xeRAbora service restarted successfully."
    echo
    echo "PS2 ACTION REQUIRED:"
    echo "Exit the current game, then reboot the PS2 / relaunch OPL-RA"
    echo "to establish a fresh session with the newly selected account."
    echo "Run 'RA: test PC connection' and 'RA: check game support' if needed."
    echo "Also select the correct MemCard Pro 2 save/card image for this player."
  else
    echo "xeRAbora failed to start. Check journalctl -u xerabora.service -n 50" >&2
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
    xr_draw_header "RetroAchievements player profiles"
    echo "  1) List configured players"
    echo "  2) Import an existing xeRAbora login"
    echo "  3) Add a new player"
    echo "  4) Set or change a player's Web API key"
    echo "  5) Switch active player (numbered selection)"
    echo "  6) View xeRAbora service status"
    echo "  7) Follow active player's log (Ctrl+C to return)"
    echo "  8) Configure server-wide Web UI / LAN access"
    echo "  0) Return to main menu"
    xr_draw_footer
    read -rp "Choose an option: " answer || return
    case "$answer" in
      1) list_profiles; xr_pause ;;
      2) import_existing; xr_pause ;;
      3) create_profile; xr_pause ;;
      4) set_key; xr_pause ;;
      5) activate; xr_pause ;;
      6) systemctl --no-pager status "$SERVICE" || true; xr_pause ;;
      7) xr_follow_log; xr_pause ;;
      8) bash "$SCRIPT_DIR/install.sh" web-ui; xr_pause ;;
      0|q|Q) return ;;
      *) echo "Invalid selection."; xr_pause ;;
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
  follow-log) xr_follow_log ;;
  *) echo "Usage: bash profiles.sh [menu|list|import|add|key|switch]" >&2; exit 2 ;;
esac
