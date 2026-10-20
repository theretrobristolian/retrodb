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
  local prepare="/var/lib/retrodb/patches/patch-prepare.json"
  local prepared_copy="$HOME/retrodb-exports/patch-prepare.json"
  if sudo -n test -f "$prepare" 2>/dev/null || sudo test -f "$prepare"; then
    sudo install -m 0600 -o "$(id -un)" -g "$(id -gn)" "$prepare" "$prepared_copy" || return 1
    ( umask 077; python3 "$HERE/report_excel.py" "$EXPORT" "$excel" "$prepared_copy" ) || return 1
  else
    ( umask 077; python3 "$HERE/report_excel.py" "$EXPORT" "$excel" ) || return 1
    echo '[INFO] Patchable verification unavailable; run patch-plan, patch-download and patch-prepare to identify verified patch sources.'
  fi
  local rename_report="$HOME/retrodb-exports/RetroDB-OPL-Rename-Proposals.csv"
  ( umask 077; python3 "$HERE/report_opl_rename.py" "$EXPORT" "$rename_report" ) || return 1
  echo "[OK] OPL rename proposals: $rename_report"
  echo "[OK] CSV copied to $EXPORT"
  echo "[OK] Excel workbook: $excel"
  ls -lh "$EXPORT"
  local remote
  remote="$(id -un)@$(hostname -f 2>/dev/null || hostname):retrodb-exports/retroachievements-compatibility.csv"
  echo 'Run on your own computer, not inside SSH:'
  echo ' Mac / Linux (recommended Excel workbook):'
  printf '   scp "%s" ~/Downloads/\n' "$(id -un)@$(hostname -f 2>/dev/null || hostname):retrodb-exports/RetroDB-Compatibility.xlsx"
  echo ' Mac / Linux (read-only OPL rename proposals):'
  printf '   scp "%s" ~/Downloads/\n' "$(id -un)@$(hostname -f 2>/dev/null || hostname):retrodb-exports/RetroDB-OPL-Rename-Proposals.csv"
  echo ' Mac / Linux (raw CSV):'
  printf '   scp "%s" ~/Downloads/\n' "$remote"
  echo ' Windows PowerShell (recommended Excel workbook):'
  printf '   scp "%s" "%s"\n' "$(id -un)@$(hostname -f 2>/dev/null || hostname):retrodb-exports/RetroDB-Compatibility.xlsx" '$env:USERPROFILE\Downloads\RetroDB-Compatibility.xlsx'
  echo ' Windows PowerShell (raw CSV):'
  printf '   scp "%s" "%s"\n' "$remote" '$env:USERPROFILE\Downloads\retroachievements-compatibility.csv'
  echo 'Excel includes Summary, PlayStation 1 and PlayStation 2 tabs; the CSV remains available for technical diagnosis.'
}
stage() {
  printf '\n================================================================\n'
  printf ' [STAGE %s] %s\n' "$1" "$2"
  printf '================================================================\n'
}
step() {
  local number="$1" label="$2"; shift 2
  stage "$number" "$label"
  if "$@"; then
    printf '[OK] %s\n' "$label"
  else
    printf '[FAILED] %s — stopping this workflow.\n' "$label" >&2
    return 1
  fi
}
sync_gamedb() {
  sudo install -d -o retrodb -g retrodb -m 0750 /var/cache/retrodb/providers/gamedb || return 1
  sudo -u retrodb env PYTHONPATH=/opt/retrodb/backend /opt/retrodb/.venv/bin/python -m retrodb.providers.gamedb --platform playstation-2
}

audit() {
  stage "1/8" "Prerequisites and read-only RetroNAS connection"
  mount_ready || { echo 'Audit cancelled: RetroNAS unavailable.' >&2; return 1; }
  sudo test -x /opt/retrodb-tools/RAHasher || { echo '[ERROR] RAHasher unavailable.' >&2; return 1; }
  printf '[OK] RetroNAS mounted; RAHasher available.\n'
  step "2/8" "Synchronise RetroAchievements catalogue (cache-aware)" sudo bash "$HERE/retroachievements.sh" sync || return 1
  step "3/8" "Synchronise PS2 GameDB serial catalogue (cache-aware)" sync_gamedb || return 1
  step "4/8" "Inventory PS1 / PS2 collection (read-only)" sudo bash "$HERE/retronas.sh" scan || return 1
  step "5/8" "Hash and match disc images against RetroAchievements" sudo bash "$HERE/retronas.sh" match || return 1
  step "6/8" "Prepare official patch manifest" sudo bash "$HERE/retronas.sh" patch-plan || return 1
  step "7/8" "Download / reuse official patches, verify existing source ISOs" patch_audit || return 1
  step "8/8" "Export formatted Excel workbook and raw CSV" export_csv || return 1
  printf '\n[COMPLETE] Full collection audit and downloadable workbook ready.\n'
  echo 'NOTE: No original RetroNAS game images were changed.'
}
patch_audit() {
  sudo bash "$HERE/retronas.sh" patch-download || return 1
  sudo bash "$HERE/retronas.sh" patch-prepare
}
patch_download() {
  mount_ready || return 1
  step "1/2" "Generate official patch manifest" sudo bash "$HERE/retronas.sh" patch-plan || return 1
  step "2/2" "Download / reuse safe patch packages" sudo bash "$HERE/retronas.sh" patch-download
  printf '\nPatches are stored locally under /var/lib/retrodb/patches/downloads.\n'
  echo 'No ISO has been patched and RetroNAS has not been modified.'
}
patch_apply() {
  local answer
  mount_ready || return 1
  cat <<'INFO'
This action applies patches ONLY to locally verified clean source images.
It writes verified outputs to:
  /var/lib/retrodb/patches/verified/

The original RetroNAS collection remains read-only.
You must review the patched outputs and manually transfer selected files
to RetroNAS yourself, replacing nothing automatically.
INFO
  read -rp 'Type APPLY to proceed, or press Enter to cancel: ' answer
  [[ "$answer" == APPLY ]] || { echo 'Cancelled.'; return 0; }
  step "1/2" "Verify candidate source checksums against patch instructions" sudo bash "$HERE/retronas.sh" patch-prepare || return 1
  step "2/2" "Apply patches locally and verify output RA hashes" sudo bash "$HERE/retronas.sh" patch-apply || return 1
  printf '\n[COMPLETE] Inspect the locally verified outputs before manually copying them to RetroNAS.\n'
  echo 'Results: /var/lib/retrodb/patches/patch-apply.json'
}
run() { if "$@"; then echo '[OK] Operation completed.'; else echo '[ERROR] Operation failed.' >&2; fi; }
menu() {
  local choice
  while true; do
    header
    echo '  1) FULL AUDIT — refresh, scan, verify patches, export Excel'
    echo '  2) Download / update official patch packages'
    echo '  3) Apply verified patches LOCALLY (confirmation required)'
    echo '  4) Export latest Excel workbook (no new audit)'
    echo '  5) Service / integration details'
    echo '  0) Exit'
    echo '----------------------------------------------------------------'
    echo ' https://github.com/theretrobristolian/retrodb'
    echo ' Update: cd ~/retrodb && git pull --ff-only origin main'
    echo '----------------------------------------------------------------'
    read -rp 'Choose an option: ' choice || break
    case "$choice" in
      1) run audit; pause ;;
      2) run patch_download; pause ;;
      3) run patch_apply; pause ;;
      4) run export_csv; pause ;;
      5) echo; systemctl --no-pager --full status retrodb.service xerabora.service || true
         echo; sudo bash "$HERE/retronas.sh" status || true; pause ;;
      0|q|Q) break ;;
      *) echo 'Invalid option.'; pause ;;
    esac
  done
}
case "${1:-menu}" in
  menu) menu ;;
  audit) audit ;;
  export) export_csv ;;
  patches) patch_download ;;
  patch-apply) patch_apply ;;
  status) header ;;
  *) echo 'Usage: bash server/manager.sh [menu|audit|export|patches|patch-apply|status]' >&2; exit 2 ;;
esac
