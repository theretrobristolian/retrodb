#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPORT=/var/lib/retrodb/reports/retroachievements-compatibility.csv
MOUNT=/mnt/retrodb-retronas
EXPORT="$HOME/retrodb-exports/retroachievements-compatibility.csv"
[[ $EUID -ne 0 ]] || { echo 'Run as normal user, not root.' >&2; exit 1; }
state() { systemctl is-active "$1" 2>/dev/null || true; }
web() { curl -fsS -m 2 -o /dev/null "$1" 2>/dev/null && echo responding || echo unavailable; }
protected_status() {
  local flag="$1" path="$2"
  if sudo -n test "$flag" "$path" 2>/dev/null; then
    echo present
  else
    echo "protected / unavailable"
  fi
}
header() {
  [[ ! -t 1 ]] || printf '\033[2J\033[H'
  cat <<'ART'
 ____      _             ____  ____
|  _ \ ___| |_ _ __ ___ |  _ \| __ )
| |_) / _ \ __| '__/ _ \| | | |  _ \
|  _ <  __/ |_| | | (_) | |_| | |_) |
|_| \_\___|\__|_|  \___/|____/|____/
ART
  echo '----------------------------------------------------------------'
  echo ' RetroDB | Community management console by The Retro Bristolian'
  echo '----------------------------------------------------------------'
  printf ' RetroDB: %-12s Local API: http://127.0.0.1:8000/health (%s)\n' "$(state retrodb.service)" "$(web http://127.0.0.1:8000/health)"
  printf ' PostgreSQL: %-9s RetroNAS: %s\n' "$(state postgresql.service)" "$(mountpoint -q "$MOUNT" && echo mounted || echo unavailable)"
  printf ' RAHasher: %-12s CSV report: %s\n' "$(protected_status -x /opt/retrodb-tools/RAHasher)" "$(protected_status -f "$REPORT")"
  printf ' xeRAbora: %-12s Web UI: http://127.0.0.1:18280/ (%s)\n' "$(state xerabora.service)" "$(web http://127.0.0.1:18280/)"
  echo '----------------------------------------------------------------'
}
pause() { read -rp 'Press Enter to return...' ignored || true; }
mount_ready() {
  mountpoint -q "$MOUNT" && return 0
  read -rp 'RetroNAS unmounted. Mount it now? [y/N] ' ans
  [[ "$ans" =~ ^[Yy]$ ]] || return 1
  sudo bash "$HERE/retronas.sh" mount && mountpoint -q "$MOUNT"
}
export_csv() {
  if ! sudo test -f "$REPORT"; then
    echo "Report not found. Run an RA match first." >&2
    return 1
  fi
  install -d -m 0700 "$HOME/retrodb-exports"
  sudo install -m 0600 -o "$(id -un)" -g "$(id -gn)" "$REPORT" "$EXPORT"
  local excel="$HOME/retrodb-exports/RetroDB-Compatibility.xlsx"
  ( umask 077; python3 "$HERE/report_excel.py" "$EXPORT" "$excel" ) || return 1
  echo "[OK] CSV copied to $EXPORT"
  echo "[OK] Excel workbook: $excel"
  ls -lh "$EXPORT"
  local remote
  remote="$(id -un)@$(hostname -f 2>/dev/null || hostname):retrodb-exports/retroachievements-compatibility.csv"
  echo 'Run on your own computer, not inside SSH:'
  echo ' Mac / Linux (recommended Excel workbook):'
  printf '   scp "%s" ~/Downloads/\n' "$(id -un)@$(hostname -f 2>/dev/null || hostname):retrodb-exports/RetroDB-Compatibility.xlsx"
  echo ' Mac / Linux (raw CSV):'
  printf '   scp "%s" ~/Downloads/\n' "$remote"
  echo ' Windows PowerShell (recommended Excel workbook):'
  printf '   scp "%s" "%s"\n' "$(id -un)@$(hostname -f 2>/dev/null || hostname):retrodb-exports/RetroDB-Compatibility.xlsx" '$env:USERPROFILE\Downloads\RetroDB-Compatibility.xlsx'
  echo ' Windows PowerShell (raw CSV):'
  printf '   scp "%s" "%s"\n' "$remote" '$env:USERPROFILE\Downloads\retroachievements-compatibility.csv'
  echo 'Excel includes Summary, PlayStation 1 and PlayStation 2 tabs; the CSV remains available for technical diagnosis.'
}
audit() {
  mount_ready || { echo 'Audit cancelled: RetroNAS unavailable.'; return 1; }
  sudo bash "$HERE/retronas.sh" scan || return 1
  sudo bash "$HERE/retronas.sh" match || return 1
  export_csv
}
run() { if "$@"; then echo '[OK] Completed.'; else echo '[ERROR] Command failed.' >&2; fi; }
menu() {
  local choice ans
  while true; do
    header
    echo '  1) Full ROM audit (scan, RA match, export CSV)'
    echo '  2) Scan RetroNAS inventory'
    echo '  3) Match games against RetroAchievements'
    echo '  4) Export Excel + raw CSV and show download commands'
    echo '  5) Sync RetroAchievements catalogue (cached)'
    echo '  6) Force refresh RetroAchievements catalogue'
    echo '  7) Check / mount RetroNAS'
    echo '  8) RetroDB service details'
    echo '  9) xeRAbora service details'
    echo '  0) Exit'
    echo '----------------------------------------------------------------'
    echo ' https://github.com/theretrobristolian/retrodb'
    echo ' Update: cd ~/retrodb && git pull --ff-only origin main'
    echo '----------------------------------------------------------------'
    read -rp 'Choose an option: ' choice || break
    case "$choice" in
      1) run audit; pause ;;
      2) if mount_ready; then run sudo bash "$HERE/retronas.sh" scan; fi; pause ;;
      3) if mount_ready; then run sudo bash "$HERE/retronas.sh" match; fi; pause ;;
      4) run export_csv; pause ;;
      5) run sudo bash "$HERE/retroachievements.sh" sync; pause ;;
      6) read -rp 'Force upstream catalogue refresh? [y/N] ' ans
         if [[ "$ans" =~ ^[Yy]$ ]]; then run sudo bash "$HERE/retroachievements.sh" sync --force; fi; pause ;;
      7) if mountpoint -q "$MOUNT"; then echo 'RetroNAS mounted.'; else run sudo bash "$HERE/retronas.sh" mount; fi; pause ;;
      8) systemctl --no-pager status retrodb.service || true; pause ;;
      9) systemctl --no-pager status xerabora.service || true; pause ;;
      0|q|Q) break ;;
      *) echo 'Invalid option.'; pause ;;
    esac
  done
}
case "${1:-menu}" in
  menu) menu ;;
  audit) audit ;;
  export) export_csv ;;
  status) header ;;
  *) echo 'Usage: bash server/manager.sh [menu|audit|export|status]' >&2; exit 2 ;;
esac
