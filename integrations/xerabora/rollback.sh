#!/usr/bin/env bash
# Restore the last xeRAbora installation without touching player profiles.
set -Eeuo pipefail
DIR=/opt/xerabora
UNIT=/etc/systemd/system/xerabora.service
[[ $(id -u) != 0 ]] || { echo "Run as normal user with sudo, not sudo bash." >&2; exit 1; }
for name in xerabora-linux-x86_64 OPL-RA.ELF VERSION; do
  sudo test -f "$DIR/$name.previous" || {
    echo "[ERROR] Missing $DIR/$name.previous; cannot safely roll back." >&2
    exit 1
  }
done
sudo test -f "$UNIT" || { echo "[ERROR] Missing $UNIT" >&2; exit 1; }
echo "[INFO] Current version: $(sudo cat "$DIR/VERSION")"
echo "[INFO] Rollback version: $(sudo cat "$DIR/VERSION.previous")"
echo "[INFO] Stop xeRAbora and restore previous binary, ELF and version marker."
read -rp 'Type ROLLBACK to continue: ' answer
[[ "$answer" == ROLLBACK ]] || { echo "Cancelled."; exit 0; }
sudo systemctl stop xerabora.service
sudo cp -a "$DIR/xerabora-linux-x86_64" "$DIR/xerabora-linux-x86_64.failed-before-rollback"
sudo cp -a "$DIR/OPL-RA.ELF" "$DIR/OPL-RA.ELF.failed-before-rollback"
sudo cp -a "$DIR/VERSION" "$DIR/VERSION.failed-before-rollback"
for name in xerabora-linux-x86_64 OPL-RA.ELF VERSION; do
  sudo cp -a "$DIR/$name.previous" "$DIR/$name"
done
# Previous version predates --server. Preserve Web UI and profile drop-ins.
sudo sed -i '/^ExecStart=/s/ --server\([[:space:]]\|$\)/\1/g' "$UNIT"
sudo systemctl daemon-reload
sudo systemctl reset-failed xerabora.service
sudo systemctl start xerabora.service
# ExecStartPre may sleep 20 seconds; distinguish startup from active daemon.
for attempt in {1..35}; do
  if systemctl is-active --quiet xerabora.service; then break; fi
  sleep 1
done
if ! systemctl is-active --quiet xerabora.service; then
  echo "[ERROR] Restored service did not become active." >&2
  sudo journalctl -u xerabora.service -n 35 --no-pager >&2
  exit 1
fi
sleep 3
if ! systemctl is-active --quiet xerabora.service; then
  echo "[ERROR] Service exited after activation." >&2
  sudo journalctl -u xerabora.service -n 35 --no-pager >&2
  exit 1
fi
echo "[OK] Restored xeRAbora $(sudo cat "$DIR/VERSION") and service is active."
echo "[INFO] Test web UI: curl -I http://127.0.0.1:18280/"
echo "[INFO] Test PS2: OPL-RA > Triangle > RA: test PC connection"
