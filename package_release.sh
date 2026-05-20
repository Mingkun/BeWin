#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$BASE_DIR/dist"
ONLINE_NAME="releaseplan-portable-online"
OFFLINE_NAME="releaseplan-portable-offline"
ONLINE_DIR="$OUT_DIR/$ONLINE_NAME"
OFFLINE_DIR="$OUT_DIR/$OFFLINE_NAME"
ONLINE_ARCHIVE="$OUT_DIR/${ONLINE_NAME}.tar.gz"
OFFLINE_ARCHIVE="$OUT_DIR/${OFFLINE_NAME}.tar.gz"

prepare_package_dir() {
  local target_dir="$1"

  rm -rf "$target_dir"
  mkdir -p "$target_dir" "$OUT_DIR"

  rsync -a \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.venv' \
    --exclude 'dist' \
    --exclude 'backups' \
    --exclude 'data' \
    --exclude 'static/downloads' \
    --exclude '.env' \
    "$BASE_DIR/" "$target_dir/"

  chmod +x "$target_dir/install.sh" "$target_dir/package_release.sh" "$target_dir/uninstall.sh" "$target_dir/run-docker.sh"
}

prepare_package_dir "$ONLINE_DIR"
prepare_package_dir "$OFFLINE_DIR"

if command -v python3 >/dev/null 2>&1; then
  mkdir -p "$OFFLINE_DIR/vendor"
  python3 -m pip download -r "$BASE_DIR/requirements.txt" -d "$OFFLINE_DIR/vendor"
fi

cd "$OUT_DIR"
tar -czf "$ONLINE_ARCHIVE" "$ONLINE_NAME"
tar -czf "$OFFLINE_ARCHIVE" "$OFFLINE_NAME"

echo "$ONLINE_ARCHIVE"
echo "$OFFLINE_ARCHIVE"
