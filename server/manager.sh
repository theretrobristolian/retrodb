#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# Refresh the checkout before opening the interactive manager. No sudo or
# background updates: clean main, trusted origin and fast-forward only.
auto_update_menu() {
  local root remote current target
  root="$(cd "$HERE/.." && pwd -P)"
  command -v git >/dev/null || { echo '[INFO] Git unavailable; opening installed menu.'; return 0; }
  [[ -d "$root/.git" ]] || { echo '[INFO] No Git checkout; opening installed menu.'; return 0; }
  [[ "$(git -C "$root" branch --show-current 2>/dev/null)" == main ]] || {
    echo '[INFO] Not on main; skipping automatic update.'; return 0;
  }
  remote="$(git -C "$root" remote get-url origin 2>/dev/null || true)"
  case "$remote" in
    https://github.com/theretrobristolian/retrodb|https://github.com/theretrobristolian/retrodb.git|git@github.com:theretrobristolian/retrodb.git)
      ;;
    *) echo '[WARN] Unexpected origin URL; skipping automatic update.'; return 0 ;;
  esac
  if [[ -n "$(git -C "$root" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
    echo '[WARN] Local tracked modifications found; skipping update to protect your changes.'
    return 0
  fi
  echo '[INFO] Checking GitHub for RetroDB updates...'
  if ! timeout 20 git -C "$root" -c credential.interactive=never fetch --quiet origin main; then
    echo '[WARN] Update check unavailable; opening existing menu.'
    return 0
  fi
  current="$(git -C "$root" rev-parse HEAD)"
  target="$(git -C "$root" rev-parse FETCH_HEAD)"
  [[ "$current" != "$target" ]] || { echo '[OK] RetroDB menu is up to date.'; return 0; }
  if ! git -C "$root" merge-base --is-ancestor "$current" "$target"; then
    echo '[WARN] Branch has diverged; refusing to overwrite local commits.'
    return 0
  fi
  # Fast-forward can fail if new tracked paths conflict with untracked files.
  if git -C "$root" merge --ff-only --quiet "$target"; then
    echo '[OK] RetroDB updated to the latest main commit.'
    exec /bin/bash "$root/server/manager.sh" "${ORIGINAL_MENU_ARGS[@]}"
  else
    echo '[WARN] Could not fast-forward; opening existing menu.'
  fi
}
ORIGINAL_MENU_ARGS=("$@")
if [[ "${1:-menu}" == menu && "${RETRODB_AUTOUPDATED:-0}" != 1 ]]; then
  export RETRODB_AUTOUPDATED=1
  auto_update_menu
fi
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
  ( umask 077; sudo python3 "$HERE/report_opl_rename.py" "$EXPORT" "$rename_report" --verify-root "$MOUNT" ) || return 1
  sudo chown "$(id -un):$(id -gn)" "$rename_report" || return 1
  chmod 0600 "$rename_report" || return 1
  local rename_xlsx="$HOME/retrodb-exports/RetroDB-OPL-Rename-Proposals.xlsx"
  ( umask 077; python3 "$HERE/report_opl_excel.py" "$rename_report" "$rename_xlsx" ) || return 1
  echo
  echo '------------------------------------------------------------'
  echo ' EXPORT SUMMARY'
  echo '------------------------------------------------------------'
  printf ' Compatibility Excel : %s\n' "$excel"
  printf ' OPL proposals Excel  : %s\n' "$rename_xlsx"
  printf ' OPL proposals CSV    : %s (rename-engine input)\n' "$rename_report"
  printf ' Raw audit CSV        : %s\n' "$EXPORT"
  echo '------------------------------------------------------------'
  local remote
  remote="$(id -un)@$(hostname -f 2>/dev/null || hostname):retrodb-exports/retroachievements-compatibility.csv"
  echo 'Run on your own computer, not inside SSH:'
  echo ' Mac / Linux (recommended Excel workbook):'
  printf '   scp "%s" ~/Downloads/\n' "$(id -un)@$(hostname -f 2>/dev/null || hostname):retrodb-exports/RetroDB-Compatibility.xlsx"
  echo ' Mac / Linux (OPL rename proposals Excel):'
  printf '   scp "%s" ~/Downloads/\n' "$(id -un)@$(hostname -f 2>/dev/null || hostname):retrodb-exports/RetroDB-OPL-Rename-Proposals.xlsx"
  echo ' Mac / Linux (raw CSV):'
  printf '   scp "%s" ~/Downloads/\n' "$remote"
  echo ' Windows PowerShell (recommended Excel workbook):'
  printf '   scp "%s" "%s"\n' "$(id -un)@$(hostname -f 2>/dev/null || hostname):retrodb-exports/RetroDB-Compatibility.xlsx" '$env:USERPROFILE\Downloads\RetroDB-Compatibility.xlsx'
  echo ' Windows PowerShell (OPL rename proposals Excel):'
  printf '   scp "%s" "%s"\n' "$(id -un)@$(hostname -f 2>/dev/null || hostname):retrodb-exports/RetroDB-OPL-Rename-Proposals.xlsx" '$env:USERPROFILE\Downloads\RetroDB-OPL-Rename-Proposals.xlsx'
  echo ' Windows PowerShell (raw CSV):'
  printf '   scp "%s" "%s"\n' "$remote" '$env:USERPROFILE\Downloads\retroachievements-compatibility.csv'
  echo '[INFO] Both reports now have Excel versions with filters and frozen headers; the OPL CSV remains the rename engine source.'
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
# Separate, temporary CIFS write mount; the audit mount remains read-only.
PILOT_ROOT=/mnt/retrodb-retronas-pilot-rw
PILOT_CSV="$HOME/retrodb-exports/RetroDB-OPL-Rename-Proposals.csv"
OPL_JOURNAL_DIR="$HOME/retrodb-exports/opl-rename-journals"
opl_update_all() {
  local source answer result=0 journal
  [[ -r "$PILOT_CSV" ]] || { echo 'Generate a current rename CSV with option 4 first.'; return 1; }
  mountpoint -q "$MOUNT" || { echo 'RetroNAS read-only mount unavailable.'; return 1; }
  mkdir -p -m 0700 "$OPL_JOURNAL_DIR" || return 1
  # Preserve the completed 40-title journal; new bulk jobs always get a new name.
  local previous
  while IFS= read -r previous; do
    if python3 - "$previous" <<'PYJOURNAL'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    ops = json.load(handle)["operations"]
sys.exit(0 if any(op["state"] != "applied" for op in ops) else 1)
PYJOURNAL
    then
      echo "[STOP] Incomplete rename journal: $previous"
      echo 'Use option 7 to inspect/recover before starting a new operation.'
      return 1
    fi
  done < <(find "$OPL_JOURNAL_DIR" -maxdepth 1 -type f -name 'opl-rename-*.json' | sort)
  journal="$OPL_JOURNAL_DIR/opl-rename-$(date -u +%Y%m%dT%H%M%SZ)-$BASHPID.json"
  echo 'OPL full-library rename — proposed changes (read-only):'
  python3 "$HERE/opl_pilot.py" preview --csv "$PILOT_CSV" --root "$MOUNT" --journal "$journal" || return 1
  local eligible
  eligible="$(python3 "$HERE/opl_pilot.py" count --csv "$PILOT_CSV" --root "$MOUNT" --journal "$journal")" || return 1
  if [[ "$eligible" == 0 ]]; then
    echo '[INFO] No eligible OPL renames. Nothing was changed; no rollback journal was created.'
    echo '[INFO] If you expected changes, regenerate proposals using More options > Export reports and inspect Status values in the CSV.'
    return 0
  fi
  echo 'All PROPOSED titles, including case-only changes, are eligible. REVIEW/COLLISION entries are skipped.'
  echo 'Original filenames are recorded in a NEW rollback manifest before any rename.'
  read -rp 'Type RENAMEALL to proceed (anything else cancels): ' answer
  [[ "$answer" == RENAMEALL ]] || { echo 'Cancelled'; return 0; }
  source="$(findmnt -n -o SOURCE --target "$MOUNT")"
  [[ "$source" == //* ]] || { echo "Unexpected CIFS source: $source"; return 1; }
  sudo install -d -m 0700 "$PILOT_ROOT" || return 1
  if mountpoint -q "$PILOT_ROOT"; then
    echo 'Temporary RW mount is already active; refusing to proceed.'; return 1
  fi
  sudo mount -t cifs "$source" "$PILOT_ROOT" -o "rw,credentials=/etc/retrodb/retronas.credentials,vers=3.1.1,iocharset=utf8,uid=$(id -u),gid=$(id -g),file_mode=0600,dir_mode=0700,actimeo=0,cache=none,nosuid,nodev,noexec" || return 1
  python3 "$HERE/opl_pilot.py" apply --csv "$PILOT_CSV" --root "$PILOT_ROOT" --journal "$journal" || result=$?
  sudo umount "$PILOT_ROOT" || { echo '[WARNING] Temporary RW mount still active; inspect manually.' >&2; return 1; }
  echo "Bulk rename rollback journal: $journal"
  echo 'The previous 40-game pilot journal is unchanged.'
  [[ $result -eq 0 ]] || echo '[WARNING] Rename was interrupted/failed. Keep the journal; inspect it before retrying.'
  return "$result"
}
patch_retronas_one() {
  local game_id confirm source result=0 journal
  mount_ready || return 1
  echo 'READY PS2 patch sources (checksum-verified from the existing audit):'
  sudo python3 - <<'PYREADY'
import json
from pathlib import Path
w=Path('/var/lib/retrodb/patches')
plans=json.loads((w/'patch-plan.json').read_text())
for r in json.loads((w/'patch-prepare.json').read_text()):
    p=next((x for x in plans if x.get('title')==r.get('title') and x.get('local_path') and str((Path('/mnt/retrodb-retronas') / x['local_path'])) == r.get('collection_source')),None)
    if p and p.get('platform')=='Sony PlayStation 2' and r.get('state')=='clean-base-verified-ready-to-patch' and r.get('candidate_path')==r.get('collection_source'):
        print(f"  RA ID {p['ra_game_id']}: {p['title']} -- {p['local_path']}")
PYREADY
  read -rp 'Enter the RA game ID to test (Enter cancels): ' game_id
  [[ "$game_id" =~ ^[0-9]{1,8}$ ]] || { echo 'Cancelled / invalid ID.'; return 0; }
  mkdir -p -m 0700 "$OPL_JOURNAL_DIR" || return 1
  journal="$OPL_JOURNAL_DIR/patch-$(date -u +%Y%m%dT%H%M%SZ)-$game_id-$BASHPID-$RANDOM.json"
  echo '[+] First patching locally and checking the resulting RA hash (no RetroNAS writes).'
  sudo env PYTHONPATH=/opt/retrodb/backend /opt/retrodb/.venv/bin/python \
    "$HERE/patch_retronas.py" --game-id "$game_id" --mount "$MOUNT" \
    --read-mount "$MOUNT" --journal "$journal" --dry-run || return 1
  echo
  echo 'Next: copy current ISO to OLD_<filename>, verify its SHA256,'
  echo 'copy the patched ISO to a temporary file, verify its RA hash,'
  echo 'and atomically replace the original filename. OLD_ is NEVER deleted.'
  read -rp "Type PATCH-$game_id to proceed, or Enter to cancel: " confirm
  [[ "$confirm" == "PATCH-$game_id" ]] || { echo 'Cancelled: dry-run journal retained.'; return 0; }
  source="$(findmnt -n -o SOURCE --target "$MOUNT")"
  [[ "$source" == //* ]] || { echo "Unexpected CIFS source: $source"; return 1; }
  mountpoint -q "$PILOT_ROOT" && { echo '[STOP] Temporary RW mount already active.'; return 1; }
  sudo install -d -m 0700 "$PILOT_ROOT" || return 1
  sudo mount -t cifs "$source" "$PILOT_ROOT" -o "rw,credentials=/etc/retrodb/retronas.credentials,vers=3.1.1,iocharset=utf8,uid=$(id -u),gid=$(id -g),file_mode=0600,dir_mode=0700,actimeo=0,cache=none,nosuid,nodev,noexec" || return 1
  journal="$OPL_JOURNAL_DIR/patch-$(date -u +%Y%m%dT%H%M%SZ)-$game_id-$BASHPID.json"
  sudo env PYTHONPATH=/opt/retrodb/backend /opt/retrodb/.venv/bin/python \
    "$HERE/patch_retronas.py" --game-id "$game_id" --mount "$PILOT_ROOT" \
    --read-mount "$MOUNT" --journal "$journal" || result=$?
  sudo umount "$PILOT_ROOT" || { echo '[WARNING] RW mount still active!'; return 1; }
  echo "Patch operation journal: $journal"
  return "$result"
}

patch_journal_status() {
  local latest
  latest="$(find "$OPL_JOURNAL_DIR" -maxdepth 1 -type f -name 'patch-*.json' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)"
  if [[ -z "$latest" ]]; then
    echo '[INFO] No patch deployment journals found.'
    return 0
  fi
  python3 - "$latest" <<'PY'
import json,sys
from pathlib import Path
path=Path(sys.argv[1])
record=json.loads(path.read_text())
print(f"Patch journal: {path}")
for key in ("game_id","source","backup","state","expected_ra_hash","actual_ra_hash","error"):
    if record.get(key):
        print(f"  {key}: {record[key]}")
PY
}
opl_recover() {
  local selected source result=0 answer
  mkdir -p -m 0700 "$OPL_JOURNAL_DIR" || return 1
  echo 'Available bulk rename journals:'
  find "$OPL_JOURNAL_DIR" -maxdepth 1 -type f -name 'opl-rename-*.json' -printf '%f\n' | sort
  read -rp 'Enter the exact journal filename: ' selected
  [[ "$selected" =~ ^opl-rename-[A-Za-z0-9T-]+\.json$ ]] || { echo 'Invalid journal filename'; return 1; }
  local journal="$OPL_JOURNAL_DIR/$selected"
  [[ -f "$journal" ]] || { echo 'Journal not found.'; return 1; }
  echo 'Inspecting filesystem via the read-only mount (elevated read permissions):'
  sudo python3 "$HERE/opl_pilot.py" status --csv "$PILOT_CSV" --root "$MOUNT" --journal "$journal" || return 1
  read -rp 'Type RESUME to finish pending renames, or press Enter to cancel: ' answer
  [[ "$answer" == RESUME ]] || return 0
  source="$(findmnt -n -o SOURCE --target "$MOUNT")"
  [[ "$source" == //* ]] || return 1
  sudo install -d -m 0700 "$PILOT_ROOT" || return 1
  mountpoint -q "$PILOT_ROOT" && { echo 'Temporary RW mount already active.'; return 1; }
  sudo mount -t cifs "$source" "$PILOT_ROOT" -o "rw,credentials=/etc/retrodb/retronas.credentials,vers=3.1.1,iocharset=utf8,uid=$(id -u),gid=$(id -g),file_mode=0600,dir_mode=0700,actimeo=0,cache=none,nosuid,nodev,noexec" || return 1
  python3 "$HERE/opl_pilot.py" resume --csv "$PILOT_CSV" --root "$PILOT_ROOT" --journal "$journal" || result=$?
  sudo umount "$PILOT_ROOT" || { echo 'WARNING: RW mount remains active.'; return 1; }
  echo "Journal: $journal"
  return "$result"
}

run() { if "$@"; then echo '[OK] Operation completed.'; else echo '[ERROR] Operation failed.' >&2; fi; }
service_details() {
  echo
  systemctl --no-pager --full status retrodb.service xerabora.service || true
  echo
  sudo bash "$HERE/retronas.sh" status || true
}
more_menu() {
  local choice
  while true; do
    header
    echo ' MORE OPTIONS'
    echo '----------------------------------------------------------------'
    echo '  1) Export reports            - Rebuild Excel from last audit'
    echo '  2) Download official patches - Refresh local patch packages'
    echo '  3) Service status            - RetroDB, xeRAbora and RetroNAS'
    echo '  4) Recover OPL renames       - Inspect or resume rename journal'
    echo '  5) View patch journal        - Inspect latest patch operation'
    echo '  6) Update RetroDB            - Redeploy backend, migrations and service'
    echo '  7) Upgrade Debian            - Preview and apply system package upgrades'
    echo
    echo '  0) Back to main menu'
    echo '----------------------------------------------------------------'
    read -rp 'Choose an option: ' choice || return 0
    case "$choice" in
      1) run export_csv; pause ;;
      2) run patch_download; pause ;;
      3) run service_details; pause ;;
      4) run opl_recover; pause ;;
      5) run patch_journal_status; pause ;;
      6) run bash "$HERE/maintenance.sh" retrodb; pause ;;
      7) run bash "$HERE/maintenance.sh" system; pause ;;
      0|q|Q) return 0 ;;
      *) echo 'Invalid option.'; pause ;;
    esac
  done
}
menu() {
  local choice
  while true; do
    header
    echo '  1) Audit game collection  - Scan, check RA support and export reports'
    echo '  2) Patch a PS2 game       - Test, verify and preserve original'
    echo '  3) Rename PS2 games       - Preview changes and confirm renames'
    echo
    echo '  4) More options           - Exports, downloads and diagnostics'
    echo '  0) Exit'
    echo '----------------------------------------------------------------'
    echo ' https://github.com/theretrobristolian/retrodb'
    echo ' Update: cd ~/retrodb && git pull --ff-only origin main'
    echo '----------------------------------------------------------------'
    read -rp 'Choose an option: ' choice || break
    case "$choice" in
      1) run audit; pause ;;
      2) run patch_retronas_one; pause ;;
      3) run opl_update_all; pause ;;
      4) more_menu ;;
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
