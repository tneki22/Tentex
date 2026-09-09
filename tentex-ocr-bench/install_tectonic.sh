#!/usr/bin/env bash
set -euo pipefail
VERSION="0.15.0"
DEST="${1:-$HOME/.local/bin}"
mkdir -p "$DEST"
URL="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${VERSION}/tectonic-${VERSION}-x86_64-unknown-linux-musl.tar.gz"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -L --fail --retry 3 "$URL" -o "$TMP/tectonic.tar.gz"
tar -xzf "$TMP/tectonic.tar.gz" -C "$DEST"
chmod +x "$DEST/tectonic"
"$DEST/tectonic" --version
