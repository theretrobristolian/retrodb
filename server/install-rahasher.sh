#!/usr/bin/env bash
set -Eeuo pipefail
umask 027
VERSION=1.8.3
ARCHIVE=RAHasher-x64-Linux-${VERSION}.zip
EXPECTED_SHA256=bb98dcb38f6491aafd3450be4024b7e5465c13a0ca72bfe17d315780771be337
URL=https://github.com/LeXofLeviafan/RAHasher/releases/download/${VERSION}/${ARCHIVE}
INSTALL_DIR=/opt/retrodb-tools
VERSION_FILE=${INSTALL_DIR}/rahasher.version
[[ $EUID -eq 0 ]] || { printf '[ERROR] Run with sudo or as root.\n' >&2; exit 1; }
[[ $(uname -m) == x86_64 ]] || { printf '[ERROR] RAHasher installer currently supports x86_64 only.\n' >&2; exit 1; }
if [[ -x $INSTALL_DIR/RAHasher && -f $VERSION_FILE ]] && grep -qx "$VERSION" "$VERSION_FILE"; then exit 0; fi
temporary=$(mktemp -d /tmp/retrodb-rahasher.XXXXXX)
trap 'rm -rf -- "$temporary"' EXIT
curl --fail --location --silent --show-error --retry 3 "$URL" -o "$temporary/$ARCHIVE"
printf '%s  %s\n' "$EXPECTED_SHA256" "$temporary/$ARCHIVE" | sha256sum --check --status
unzip -q "$temporary/$ARCHIVE" -d "$temporary/unpacked"
binary=$(find "$temporary/unpacked" -type f -name 'RAHasher' | head -n 1)
[[ -n $binary ]] || { printf '[ERROR] RAHasher binary was not found in verified archive.\n' >&2; exit 1; }
install -d -o root -g retrodb -m 0750 "$INSTALL_DIR"
install -o root -g retrodb -m 0750 "$binary" "$INSTALL_DIR/RAHasher"
printf '%s\n' "$VERSION" > "$VERSION_FILE"
chown root:retrodb "$VERSION_FILE"
chmod 0640 "$VERSION_FILE"
