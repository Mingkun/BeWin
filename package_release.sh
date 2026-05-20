#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="$BASE_DIR/dist"
LITE_NAME="releaseplan-portable-lite"
FULL_NAME="releaseplan-portable-full"
LITE_DIR="$OUT_DIR/$LITE_NAME"
FULL_DIR="$OUT_DIR/$FULL_NAME"
LITE_ARCHIVE="$OUT_DIR/${LITE_NAME}.tar.gz"
FULL_ARCHIVE="$OUT_DIR/${FULL_NAME}.tar.gz"

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

prepare_package_dir "$LITE_DIR"
prepare_package_dir "$FULL_DIR"

if command -v python3 >/dev/null 2>&1; then
  mkdir -p "$FULL_DIR/vendor"
  python3 -m pip download -r "$BASE_DIR/requirements.txt" -d "$FULL_DIR/vendor"
fi

cd "$OUT_DIR"
tar -czf "$LITE_ARCHIVE" "$LITE_NAME"
tar -czf "$FULL_ARCHIVE" "$FULL_NAME"

echo "$LITE_ARCHIVE"
echo "$FULL_ARCHIVE"
