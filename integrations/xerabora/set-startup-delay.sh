#!/usr/bin/env bash
# Configure the xeRAbora systemd pre-start pause without restarting the service.
set -euo pipefail
DELAY="${1:-10}"
if [[ ! "$DELAY" =~ ^[0-9]+$ ]] || (( DELAY > 120 )); then
  echo "Usage: sudo bash integrations/xerabora/set-startup-delay.sh [seconds: 0..120]" >&2
  exit 2
fi
if (( EUID != 0 )); then echo "Run with sudo" >&2; exit 1; fi
if ! systemctl cat xerabora.service >/dev/null 2>&1; then
  echo "xerabora.service is not installed" >&2; exit 1
fi
DIR=/etc/systemd/system/xerabora.service.d
FILE="$DIR/restart.conf"
mkdir -p "$DIR"
if [[ -f "$FILE" ]]; then
  if ! grep -q '^# xeRAbora startup mode: auto$' "$FILE"; then
    echo "Existing restart.conf is not in automatic mode. No changes made." >&2
    exit 1
  fi
fi
# Preserve the existing recovery policy; only modify the start delay.
if [[ -f "$FILE" ]] && grep -Eq '^ExecStartPre=/bin/sleep [0-9]+$' "$FILE"; then
  sed -i -E "s|^ExecStartPre=/bin/sleep [0-9]+$|ExecStartPre=/bin/sleep $DELAY|" "$FILE"
else
  cat > "$FILE" <<EOF
# xeRAbora startup mode: auto
[Service]
ExecStartPre=
ExecStartPre=/bin/sleep $DELAY
Restart=always
RestartSec=10
EOF
fi
systemctl daemon-reload
echo "xeRAbora pre-start delay now ${DELAY}s; running service left untouched."
systemctl show xerabora.service -p ExecStartPre
