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
web() {
  local status
  status="$(curl -sS -m 2 -o /dev/null -w '%{http_code}' "$1" 2>/dev/null)" || {
    echo unavailable
    return
  }
  case "$status" in
    200) echo responding ;;
    401|403) echo 'auth required' ;;
    *) echo "HTTP $status" ;;
  esac
}
retronas_mount_state() {
  if findmnt -rn -M "$MOUNT" -t cifs >/dev/null 2>&1; then
    echo mounted
  elif systemctl is-active --quiet "$(systemd-escape --path --suffix=automount "$MOUNT")"; then
    echo 'on-demand'
  else
    echo unmounted
  fi
}
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
  # Keep health rows compact; URLs remain available in service details.
  local hasher report
  hasher="$(protected_status -x /opt/retrodb-tools/RAHasher)"
  report="$(protected_status -f "$REPORT")"
  [[ "$hasher" == "protected / unavailable" ]] && hasher="unavailable"
  [[ "$report" == "protected / unavailable" ]] && report="unavailable"
  printf ' %-12s %-13s %-12s %s\n' 'RetroDB:' "$(state retrodb.service)" 'Local API:' "$(web http://127.0.0.1:8000/health)"
  printf ' %-12s %-13s %-12s %s\n' 'PostgreSQL:' "$(state postgresql.service)" 'RetroNAS:' "$(retronas_mount_state)"
  printf ' %-12s %-13s %-12s %s\n' 'RAHasher:' "$hasher" 'CSV report:' "$report"
  printf ' %-12s %-13s %-12s %s\n' 'xeRAbora:' "$(state xerabora.service)" 'Web UI:' "$(web http://retrodb.it.gattaca.house:18280/)"
  echo '----------------------------------------------------------------'
}
pause() { read -rp 'Press Enter to return...' ignored || true; }
# Resolve the actual CIFS filesystem, never the enclosing systemd automount.
# --target without -t cifs can return both systemd-1 and //server/share.
retronas_cifs_source() {
  local source unit
  # The systemd .automount can shadow the actual CIFS mount, and the
  # audit path may be inaccessible to the ordinary user. Ask the .mount
  # unit for its configured What= instead of probing the directory.
  unit="$(systemd-escape --path --suffix=mount "$MOUNT")" || return 1
  source="$(systemctl show "$unit" -p What --value 2>/dev/null || true)"
  if [[ "$source" != //* ]]; then
    source="$(findmnt -rn -M "$MOUNT" -t cifs -o SOURCE 2>/dev/null || true)"
  fi
  if [[ "$source" != //* || "$source" == *$'\n'* || "$source" == *$'\r'* ]]; then
    echo "[STOP] Could not resolve one SMB //server/share source from $unit: ${source:-none}" >&2
    return 1
  fi
  printf '%s\n' "$source"
}

mount_ready() {
  mountpoint -q "$MOUNT" && return 0
  read -rp 'RetroNAS unmounted. Mount it now? [y/n] (default: no) ' ans
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
  local ps1_csv="$HOME/retrodb-exports/RetroDB-PS1-Audit.csv"
  local ps1_root="$MOUNT/roms/sony/playstation1"
  if sudo test -d "$ps1_root"; then
    ( umask 077; sudo python3 "$HERE/report_ps1_audit.py" --root "$ps1_root" --output "$ps1_csv" ) || return 1
    sudo chown "$(id -un):$(id -gn)" "$ps1_csv" || return 1
    chmod 0600 "$ps1_csv" || return 1
  else
    echo '[WARNING] PS1 folder unavailable; export will omit the PS1 file audit.'
    rm -f "$ps1_csv"
  fi
  local prep_arg="-"
  if sudo -n test -f "$prepare" 2>/dev/null || sudo test -f "$prepare"; then
    sudo install -m 0600 -o "$(id -un)" -g "$(id -gn)" "$prepare" "$prepared_copy" || return 1
    prep_arg="$prepared_copy"
  else
    echo '[INFO] Patch preparation unavailable; verified patch evidence omitted.'
  fi
  if [[ -f "$ps1_csv" ]]; then
    ( umask 077; python3 "$HERE/report_excel.py" "$EXPORT" "$excel" "$prep_arg" "$ps1_csv" ) || return 1
  else
    ( umask 077; python3 "$HERE/report_excel.py" "$EXPORT" "$excel" "$prep_arg" ) || return 1
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
  printf ' PS1 file audit CSV   : %s\n' "$ps1_csv"
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
  sudo -u retrodb env PYTHONPATH=/opt/retrodb/backend /opt/retrodb/.venv/bin/python -m retrodb.providers.gamedb --platform playstation-2 || return 1
  sudo -u retrodb env PYTHONPATH=/opt/retrodb/backend /opt/retrodb/.venv/bin/python -m retrodb.providers.gamedb --platform playstation
}

audit() {
  stage "1/8" "Prerequisites and read-only RetroNAS connection"
  mount_ready || { echo 'Audit cancelled: RetroNAS unavailable.' >&2; return 1; }
  sudo test -x /opt/retrodb-tools/RAHasher || { echo '[ERROR] RAHasher unavailable.' >&2; return 1; }
  printf '[OK] RetroNAS mounted; RAHasher available.\n'
  step "2/8" "Synchronise RetroAchievements catalogue (cache-aware)" sudo bash "$HERE/retroachievements.sh" sync || return 1
  step "3/8" "Synchronise PS1 / PS2 GameDB catalogues (cache-aware)" sync_gamedb || return 1
  step "4/8" "Inventory PS1 / PS2 collection (read-only)" sudo bash "$HERE/retronas.sh" scan || return 1
  step "5/8" "Hash and match disc images against RetroAchievements" sudo bash "$HERE/retronas.sh" match || return 1
  step "6/8" "Prepare official patch manifest" sudo bash "$HERE/retronas.sh" patch-plan || return 1
  step "7/8" "Download / reuse official patches, verify existing source ISOs" patch_audit || return 1
  step "8/8" "Export formatted Excel workbook and raw CSV" export_csv || return 1
  printf '\n[COMPLETE] Full collection audit and downloadable workbook ready.\n'
  echo 'NOTE: No original RetroNAS game images were changed.'
}
patch_audit() {
  # Time the two distinct operations to identify download versus SMB checksum cost.
  # Individual patch download failures must not block source verification.
  local started download_started verify_started ended download_rc=0 verify_rc=0
  started="$(date +%s)"
  printf '[TIMING] Stage 7 started: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"

  download_started="$(date +%s)"
  printf '[TIMING] Patch download/cache check started: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
  sudo bash "$HERE/retronas.sh" patch-download || download_rc=$?
  printf '[TIMING] Patch download/cache check ended: %s | elapsed: %ss\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$(($(date +%s) - download_started))"
  (( download_rc == 0 )) || echo "[WARN] Some patch downloads failed; checking available packages anyway."

  verify_started="$(date +%s)"
  printf '[TIMING] Source ISO checksum verification started: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
  sudo bash "$HERE/retronas.sh" patch-prepare || verify_rc=$?
  ended="$(date +%s)"
  printf '[TIMING] Source ISO checksum verification ended: %s | elapsed: %ss\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$((ended - verify_started))"
  printf '[TIMING] Stage 7 ended: %s | total elapsed: %ss\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$((ended - started))"
  return "$verify_rc"
}
patch_download() {
  mount_ready || return 1
  step "1/2" "Generate official patch manifest" sudo bash "$HERE/retronas.sh" patch-plan || return 1
  step "2/2" "Download / reuse safe patch packages" sudo bash "$HERE/retronas.sh" patch-download
  printf '\nPatches are stored locally under /var/lib/retrodb/patches/downloads.\n'
  echo 'No ISO has been patched and RetroNAS has not been modified.'
}
patch_apply() {
  local game_id confirm
  mount_ready || return 1
  echo 'Checking checksum-verified patch sources for PS1 and PS2...'
  step "1/2" "Refresh verified patch source list" sudo bash "$HERE/retronas.sh" patch-prepare || return 1
  echo
  echo 'READY TO PATCH (verified original checksum; no RetroNAS writes):'
  sudo python3 - <<'PYREADY'
import json
from pathlib import Path
w = Path('/var/lib/retrodb/patches')
try:
    plans = json.loads((w / 'patch-plan.json').read_text())
    prepared = json.loads((w / 'patch-prepare.json').read_text())
except (OSError, ValueError) as exc:
    print(f'[ERROR] Cannot load patch manifest: {exc}')
    raise SystemExit(1)
by_title = {str(p.get('title')): p for p in plans}
ready = {}
for entry in prepared:
    if entry.get('state') != 'clean-base-verified-ready-to-patch':
        continue
    plan = by_title.get(str(entry.get('title')), {})
    game_id = str(plan.get('ra_game_id', ''))
    if not game_id.isdecimal() or plan.get('platform') not in ('Sony PlayStation', 'Sony PlayStation 2'):
        continue
    if entry.get('candidate_path') != entry.get('collection_source'):
        continue
    ready.setdefault(game_id, []).append((plan, entry))
for game_id, variants in sorted(ready.items(), key=lambda x: int(x[0])):
    for plan, entry in variants:
        print(f"  RA ID {game_id} [{plan['platform']}]: {plan.get('required_release') or plan.get('title')} ")
if not ready:
    print('  None ready. Review patch-download.json and patch-prepare.json.')
PYREADY
  read -rp 'Enter ONE RA game ID to patch (Enter cancels): ' game_id
  [[ "$game_id" =~ ^[0-9]{1,8}$ ]] || { echo 'Cancelled / invalid RA ID.'; return 0; }
  sudo python3 - "$game_id" <<'PYCHECK' || { echo '[STOP] No checksum-verified source for that RA game ID.'; return 1; }
import json, sys
from pathlib import Path
w=Path('/var/lib/retrodb/patches')
plans=json.loads((w/'patch-plan.json').read_text())
ready=json.loads((w/'patch-prepare.json').read_text())
titles={str(x.get('title')) for x in plans if str(x.get('ra_game_id')) == sys.argv[1]
        and x.get('platform') in ('Sony PlayStation', 'Sony PlayStation 2')}
ok=any(r.get('state')=='clean-base-verified-ready-to-patch'
       and r.get('title') in titles
       and r.get('candidate_path')==r.get('collection_source') for r in ready)
sys.exit(0 if ok else 1)
PYCHECK
  if sudo python3 - "$game_id" <<'PYEXIST'
import json, sys
from pathlib import Path
try:
    entries=json.loads(Path('/var/lib/retrodb/patches/patch-apply.json').read_text())
    found=[e for e in entries if str(e.get('ra_game_id'))==sys.argv[1] and e.get('status')=='patched-and-verified'
           and Path(e.get('output','')).is_file() and Path(e.get('cue','')).is_file()]
    sys.exit(0 if len(found)==1 else 1)
except (OSError, ValueError):
    sys.exit(1)
PYEXIST
  then
    echo '[OK] Existing verified local BIN/CUE available; skipping unnecessary patch repeat.'
  else
    echo 'Patch selected game locally; RetroNAS stays read-only until deployment confirmation.'
    read -rp "Type PATCH-$game_id to confirm local patch: " confirm
    [[ "$confirm" == "PATCH-$game_id" ]] || { echo 'Cancelled.'; return 0; }
    step "2/2" "Apply selected patch and verify its RA hash" sudo bash "$HERE/retronas.sh" patch-apply --game-id "$game_id" || return 1
  fi
  echo '[OK] Local patch RA-verified.'
  sudo python3 - "$game_id" <<'PYPLATFORM'
import json,sys
from pathlib import Path
rows=json.loads(Path('/var/lib/retrodb/patches/patch-plan.json').read_text())
match=[r for r in rows if str(r.get('ra_game_id'))==sys.argv[1]]
print('[INFO] Patched game platform:', ', '.join(sorted({str(r.get('platform')) for r in match})))
PYPLATFORM
  if sudo python3 - "$game_id" <<'PYISPS1'
import json,sys
from pathlib import Path
rows=json.loads(Path('/var/lib/retrodb/patches/patch-plan.json').read_text())
sys.exit(0 if any(str(r.get('ra_game_id'))==sys.argv[1] and r.get('platform')=='Sony PlayStation' for r in rows) else 1)
PYISPS1
  then
    deploy_ps1_patch "$game_id"
  else
    echo '[INFO] PS2 local result ready. Existing PS2 network deployment remains a separate legacy workflow.'
  fi
}
deploy_ps1_patch() {
  local game_id answer source journal result=0
  mount_ready || return 1
  game_id="${1:-}"
  if [[ -z "$game_id" ]]; then
    read -rp 'Enter the single PS1 RA game ID to deploy (e.g. 10907): ' game_id
  fi
  [[ "$game_id" =~ ^[0-9]{1,8}$ ]] || { echo 'Cancelled.'; return 0; }
  if ! sudo python3 - "$game_id" <<'PYPATCH'
import json,sys
from pathlib import Path
p=Path('/var/lib/retrodb/patches/patch-apply.json')
rows=json.loads(p.read_text())
assert any(str(r.get('ra_game_id'))==sys.argv[1] and r.get('status')=='patched-and-verified' for r in rows)
PYPATCH
  then
    echo '[INFO] No locally verified patch result for this ID (or not a PS1 patch).'
    return 0
  fi
  echo 'This PS1 deployment retains original BIN and CUE as OLD_ backups and replaces the active pair.'
  echo 'Patch must already be locally RA-verified. Existing OLD_ files are never overwritten.'
  read -rp "Type DEPLOY-$game_id to confirm NAS changes: " answer
  [[ "$answer" == "DEPLOY-$game_id" ]] || { echo 'Cancelled.'; return 0; }
  source="$(retronas_cifs_source)" || return 1
  [[ "$source" == //* ]] || { echo "[STOP] Invalid CIFS source: $source"; return 1; }
  mountpoint -q "$PILOT_ROOT" && { echo '[STOP] Writable mount already active.'; return 1; }
  sudo install -d -m 0700 "$PILOT_ROOT" || return 1
  sudo mount -t cifs "$source" "$PILOT_ROOT" -o "rw,credentials=/etc/retrodb/retronas.credentials,vers=3.1.1,iocharset=utf8,uid=$(id -u),gid=$(id -g),file_mode=0600,dir_mode=0700,actimeo=0,cache=none,nosuid,nodev,noexec" || return 1
  mkdir -p -m 0700 "$OPL_JOURNAL_DIR" || return 1
  journal="$OPL_JOURNAL_DIR/ps1-deploy-$(date -u +%Y%m%dT%H%M%SZ)-$game_id-$BASHPID.json"
  sudo env PYTHONPATH=/opt/retrodb/backend /opt/retrodb/.venv/bin/python \
    "$HERE/deploy_ps1_patch.py" --game-id "$game_id" --ro-mount "$MOUNT" \
    --rw-mount "$PILOT_ROOT" --journal "$journal" || result=$?
  sudo umount "$PILOT_ROOT" || { echo '[WARNING] Writable mount remains active.'; return 1; }
  echo "Deployment journal: $journal"
  return "$result"
}
# Separate, temporary CIFS write mount; the audit mount remains read-only.
PILOT_ROOT=/mnt/retrodb-retronas-pilot-rw
PILOT_CSV="$HOME/retrodb-exports/RetroDB-OPL-Rename-Proposals.csv"
OPL_JOURNAL_DIR="$HOME/retrodb-exports/opl-rename-journals"
ps1_rename_all() {
  local csv="$HOME/retrodb-exports/RetroDB-PS1-Audit.csv"
  local journal_dir="$HOME/retrodb-exports/ps1-rename-journals"
  local journal="" source result=0 answer
  [[ -r "$csv" ]] || { echo 'Export reports first to generate a current PS1 audit.'; return 1; }
  mountpoint -q "$MOUNT" || { echo 'RetroNAS read-only mount unavailable.'; return 1; }
  mkdir -p -m 0700 "$journal_dir" || return 1
  local prior
  while IFS= read -r prior; do
    if python3 - "$prior" <<'PYJ'
import json, sys
try:
    operations = json.load(open(sys.argv[1], encoding='utf-8'))['operations']
    incomplete = any(op.get('state') != 'applied' for op in operations)
except (OSError, ValueError, KeyError):
    incomplete = True
sys.exit(0 if incomplete else 1)
PYJ
    then
      echo "[STOP] Incomplete PS1 rename journal: $prior"
      echo 'Inspect or recover the files before attempting another batch.'
      return 1
    fi
  done < <(find "$journal_dir" -maxdepth 1 -name '*.json' -type f | sort)
  # Require GameDB titles from the same authoritative catalogue as PS2 naming.
  sync_gamedb || return 1
  # Always rescan before a rename; cached proposals can be stale after a prior run.
  ( umask 077; sudo python3 "$HERE/report_ps1_audit.py" --root "$MOUNT/roms/sony/playstation1" --output "$csv" ) || return 1
  sudo chown "$(id -un):$(id -gn)" "$csv" || return 1
  chmod 0600 "$csv" || return 1
  sudo python3 "$HERE/ps1_rename.py" preview --csv "$csv" --root "$MOUNT/roms/sony/playstation1" || return 1
  echo "[CHECK] RA-verified name conflicts (preview only):"
  sudo python3 "$HERE/ps1_ra_conflict.py" preview --root "$MOUNT/roms/sony/playstation1" || return 1
  local eligible conflict_count
  eligible="$(sudo python3 - "$HERE" "$csv" "$MOUNT/roms/sony/playstation1" <<'PYCOUNT'
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from ps1_rename import parse
print(len(parse(SimpleNamespace(csv=Path(sys.argv[2]), root=Path(sys.argv[3]), limit=None))))
PYCOUNT
)" || return 1
  conflict_count="$(sudo python3 "$HERE/ps1_ra_conflict.py" count --root "$MOUNT/roms/sony/playstation1")" || return 1
  if [[ "$eligible" == 0 && "$conflict_count" == 0 ]]; then
    echo '[OK] No eligible PS1 renames remain; nothing changed and no journal created.'
    return 0
  fi
  echo '[BULK] Eligible PS1 renames and explicitly previewed RA-confirmed collision resolutions will be applied.'
  read -rp 'Type RENAMEPS1 to rename ALL eligible pairs: ' answer
  [[ "$answer" == RENAMEPS1 ]] || { echo 'Cancelled'; return 0; }
  source="$(retronas_cifs_source)" || return 1
  [[ "$source" == //* ]] || { echo "Unexpected CIFS source: $source"; return 1; }
  sudo install -d -m 0700 "$PILOT_ROOT" || return 1
  if mountpoint -q "$PILOT_ROOT"; then
    echo 'Temporary writable mount already active; refusing to proceed.'; return 1
  fi
  sudo mount -t cifs "$source" "$PILOT_ROOT" -o "rw,credentials=/etc/retrodb/retronas.credentials,vers=3.1.1,iocharset=utf8,uid=$(id -u),gid=$(id -g),file_mode=0600,dir_mode=0700,actimeo=0,cache=none,nosuid,nodev,noexec" || return 1
  # Resolve reviewed RA-verified same-disc collisions first. Keep their
  # recovery journal separate from the ordinary PS1 bulk-rename journals.
  # Never run a second collision operation with an incomplete journal.
  local conflict_dir="$HOME/retrodb-exports/ps1-conflict-journals"
  mkdir -p -m 0700 "$conflict_dir" || return 1
  local cj
  for cj in "$conflict_dir"/*.json; do
    [[ -f "$cj" ]] || continue
    if ! python3 - "$cj" <<'PYCONF'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        state = json.load(f).get("state")
    sys.exit(0 if state == "applied" else 1)
except (OSError, ValueError):
    sys.exit(1)
PYCONF
    then
      echo "[STOP] Incomplete PS1 collision journal: $cj" >&2
      echo "[STOP] Inspect recovery before another writable rename." >&2
      result=1
      break
    fi
  done
  if [[ "$result" -eq 0 && "$conflict_count" != 0 ]]; then
    cj="$conflict_dir/ps1-conflict-$(date -u +%Y%m%dT%H%M%SZ)-$BASHPID.json"
    sudo python3 "$HERE/ps1_ra_conflict.py" apply --root "$PILOT_ROOT/roms/sony/playstation1" --journal "$cj" || result=$?
    local created=0 conflict_journal
    for conflict_journal in "${cj%.json}"-*.json; do
      [[ -f "$conflict_journal" ]] || continue
      created=1
      sudo chown "$(id -un):$(id -gn)" "$conflict_journal" || result=1
      echo "Conflict journal: $conflict_journal"
    done
    if [[ "$created" == 0 ]]; then
      echo "[INFO] No conflict journal created (the operation stopped before any rename)." >&2
    fi
  fi
  if [[ "$result" -eq 0 ]]; then
    # A resolved collision changes file names, so regenerate proposals using
    # the writable view before applying the ordinary non-collision renames.
    ( umask 077; sudo python3 "$HERE/report_ps1_audit.py" --root "$PILOT_ROOT/roms/sony/playstation1" --output "$csv" && sudo chown "$(id -un):$(id -gn)" "$csv" ) || result=$?
  fi
  if [[ "$result" -eq 0 && "$eligible" != 0 ]]; then
    journal="$journal_dir/ps1-rename-$(date -u +%Y%m%dT%H%M%SZ)-$BASHPID.json"
    python3 "$HERE/ps1_rename.py" apply --csv "$csv" --root "$PILOT_ROOT/roms/sony/playstation1" --journal "$journal" || result=$?
  fi

  sudo umount "$PILOT_ROOT" || { echo '[WARNING] Writable mount remains active!'; return 1; }
  [[ -n "$journal" && -f "$journal" ]] && echo "PS1 rename journal: $journal"
  [[ "$result" -eq 0 ]] || echo '[WARNING] Incomplete operation: inspect journal before any rerun.'
  return "$result"
}
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
  source="$(retronas_cifs_source)" || return 1
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
ready_count=0
for r in json.loads((w/'patch-prepare.json').read_text()):
    p=next((x for x in plans if x.get('title')==r.get('title') and x.get('local_path') and str((Path('/mnt/retrodb-retronas') / x['local_path'])) == r.get('collection_source')),None)
    if p and p.get('platform')=='Sony PlayStation 2' and r.get('state')=='clean-base-verified-ready-to-patch' and r.get('candidate_path')==r.get('collection_source'):
        ready_count += 1
        print(f"  RA ID {p['ra_game_id']}: {p['required_release']} -- {p['local_path']}")
if not ready_count:
    print('  None verified yet. Review /var/lib/retrodb/patches/patch-download.json')
    print('  and /var/lib/retrodb/patches/patch-prepare.json for individual failures.')
else:
    print(f'  {ready_count} checksum-verified sources ready.')
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
  source="$(retronas_cifs_source)" || return 1
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
  source="$(retronas_cifs_source)" || return 1
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
retronas_details() {
  local unit source dialect opts
  unit="$(systemd-escape --path --suffix=mount "$MOUNT")"
  echo ' RetroNAS connection'
  echo '----------------------------------------------------------------'
  printf ' Mount path: %s\n' "$MOUNT"
  source="$(systemctl show "$unit" -p What --value 2>/dev/null || true)"
  printf ' SMB share: %s\n' "${source:-not configured}"
  printf ' Unit state: %s\n' "$(systemctl is-active "$unit" 2>/dev/null || true)"
  printf ' At startup: %s\n' "$(systemctl is-enabled "$unit" 2>/dev/null || true)"
  if mountpoint -q "$MOUNT"; then
    echo ' Mount: connected'
    printf ' Filesystem: %s\n' "$(findmnt -n -o FSTYPE -T "$MOUNT" 2>/dev/null || echo unknown)"
    opts="$(findmnt -n -o OPTIONS -T "$MOUNT" 2>/dev/null || true)"
    dialect="$(printf '%s' "$opts" | grep -oE 'vers=[0-9.]+' | head -n 1 || true)"
    printf ' Requested SMB dialect: %s\n' "${dialect:-not shown in mount options}"
    echo ' Negotiated SMB details: sudo cat /proc/fs/cifs/DebugData'
    echo ' Network link rate: not determined by SMB dialect'
  else
    echo ' Mount: DISCONNECTED'
    echo ' No active SMB dialect can be reported.'
    echo ' View failure: sudo journalctl -u "'"$unit"'" -n 50'
  fi
}
retronas_menu() {
  local choice confirm
  while true; do
    header
    retronas_details
    echo '----------------------------------------------------------------'
    echo ' RetroNAS settings'
    echo
    echo '  1) Refresh mount (start existing configuration)'
    echo '  2) View mount error log'
    echo '  3) Change server / share / SMB login'
    echo '  4) Enable reliable on-demand mount at boot'
    echo '  0) Back'
    echo
    echo '----------------------------------------------------------------'
    read -rp 'Choose an option: ' choice || return 0
    case "$choice" in
      1) sudo bash "$HERE/retronas.sh" mount; pause ;;
      2) sudo journalctl -u "$(systemd-escape --path --suffix=mount "$MOUNT")" -n 70 --no-pager; pause ;;
      3)
        echo ' This replaces the mount settings and saved SMB login.'
        echo ' It restarts the RetroNAS mount; do not run during an audit.'
        read -rp 'Continue? [y/n] (default: no) ' confirm
        if [[ "$confirm" =~ ^[Yy]$ ]]; then
          sudo bash "$HERE/configure-retronas.sh"
        fi
        pause ;;
      4) sudo bash "$HERE/enable-retronas-automount.sh"; pause ;;
      0|q|Q) return 0 ;;
      *) echo 'Invalid option.'; pause ;;
    esac
  done
}
online_import_menu() {
  local source tmp csvurl
  csvurl='https://docs.google.com/spreadsheets/d/15pfhL36qmC-iKr8MNjNXNLwgacG4VOmkfvwVxV5vGzo/export?format=csv&gid=0'
  echo 'Import community PS2 online compatibility catalogue.'
  echo '  1) Fetch public community sheet now'
  echo '  2) Import an existing CSV file on this VM'
  echo '  0) Cancel'
  read -rp 'Choose: ' choice
  case "$choice" in
    1)
      source="$(mktemp)"
      if ! curl -fLsS --connect-timeout 10 --max-time 60 "$csvurl" -o "$source"; then
        rm -f "$source"
        echo '[ERROR] Could not fetch the public CSV. Download it manually and use option 2.'
        return 1
      fi
      ;;
    2)
      read -rp 'CSV path on this VM: ' source
      [[ -r "$source" && -f "$source" ]] || { echo '[ERROR] Cannot read CSV.'; return 1; }
      ;;
    0|'') return 0 ;;
    *) echo 'Invalid option.'; return 1 ;;
  esac
  tmp="$(mktemp)"
  if ! python3 "$HERE/online_catalogue.py" import-ps2 "$source" "$tmp"; then
    rm -f "$tmp"
    [[ "$choice" == 1 ]] && rm -f "$source"
    return 1
  fi
  if ! install -D -m 0600 "$tmp" "$HOME/.cache/retrodb/online-compatibility.json"; then
    rm -f "$tmp"
    [[ "$choice" == 1 ]] && rm -f "$source"
    return 1
  fi
  rm -f "$tmp"
  [[ "$choice" == 1 ]] && rm -f "$source"
  echo '[OK] Online catalogue updated in ~/.cache/retrodb.'
  echo '     Use More options -> Export reports to rebuild Excel.'
}
xlink_import_menu() {
  local tmp
  echo 'Import Team XLink verified PS2 LAN games (title-level evidence).'
  echo 'The source has no disc IDs; release/region support stays unverified.'
  tmp="$(mktemp)"
  if ! python3 "$HERE/import_xlink.py" "$tmp"; then
    rm -f "$tmp"
    echo '[WARN] XLink import failed; previous data (if any) was preserved.'
    return 1
  fi
  install -D -m 0600 "$tmp" "$HOME/.cache/retrodb/xlink-ps2.json" || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
  echo '[OK] XLink source imported. Re-export Excel reports to apply.'
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
    echo '  8) RetroNAS settings         - Mount, connection and server config'
    echo '  9) Import PS2 online data    - Community CSV to offline catalogue'
    echo ' 10) Refresh XLink PS2 LAN    - Official supported-game titles'
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
      8) retronas_menu ;;
      9) online_import_menu; pause ;;
     10) xlink_import_menu; pause ;;
      0|q|Q) return 0 ;;
      *) echo 'Invalid option.'; pause ;;
    esac
  done
}
menu() {
  local choice
  while true; do
    header
    echo ' Main menu'
    echo
    echo '  1) Audit games       - Check RA support and export reports'
    echo '  2) Patch PS1 / PS2   - Patch one game; deploy PS1 with OLD_ backup'
    echo '  3) Rename games      - PS1 preview / PS2 confirmed changes'
    echo
    echo '  4) More options           - Exports, downloads and diagnostics'
    echo '  0) Exit'
    echo
    echo '----------------------------------------------------------------'
    echo ' Community console by The Retro Bristolian'
    echo ' Source: https://github.com/theretrobristolian/retrodb'
    echo ' Run: retrodb  |  Script updates checked on launch'
    echo '----------------------------------------------------------------'
    read -rp 'Choose an option: ' choice || break
    case "$choice" in
      1) run audit; pause ;;
      2) run patch_apply; pause ;;
      3)
        echo '  1) PlayStation 1 - Rename all eligible BIN/CUE pairs'
        echo '  2) PlayStation 2 - Existing confirmed rename workflow'
        read -rp 'Platform: ' platform_choice
        case "$platform_choice" in
          1) run ps1_rename_all ;;
          2) run opl_update_all ;;
          *) echo 'Cancelled' ;;
        esac
        pause ;;
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
