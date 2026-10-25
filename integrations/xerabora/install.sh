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
[[ -f "$SCRIPT_DIR/ui.sh" ]] || { echo "Missing ui.sh; download the complete xerabora directory." >&2; exit 1; }
# shellcheck source=ui.sh
source "$SCRIPT_DIR/ui.sh"
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
    read -rp "Install required packages with apt-get now? [y/n] (default: no) " reply
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
server_mode_supported() {
  # Only v1.0.0 and newer implement --server. Pre-release builds must
  # retain their original invocation, including v1.0.0-rc releases.
  local version="${1#v}" major minor patch suffix
  if [[ "$version" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    major="${BASH_REMATCH[1]}"
    (( 10#$major >= 1 ))
  else
    return 1
  fi
}

sync_service_server_mode() {
  # Repair a previously installed v1.x service in place without overwriting
  # startup-mode, profile and Web UI preferences.
  local version="$1" unit=/etc/systemd/system/xerabora.service
  [[ -f "$unit" ]] || return 0
  if server_mode_supported "$version"; then
    if ! grep -Eq '^ExecStart=.*[[:space:]]--server([[:space:]]|$)' "$unit"; then
      sudo sed -i '/^ExecStart=/s/$/ --server/' "$unit" || return 1
      sudo systemctl daemon-reload || return 1
      echo "[OK] xeRAbora $version: systemd server mode enabled."
      if systemctl is-active --quiet xerabora.service; then
        sudo systemctl restart xerabora.service || return 1
      fi
    fi
  elif grep -Eq '^ExecStart=.*[[:space:]]--server([[:space:]]|$)' "$unit"; then
    sudo sed -i '/^ExecStart=/s/ --server\([[:space:]]\|$\)/\1/g' "$unit" || return 1
    sudo systemctl daemon-reload || return 1
    if systemctl is-active --quiet xerabora.service; then
      sudo systemctl restart xerabora.service || return 1
    fi
  fi
}

# Temporary denylist: confirmed broken on Intel Celeron J6412 (no AVX/AVX2).
# Never install v1.0.0 on this CPU, regardless of the upgrade path.
# Remove only after upstream supplies a verified compatible release.
blocked_cpu_release() {
  local version="${1#v}"
  [[ "$version" == "1.0.0" ]] || return 1
  grep -qi 'Intel(R) Celeron(R) J6412' /proc/cpuinfo 2>/dev/null ||
    { ! grep -qw avx /proc/cpuinfo 2>/dev/null && ! grep -qw avx2 /proc/cpuinfo 2>/dev/null; }
}

enforce_release_guard() {
  local version="$1"
  if blocked_cpu_release "$version"; then
    echo "[BLOCKED] xeRAbora $version is known to fail CPU ISA checks on this host." >&2
    echo "[SAFE] Remain on the working alpha release. No download or service changes made." >&2
    return 1
  fi
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
    if blocked_cpu_release "$upstream"; then
      echo "[BLOCKED] This upstream version is incompatible with the CPU exposed to the VM."
    else
      [[ "$installed" == "$upstream" ]] && echo "Up to date" || echo "Update available (or installation unmanaged)"
    fi
  else
    echo "Cannot retrieve GitHub release information" >&2
    return 1
  fi
}
cpu_binary_preflight() {
  # Briefly exercise the freshly downloaded binary before replacing anything.
  # Detect the dynamic loader's unsupported-ISA error and SIGILL (132).
  # A timeout is *not* a pass/fail indication: GUI/server clients can run forever.
  local candidate="$1" temp rc
  temp="$(mktemp)"
  chmod +x "$candidate"
  set +e
  timeout --kill-after=1s 4s "$candidate" --help >"$temp" 2>&1
  rc=$?
  set -e
  if grep -Eiq 'CPU ISA level is lower than required|unsupported (CPU|instruction)|Illegal instruction' "$temp" || [[ "$rc" == 132 ]]; then
    echo "[ERROR] New xeRAbora binary requires CPU instructions not exposed by this VM." >&2
    cat "$temp" >&2
    rm -f "$temp"
    return 1
  fi
  rm -f "$temp"
  # Also reject if ELF explicitly declares x86-64-v3/v4 without CPU AVX2.
  if command -v readelf >/dev/null 2>&1 &&
     readelf -n "$candidate" 2>/dev/null | grep -Eq 'x86-64-v[34]' &&
     ! grep -qw avx2 /proc/cpuinfo; then
    echo "[ERROR] Binary declares x86-64-v3/v4 but the VM exposes no AVX2." >&2
    return 1
  fi
  return 0
}

rollback_failed_upgrade() {
  # Called only after all three previous artifacts were captured.
  # Do not modify authentication, profiles or service override drop-ins.
  local old_unit="$1" name
  echo "[WARN] Restoring previous working xeRAbora install." >&2
  sudo systemctl stop xerabora.service || true
  for name in xerabora-linux-x86_64 OPL-RA.ELF VERSION; do
    if sudo test -f "/opt/xerabora/$name.previous"; then
      sudo cp -a "/opt/xerabora/$name.previous" "/opt/xerabora/$name"
    fi
  done
  if [[ -f "$old_unit" ]]; then
    sudo install -m 0644 "$old_unit" /etc/systemd/system/xerabora.service
  fi
  sudo systemctl daemon-reload
  sudo systemctl reset-failed xerabora.service || true
  sudo systemctl start xerabora.service || true
}

verify_running_service() {
  local n
  for n in {1..45}; do
    if systemctl is-active --quiet xerabora.service; then
      sleep 3
      systemctl is-active --quiet xerabora.service && return 0
    fi
    sleep 1
  done
  sudo journalctl -u xerabora.service -n 40 --no-pager >&2
  return 1
}

install_client() {
  prerequisites || return 1
  local version old base tmp file confirm mode
  mode="$(service_startup_mode)"
  old="$(installed_version)"
  version="$(latest_release)"
  [[ "$version" =~ ^[a-zA-Z0-9._-]+$ ]] || { echo "Unable to validate release tag" >&2; exit 1; }
  echo "Installed: $old | Newest: $version"
  enforce_release_guard "$version" || return 1
  if [[ "$old" == "$version" && -x /opt/xerabora/xerabora-linux-x86_64 ]]; then
    echo "Already current; checking service configuration."
    if ! cpu_binary_preflight /opt/xerabora/xerabora-linux-x86_64; then
      echo "[ERROR] Installed binary incompatible. Use option 15 to restore the previous release." >&2
      return 1
    fi
    sync_service_server_mode "$version" || return 1
    if [[ -f "$SCRIPT_DIR/../../server/install-launchers.sh" ]]; then
      bash "$SCRIPT_DIR/../../server/install-launchers.sh" xerabora || echo "[WARN] xeRAbora launcher could not be installed."
    fi
    prompt_api_key
    return
  fi
  read -rp "Download, verify, install $version and restart service? [y/n] (default: no) " confirm
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
  if ! cpu_binary_preflight "$tmp/xerabora-linux-x86_64"; then
    echo "[SAFE] Existing xeRAbora binary and profiles were not changed." >&2
    return 1
  fi
  local previous_unit
  previous_unit="$(mktemp)"
  if sudo test -f /etc/systemd/system/xerabora.service; then
    sudo cp /etc/systemd/system/xerabora.service "$previous_unit"
  fi
  sudo install -d -m 0755 /opt/xerabora
  for file in xerabora-linux-x86_64 OPL-RA.ELF VERSION; do
    [[ -f "/opt/xerabora/$file" ]] && sudo cp -p "/opt/xerabora/$file" "/opt/xerabora/$file.previous"
  done
  sudo install -m 0755 "$tmp/xerabora-linux-x86_64" /opt/xerabora/xerabora-linux-x86_64
  sudo install -m 0644 "$tmp/OPL-RA.ELF" /opt/xerabora/OPL-RA.ELF
  printf '%s\n' "$version" | sudo tee /opt/xerabora/VERSION >/dev/null
  local unit server_flag=""
  server_mode_supported "$version" && server_flag=" --server"
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
ExecStart=/opt/xerabora/xerabora-linux-x86_64 --no-sound --ui-port 18280$server_flag
ExecStartPre=/bin/sleep 10
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
  sudo install -m 0644 "$unit" /etc/systemd/system/xerabora.service
  rm -f "$unit"
  sudo systemctl daemon-reload
  if [[ -n "$server_flag" ]]; then echo "[OK] xeRAbora $version uses persistent --server mode."; fi
  if [[ "$mode" == auto ]]; then sudo systemctl enable xerabora.service; fi
  if [[ "$old" == unknown && ! -s "$HOME_PATH/.config/xerabora/credentials" ]]; then
    read -rp "Authenticate now? [y/n] (default: yes) " confirm
    if [[ ! "$confirm" =~ ^[Nn]$ ]]; then login; else echo "Run login and then start when ready"; return; fi
  fi
  if [[ "$mode" == disabled ]]; then
    echo "Service installed but remains disabled/masked as requested."
  elif [[ "$mode" == manual ]] && ! systemctl is-active --quiet xerabora.service; then
    echo "Service installed; manual mode preserved (not started)."
  else
    sudo systemctl restart xerabora.service
    if verify_running_service; then
      echo "Service active: $version"
    else
      rollback_failed_upgrade "$previous_unit"
      echo "[ERROR] Upgrade failed health check; previous binary and service restored." >&2
      return 1
    fi
  fi
  if [[ -f "$SCRIPT_DIR/../../server/install-launchers.sh" ]]; then
    if bash "$SCRIPT_DIR/../../server/install-launchers.sh" xerabora; then
      echo "[OK] To open the xeRAbora menu next time, type: xerabora"
    else
      echo "[WARN] xeRAbora installed, but launcher setup failed. Use bash integrations/xerabora/install.sh."
    fi
  fi
  echo "Matching PS2 ELF: /opt/xerabora/OPL-RA.ELF (copy to your PS2 when upgrading)"
  show_elf_download
  prompt_api_key
}



show_elf_download() {
  local host remote
  host="$(hostname -f 2>/dev/null || hostname)"
  remote="$(id -un)@${host}:/opt/xerabora/OPL-RA.ELF"
  echo
  echo 'Matching PS2 OPL-RA ELF — download it to your own computer:'
  if [[ ! -f /opt/xerabora/OPL-RA.ELF ]]; then
    echo '[WARN] OPL-RA.ELF is not installed; install/update xeRAbora first.'
    return 1
  fi
  echo 'Run these commands on your Mac / Linux / Windows computer, NOT in SSH:'
  echo ' macOS / Linux terminal:'
  printf '   scp "%s" ~/Downloads/\n' "$remote"
  echo ' Windows PowerShell:'
  printf '   scp "%s" "%s"\n' "$remote" '$env:USERPROFILE\Downloads\OPL-RA.ELF'
  echo 'Then copy the downloaded ELF onto your PS2 storage and update the OPL-RA entry if necessary.'
}

api_key_present() { [[ -s "$(active_config_dir)/apikey" ]]; }
set_api_key() {
  local key answer keytmp
  if api_key_present; then
    read -rp "Web API key exists. Replace? [y/n] (default: no) " answer
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
    read -rp "Add Web API key? [y/n] (default: no) " answer
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

service_startup_mode() {
  local state mode_file="/etc/systemd/system/xerabora.service.d/restart.conf"
  if [[ -f "$mode_file" ]]; then
    if grep -q '^# xeRAbora startup mode: auto$' "$mode_file"; then echo auto; return; fi
    if grep -q '^# xeRAbora startup mode: manual$' "$mode_file"; then echo manual; return; fi
    if grep -q '^# xeRAbora startup mode: disabled$' "$mode_file"; then echo disabled; return; fi
  fi
  [[ -f /etc/systemd/system/xerabora.service ]] || { echo auto; return; }
  state="$(systemctl is-enabled xerabora.service 2>/dev/null || true)"
  case "$state" in
    enabled|enabled-runtime|linked) echo auto ;;
    disabled|disabled-runtime|static) echo manual ;;
    masked|masked-runtime) echo disabled ;;
    *) echo auto ;;
  esac
}
configure_service_startup() {
  local choice mode dir="/etc/systemd/system/xerabora.service.d" current
  [[ -f /etc/systemd/system/xerabora.service ]] || { echo "Install xeRAbora first."; return 1; }
  current="$(service_startup_mode)"
  xr_draw_header "Service startup and recovery"
  printf ' Current startup mode: %s\n' "$current"
  echo "  1) Automatic: start on boot, restart if unexpectedly stopped"
  echo "  2) Manual: start only when requested, no automatic recovery"
  echo "  3) Disabled: prevent startup until re-enabled"
  echo "  0) Return to main menu"
  xr_draw_footer
  read -rp "Choose an option: " choice || return 0
  case "$choice" in
    1) mode=auto ;;
    2) mode=manual ;;
    3) mode=disabled ;;
    0) return 0 ;;
    *) echo "Invalid selection."; return 1 ;;
  esac
  sudo -v || return 1
  sudo install -d -m 0755 "$dir"
  if [[ "$mode" == auto ]]; then
    printf '# xeRAbora startup mode: auto\n[Service]\nExecStartPre=\nExecStartPre=/bin/sleep 10\nRestart=always\nRestartSec=10\n' | sudo tee "$dir/restart.conf" >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable xerabora.service
    sudo systemctl restart xerabora.service
  else
    printf '# xeRAbora startup mode: %s\n[Service]\nExecStartPre=\nRestart=no\n' "$mode" | sudo tee "$dir/restart.conf" >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl disable xerabora.service
    if [[ "$mode" == disabled ]]; then
      sudo systemctl stop xerabora.service
      echo "Service stopped and disabled at boot."
    fi
  fi
  echo "Startup mode: $mode"
  systemctl is-active xerabora.service 2>/dev/null || true
  if [[ "$mode" == auto ]]; then
    echo "Automatic recovery enabled. Intentional 'systemctl stop' will not trigger a restart."
  elif [[ "$mode" == manual ]]; then
    echo "Manual mode selected; an already-running service is left running."
  else
    echo "Service stopped and disabled at boot; select Automatic or Manual to enable it again."
  fi
}


migrate_web_ui_lan_setting() {
  # Upgrade old per-player UI preferences without modifying account credentials.
  local shared="$HOME_PATH/.config/xerabora-server" legacy
  [[ ! -f "$shared/lan" ]] || return 0
  # An explicit LAN enable on any existing player wins over older localhost defaults.
  for legacy in "$HOME_PATH/.config/xerabora-profiles/"*/xerabora/lan "$HOME_PATH/.config/xerabora/lan"; do
    if [[ -f "$legacy" ]] && [[ "$(cat "$legacy")" == 1 ]]; then
      install -d -m 700 "$shared"
      printf '1\n' > "$shared/lan"
      chmod 600 "$shared/lan"
      return 0
    fi
  done
}

migrate_web_ui_lan_setting



web_ui_settings() {
  local choice cfg unit=/etc/systemd/system/xerabora.service tmp
  cfg="$HOME_PATH/.config/xerabora-server"
  [[ -f "$unit" ]] || { echo "Install xeRAbora first."; return 1; }
  xr_draw_header "Web interface settings"
  echo "  1) Enable Web UI on this server (localhost only)"
  echo "  2) Allow Web UI from your local network (LAN)"
  echo "  3) Disable LAN access (localhost only)"
  echo "  4) Disable Web UI entirely"
  echo "  0) Return to main menu"
  xr_draw_footer
  read -rp "Choose an option: " choice || return 0
  case "$choice" in
    1|2|3|4) ;;
    0) return 0 ;;
    *) echo "Invalid selection"; return 1 ;;
  esac
  if [[ "$choice" == 2 ]]; then
    echo "WARNING: LAN access exposes your RetroAchievements profile and Web UI"
    echo "to anyone who can reach TCP port 18280 on your network."
    echo "Use only on a trusted private network; this is HTTP, not HTTPS."
    local confirmation
    read -rp "Type ENABLE LAN to continue: " confirmation
    [[ "$confirmation" == "ENABLE LAN" ]] || { echo "Cancelled."; return 0; }
  fi
  sudo -v || return 1
  if [[ "$choice" == 1 || "$choice" == 2 || "$choice" == 3 ]]; then
    sudo sed -i 's/ --no-ui//g' "$unit"
    if ! grep -q '^ExecStart=.*--ui-port' "$unit"; then
      sudo sed -i '/^ExecStart=/s/$/ --ui-port 18280/' "$unit"
    fi
  else
    if ! grep -q '^ExecStart=.*--no-ui' "$unit"; then
      sudo sed -i '/^ExecStart=/s/$/ --no-ui/' "$unit"
    fi
  fi
  mkdir -p "$cfg"
  chmod 700 "$cfg"
  if [[ "$choice" == 2 ]]; then printf '1\n' > "$cfg/lan"; else printf '0\n' > "$cfg/lan"; fi
  chmod 600 "$cfg/lan"
  # Upstream xeRAbora loads its native LAN flag from each account's config.
  # Synchronise the single server preference to every installed profile.
  local profile_cfg
  for profile_cfg in "$HOME_PATH"/.config/xerabora-profiles/*/xerabora "$HOME_PATH"/.config/xerabora; do
    [[ -d "$profile_cfg" ]] || continue
    printf '%s\\n' "$([[ "$choice" == 2 ]] && echo 1 || echo 0)" > "$profile_cfg/lan"
    chmod 600 "$profile_cfg/lan"
  done
  sudo systemctl disable --now xerabora-lan.service 2>/dev/null || true
  sudo systemctl daemon-reload
  sudo systemctl restart xerabora.service
  echo "Web UI setting saved; xeRAbora service restarted."
  xr_web_urls
  echo "Exit and relaunch OPL-RA if a PS2 session was interrupted."
}

uninstall_client() {
  local answer unit="/etc/systemd/system/xerabora.service"
  xr_draw_header "Full uninstall — irreversible"
  echo "This will permanently remove:"
  echo "  /opt/xerabora (binary, previous versions and OPL-RA.ELF)"
  echo "  $HOME_PATH/.config/xerabora (original login, API key, logs)"
  echo "  $HOME_PATH/.config/xerabora-profiles (ALL accounts and logs)"
  echo "  $HOME_PATH/.config/xerabora-server (server-wide Web UI settings)"
  echo "  $unit, xerabora-lan.service and its xerabora.service.d/profile.conf override"
  echo
  echo "Your RetroDB repository and unrelated applications will remain."
  echo "systemd's shared journal is not purged (doing so affects other services)."
  echo "You may want to back up credentials or logs before continuing."
  echo
  if [[ -f "$unit" ]] && ! grep -Fq '/opt/xerabora/xerabora-linux-x86_64' "$unit"; then
    echo "Refusing removal: existing service unit does not look like ours." >&2
    return 1
  fi
  read -rp "Type UNINSTALL XERABORA to confirm permanent removal: " answer
  [[ "$answer" == "UNINSTALL XERABORA" ]] || { echo "Cancelled; nothing removed."; return 0; }
  sudo -v || return 1
  if [[ -f "$unit" ]]; then
    sudo systemctl disable --now xerabora.service || return 1
    sudo rm -f -- "$unit"
  fi
  sudo systemctl disable --now xerabora-lan.service 2>/dev/null || true
  sudo rm -f -- /etc/systemd/system/xerabora-lan.service
  sudo rm -f -- /etc/systemd/system/xerabora.service.d/profile.conf /etc/systemd/system/xerabora.service.d/restart.conf
  if [[ -d /etc/systemd/system/xerabora.service.d ]]; then
    sudo rmdir /etc/systemd/system/xerabora.service.d 2>/dev/null || true
  fi
  sudo systemctl daemon-reload
  if [[ -d /opt/xerabora ]]; then sudo rm -rf -- /opt/xerabora; fi
  rm -rf -- "$HOME_PATH/.config/xerabora" "$HOME_PATH/.config/xerabora-profiles" "$HOME_PATH/.config/xerabora-server"
  echo "Full xeRAbora uninstall completed."
  echo "The source checkout and PS2 ELF copies on the console were not removed."
}


safe_source_update() {
  # Source only: never changes running xeRAbora binary, service, or profile.
  local root origin
  command -v git >/dev/null || { echo "Git unavailable"; return 0; }
  root="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)" || { echo "Standalone install; no Git checkout"; return 0; }
  [[ -f "$root/integrations/xerabora/install.sh" ]] || return 0
  [[ "$(git -C "$root" branch --show-current)" == main ]] || { echo "Not on main: skipped"; return 0; }
  origin="$(git -C "$root" remote get-url origin 2>/dev/null)" || return 0
  case "$origin" in
    https://github.com/theretrobristolian/retrodb|https://github.com/theretrobristolian/retrodb.git|git@github.com:theretrobristolian/retrodb.git) ;;
    *) echo "Unknown origin; skipped"; return 0 ;;
  esac
  [[ -z "$(git -C "$root" status --porcelain --untracked-files=no)" ]] || { echo "Local edits; skipped"; return 0; }
  git -C "$root" -c credential.interactive=never fetch -q origin main || { echo "GitHub unavailable"; return 0; }
  git -C "$root" merge-base --is-ancestor HEAD FETCH_HEAD || { echo "History diverged; skipped"; return 0; }
  if [[ "$(git -C "$root" rev-parse HEAD)" != "$(git -C "$root" rev-parse FETCH_HEAD)" ]]; then
    git -C "$root" merge --ff-only -q FETCH_HEAD || return 0
    echo "Manager scripts updated; xeRAbora service unchanged."
    exec bash "$root/integrations/xerabora/install.sh" menu --updated
  fi
  echo "Manager scripts up to date."
}
release_status_line() {
  local upstream installed
  installed="$(installed_version)"
  if ! upstream="$(latest_release 2>/dev/null)" || [[ -z "$upstream" ]]; then
    echo " Upstream version: check unavailable (installed $installed)"
  elif [[ "$installed" == "$upstream" ]]; then
    echo " Upstream version: $installed (current)"
  elif blocked_cpu_release "$upstream"; then
    echo " Upstream version: $upstream available, BLOCKED on this CPU (installed $installed)"
  else
    echo " Upstream version: $upstream available (installed $installed; manual install)"
  fi
}
advanced_menu() {
  local choice
  while true; do
    xr_draw_header "Advanced options"
    echo "  1) Set Web API key"
    echo "  2) Test API"
    echo "  3) Network diagnostics"
    echo "  4) Legacy login"
    echo "  5) Web UI / LAN settings"
    echo "  6) Service startup / recovery settings"
    echo "  7) OPL-RA.ELF download instructions"
    echo "  8) Roll back xeRAbora"
    echo "  9) Uninstall and remove local account data"
    echo "  0) Back"
    xr_draw_footer
    read -rp "Choose: " choice || return 0
    case "$choice" in
      1) set_api_key; xr_pause ;; 2) test_api; xr_pause ;;
      3) doctor; xr_pause ;; 4) login; xr_pause ;;
      5) web_ui_settings; xr_pause ;; 6) configure_service_startup; xr_pause ;;
      7) show_elf_download || true; xr_pause ;;
      8) bash "$SCRIPT_DIR/rollback.sh" || true; xr_pause ;;
      9) uninstall_client; xr_pause ;; 0) return ;;
      *) echo "Invalid choice"; xr_pause ;;
    esac
  done
}
service_controls() {
  local choice
  while true; do
    xr_draw_header "Service controls"
    echo "  1) Status"
    echo "  2) Start"
    echo "  3) Stop"
    echo "  4) Restart"
    echo "  0) Back"
    xr_draw_footer
    read -rp "Choose: " choice || return 0
    case "$choice" in
      1) systemctl --no-pager status xerabora.service || true; xr_pause ;;
      2) sudo systemctl start xerabora.service; xr_pause ;;
      3) sudo systemctl stop xerabora.service; xr_pause ;;
      4) sudo systemctl restart xerabora.service; xr_pause ;;
      0) return ;; *) echo "Invalid choice"; xr_pause ;;
    esac
  done
}
menu() {
  local choice release_note
  if [[ "$*" != *--updated* ]]; then safe_source_update; fi
  release_note="$(release_status_line)"
  while true; do
    xr_draw_header ""
    echo "$release_note"
    printf '%s\n' '--------------------------------------------------------------------'
    echo " Main menu"
    echo
    echo "  1) Switch player"
    echo "  2) Manage players (add / import / credentials)"
    echo "  3) Follow game and achievement log"
    echo "  4) Service controls"
    echo "  5) Check / install xeRAbora binary (may restart service)"
    echo "  6) Update RetroDB manager scripts (no service restart)"
    echo "  7) Advanced options"
    echo "  0) Exit"
    echo
    xr_draw_footer
    read -rp "Choose: " choice || break
    case "$choice" in
      1) bash "$SCRIPT_DIR/profiles.sh" switch; xr_pause ;;
      2) bash "$SCRIPT_DIR/profiles.sh" menu ;;
      3) xr_follow_log; xr_pause ;;
      4) service_controls ;;
      5) check_version || true; install_client; xr_pause; release_note="$(release_status_line)" ;;
      6) safe_source_update; xr_pause ;;
      7) advanced_menu ;;
      0|q|Q) break ;; *) echo "Invalid choice"; xr_pause ;;
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
  follow-log) xr_follow_log ;;
  uninstall) uninstall_client ;;
  web-ui) web_ui_settings ;;
  startup) configure_service_startup ;;
  elf|download-elf) show_elf_download ;;
  rollback) bash "$SCRIPT_DIR/rollback.sh" ;;
  start|stop|restart) sudo systemctl "$1" xerabora.service ;;
  *) echo "Usage: bash install.sh [menu|prerequisites|install|check|update|api-key|test-api|login|doctor|status|logs|follow-log|uninstall|web-ui|startup|elf|download-elf|start|stop|restart]"; exit 2 ;;
esac
