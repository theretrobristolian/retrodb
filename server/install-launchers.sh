#!/usr/bin/env bash
# Install convenience launchers for the checked-out RetroDB repository.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ -f "$ROOT/server/manager.sh" && -f "$ROOT/integrations/xerabora/install.sh" ]] || {
  echo '[ERROR] Run this script from a complete RetroDB checkout.' >&2
  exit 1
}
[[ "${EUID}" -ne 0 ]] || {
  echo '[ERROR] Run as your normal login user; sudo is used only to install commands.' >&2
  exit 1
}
command -v sudo >/dev/null || { echo '[ERROR] sudo is required.' >&2; exit 1; }

install_launcher() {
  local name="$1" target="$2" tmp
  tmp="$(mktemp)"
  # Quote the actual checkout path, including whitespace, safely for bash.
  printf -v quoted '%q' "$target"
  cat >"$tmp" <<EOF
#!/usr/bin/env bash
exec /bin/bash $quoted "\$@"
EOF
  sudo install -o root -g root -m 0755 "$tmp" "/usr/local/bin/$name"
  rm -f "$tmp"
  echo "[OK] /usr/local/bin/$name -> $target"
}

install_launcher retrodb "$ROOT/server/manager.sh"
install_launcher xerabora "$ROOT/integrations/xerabora/install.sh"
# Optional spelling that matches the product name; lowercase is recommended.
sudo ln -sfn xerabora /usr/local/bin/xeRAbora
echo '[OK] Use: retrodb | xerabora | xeRAbora'
echo '[INFO] These commands track this checkout; git pull updates the scripts without reinstalling launchers.'
