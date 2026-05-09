#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$BASE_DIR/dist"
PKG_NAME="releaseplan-portable"
PKG_DIR="$OUT_DIR/$PKG_NAME"
ARCHIVE="$OUT_DIR/${PKG_NAME}.tar.gz"

rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR" "$OUT_DIR"

rsync -a \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.venv' \
  --exclude 'dist' \
  "$BASE_DIR/" "$PKG_DIR/"

chmod +x "$PKG_DIR/install.sh" "$PKG_DIR/package_release.sh" "$PKG_DIR/uninstall.sh" "$PKG_DIR/run-docker.sh"

if command -v python3 >/dev/null 2>&1; then
  mkdir -p "$PKG_DIR/vendor"
  python3 -m pip download -r "$BASE_DIR/requirements.txt" -d "$PKG_DIR/vendor"
fi

cd "$OUT_DIR"
tar -czf "$ARCHIVE" "$PKG_NAME"

echo "$ARCHIVE"
