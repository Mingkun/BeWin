#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"

IMAGE_NAME="releaseplan:latest"
CONTAINER_NAME="releaseplan"

mkdir -p data

docker build -t "$IMAGE_NAME" .

docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

docker run -d \
  --name "$CONTAINER_NAME" \
  -p 5010:5010 \
  -e RELEASEPLAN_SECRET_KEY="${RELEASEPLAN_SECRET_KEY:-change-me-to-a-random-long-string}" \
  -e RELEASEPLAN_SAML_ENABLED="${RELEASEPLAN_SAML_ENABLED:-false}" \
  -e RELEASEPLAN_SAML_SETTINGS="/app/saml_settings.json" \
  -v "$BASE_DIR/data:/app/data" \
  -v "$BASE_DIR/docs:/app/docs" \
  --restart unless-stopped \
  "$IMAGE_NAME"

echo "[OK] ReleasePlan Docker 已启动"
echo "[INFO] 访问地址: http://<server-ip>:5010/"
