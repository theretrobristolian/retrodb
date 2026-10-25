#!/usr/bin/env bash
# Publish nonsecret, read-only online compatibility data for RetroDB's web service.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo from the VM user account.' >&2; exit 1; }
caller="${SUDO_USER:-}"
[[ -n "$caller" && "$caller" != root ]] || { echo '[ERROR] Run via sudo as the user who imported the datasets.' >&2; exit 1; }
src="/home/$caller/.cache/retrodb"
dest="/var/cache/retrodb/web"
install -d -o retrodb -g retrodb -m 0750 "$dest"
for dataset in online-compatibility.json xlink-ps2.json; do
  if [[ -f "$src/$dataset" ]]; then
    # Read as owning user to avoid sudo loading untrusted paths.
    tmp="$(mktemp)"
    if runuser -u "$caller" -- cat "$src/$dataset" > "$tmp"; then
      python3 -m json.tool "$tmp" >/dev/null
      install -o retrodb -g retrodb -m 0640 "$tmp" "$dest/$dataset"
      echo "[OK] Published $dataset"
    fi
    rm -f "$tmp"
  else
    echo "[INFO] No $dataset to publish"
  fi
done
