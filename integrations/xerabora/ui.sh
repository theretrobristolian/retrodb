#!/usr/bin/env bash
# Shared terminal presentation for the standalone xeRAbora installer.
XR_REPO_URL="https://github.com/theretrobristolian/retrodb"
XR_UPSTREAM_URL="https://hacan359.github.io/xerabora/#top"
xr_active_profile() {
  local path="$HOME/.config/xerabora-profiles/active"
  if [[ -s "$path" ]]; then cat "$path"; else echo "default (legacy)"; fi
}
xr_version() {
  if [[ -s /opt/xerabora/VERSION ]]; then cat /opt/xerabora/VERSION; else echo "not installed"; fi
}
xr_service_status() {
  systemctl is-active xerabora.service 2>/dev/null || true
}
xr_config_dir() {
  local active
  active="$(cat "$HOME/.config/xerabora-profiles/active" 2>/dev/null || true)"
  if [[ "$active" =~ ^[A-Za-z0-9_-]{1,48}$ && -d "$HOME/.config/xerabora-profiles/$active/xerabora" ]]; then
    printf '%s' "$HOME/.config/xerabora-profiles/$active/xerabora"
  else
    printf '%s' "$HOME/.config/xerabora"
  fi
}
xr_server_ip() {
  local ip
  ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1);exit}}')"
  [[ -n "$ip" ]] || ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  printf '%s' "$ip"
}
xr_web_enabled() {
  [[ -f /etc/systemd/system/xerabora.service ]] &&
    ! grep -Eq '^ExecStart=.*--no-ui([[:space:]]|$)' /etc/systemd/system/xerabora.service
}
xr_web_lan_enabled() {
  [[ "$(cat "$HOME/.config/xerabora-server/lan" 2>/dev/null || true)" == 1 ]]
}
xr_web_urls() {
  local ip host
  if ! xr_web_enabled; then
    printf ' Web UI: disabled (enable from manager)\n'
    return
  fi
  printf ' Web UI (local): http://127.0.0.1:18280/\n'
  if xr_web_lan_enabled; then
    ip="$(xr_server_ip)"
    host="$(hostname -f 2>/dev/null || hostname)"
    [[ -n "$ip" ]] && printf ' Web UI (LAN):   http://%s:18280/\n' "$ip"
    [[ "$host" == *.* ]] && printf ' Web UI (DNS):   http://%s:18280/ (if DNS resolves)\n' "$host"
  else
    printf ' Web UI: localhost only; LAN access disabled\n'
  fi
}
xr_draw_header() {
  local title="${1:-Main menu}"
  if [[ -t 1 ]]; then printf '\033[2J\033[H'; fi
  cat <<'ART'
 __  __ _____ ____      _    ____   ___  ____      _
 \ \/ /| ____|  _ \    / \  | __ ) / _ \|  _ \    / \
  \  / |  _| | |_) |  / _ \ |  _ \| | | | |_) |  / _ \
  /  \ | |___|  _ <  / ___ \| |_) | |_| |  _ <  / ___ \
 /_/\_\|_____|_| \_\/_/   \_\____/ \___/|_| \_\/_/   \_\
ART
  printf '%s\n' '--------------------------------------------------------------------'
  printf ' xeRAbora by hacan359 | %s\n' "$XR_UPSTREAM_URL"
  printf '%s\n' '--------------------------------------------------------------------'
  printf ' Service: %-15s Version: %s\n' "$(xr_service_status)" "$(xr_version)"
  printf ' Active RetroAchievements profile: %s\n' "$(xr_active_profile)"
  xr_web_urls
  printf '%s\n' '--------------------------------------------------------------------'
  printf ' %s\n' "$title"
  printf '%s\n' '--------------------------------------------------------------------'
}
xr_draw_footer() {
  printf '%s\n' '--------------------------------------------------------------------'
  printf ' Community installer by The Retro Bristolian\n'
  printf ' Source: %s\n' "$XR_REPO_URL"
  printf ' Update scripts: cd ~/retrodb && git pull --ff-only origin main\n'
  printf '%s\n' '--------------------------------------------------------------------'
}
xr_pause() { local unused; read -rp 'Press Enter to return to the menu...' unused || true; }
xr_follow_log() {
  local log pid
  if [[ -s "$HOME/.config/xerabora-profiles/active" ]]; then
    log="$HOME/.config/xerabora-profiles/$(cat "$HOME/.config/xerabora-profiles/active")/xerabora/xerabora.log"
  else
    log="$HOME/.config/xerabora/xerabora.log"
  fi
  [[ -f "$log" ]] || { echo "No log file yet: $log"; return 0; }
  printf 'Monitoring: %s\nPress Ctrl+C to stop and return to the menu.\n\n' "$log"
  tail -n 30 -F -- "$log" &
  pid=$!
  trap 'kill "$pid" 2>/dev/null || true' INT
  wait "$pid" 2>/dev/null || true
  trap - INT
}
