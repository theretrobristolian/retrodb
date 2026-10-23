#!/usr/bin/env bash
# Explicit maintenance operations; never invoked by automatic menu refresh.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
ACTION="${1:-}"
[[ "${EUID}" -ne 0 ]] || { echo '[ERROR] Launch as your normal user, not root.' >&2; exit 1; }
command -v sudo >/dev/null || { echo '[ERROR] sudo is required.' >&2; exit 1; }
case "$ACTION" in retrodb|system) ;; *) echo 'Usage: maintenance.sh [retrodb|system]' >&2; exit 2 ;; esac

safe_git_update() {
  [[ -d "$ROOT/.git" ]] || { echo '[ERROR] No Git checkout.' >&2; return 1; }
  [[ "$(git -C "$ROOT" branch --show-current)" == main ]] || {
    echo '[ERROR] Checkout is not on main.' >&2; return 1;
  }
  local remote
  remote="$(git -C "$ROOT" remote get-url origin)"
  case "$remote" in
    https://github.com/theretrobristolian/retrodb|https://github.com/theretrobristolian/retrodb.git|git@github.com:theretrobristolian/retrodb.git) ;;
    *) echo '[ERROR] Unexpected origin URL.' >&2; return 1 ;;
  esac
  [[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]] || {
    echo '[ERROR] Local tracked changes detected. Update aborted.' >&2; return 1;
  }
  echo '[INFO] Checking current RetroDB release...'
  git -C "$ROOT" -c credential.interactive=never fetch origin main || return 1
  local head upstream
  head="$(git -C "$ROOT" rev-parse HEAD)"
  upstream="$(git -C "$ROOT" rev-parse FETCH_HEAD)"
  git -C "$ROOT" merge-base --is-ancestor "$head" "$upstream" || {
    echo '[ERROR] Local branch diverges from origin/main.' >&2; return 1;
  }
  if [[ "$head" != "$upstream" ]]; then
    echo "[INFO] Updating from ${head:0:10} to ${upstream:0:10}"
    git -C "$ROOT" merge --ff-only "$upstream" || return 1
  else
    echo '[OK] Source already current.'
  fi
}

update_retrodb() {
  safe_git_update || return 1
  echo
  echo 'This will check host prerequisites, redeploy the RetroDB backend,'
  echo 'apply database migrations, restart retrodb.service and check health.'
  echo 'Your RetroNAS read-only mount and xeRAbora installation are NOT changed.'
  echo 'It may briefly interrupt the RetroDB API.'
  read -rp 'Type UPDATE RETRODB to continue: ' confirm
  [[ "$confirm" == 'UPDATE RETRODB' ]] || { echo 'Cancelled.'; return 0; }
  sudo bash "$ROOT/server/build.sh" --check || {
    echo '[INFO] Prerequisites need repair. Running idempotent host build.'
    sudo bash "$ROOT/server/build.sh" || return 1
  }
  sudo bash "$ROOT/server/deploy.sh" || return 1
  systemctl is-active --quiet retrodb.service || return 1
  curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8000/health || return 1
  echo
  echo '[OK] RetroDB deployed, service healthy, database migrations applied.'
  echo '[INFO] Restart the menu to load any new menu layout.'
}

update_system() {
  [[ -r /etc/os-release ]] || return 1
  . /etc/os-release
  case "$ID" in debian|ubuntu) ;; *) echo '[ERROR] Unsupported OS.' >&2; return 1 ;; esac
  echo '[INFO] Refreshing APT package lists (requires sudo).'
  sudo apt-get update || return 1
  echo
  echo '[INFO] APT full-upgrade simulation (no packages changed):'
  sudo apt-get -s full-upgrade || return 1
  echo
  echo 'This can upgrade the Linux kernel, hypervisor/VM tooling and other'
  echo 'system packages. It may interrupt services. No automatic reboot or'
  echo 'autoremove will be performed. Review the simulation above.'
  read -rp 'Type UPGRADE SYSTEM to continue: ' confirm
  [[ "$confirm" == 'UPGRADE SYSTEM' ]] || { echo 'Cancelled.'; return 0; }
  sudo apt-get full-upgrade || return 1
  echo '[OK] APT full-upgrade completed.'
  if [[ -e /var/run/reboot-required ]]; then
    echo '[WARN] A reboot is required. Schedule it manually after checking active services.'
  else
    echo '[INFO] No reboot-required marker was found; check services manually.'
  fi
}
case "$ACTION" in
  retrodb) update_retrodb ;;
  system) update_system ;;
esac
