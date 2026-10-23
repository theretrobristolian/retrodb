#!/usr/bin/env bash
# Register persistent menu shortcuts against this repository checkout.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
MODE="${1:-all}"
case "$MODE" in all|retrodb|xerabora) ;; *) echo 'Usage: install-launchers.sh [all|retrodb|xerabora]' >&2; exit 2 ;; esac
command -v sudo >/dev/null || [[ "$EUID" -eq 0 ]] || { echo '[ERROR] sudo is required.' >&2; exit 1; }

install_launcher() {
  local name="$1" target="$2" tmp quoted
  [[ -f "$target" ]] || { echo "[ERROR] Missing: $target" >&2; return 1; }
  tmp="$(mktemp)"
  printf -v quoted '%q' "$target"
  printf '#!/usr/bin/env bash\nexec /bin/bash %s "$@"\n' "$quoted" >"$tmp"
  if [[ "$EUID" -eq 0 ]]; then
    install -o root -g root -m 0755 "$tmp" "/usr/local/bin/$name"
  else
    sudo install -o root -g root -m 0755 "$tmp" "/usr/local/bin/$name"
  fi
  rm -f "$tmp"
  echo "[OK] Installed command: $name"
}
if [[ "$MODE" == all || "$MODE" == retrodb ]]; then
  install_launcher retrodb "$ROOT/server/manager.sh"
  echo '      Start the RetroDB menu by typing: retrodb'
fi
if [[ "$MODE" == all || "$MODE" == xerabora ]]; then
  install_launcher xerabora "$ROOT/integrations/xerabora/install.sh"
  if [[ "$EUID" -eq 0 ]]; then
    ln -sfn xerabora /usr/local/bin/xeRAbora
  else
    sudo ln -sfn xerabora /usr/local/bin/xeRAbora
  fi
  echo '      Start the xeRAbora menu by typing: xerabora (or xeRAbora)'
fi
