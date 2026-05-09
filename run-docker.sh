#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"

IMAGE_NAME="releaseplan:latest"
CONTAINER_NAME="releaseplan"
PROXY_URL="${PROXY_URL:-}"

mkdir -p data

BUILD_ARGS=()
RUN_PROXY_ARGS=()

if [ -n "$PROXY_URL" ]; then
  BUILD_ARGS+=(--build-arg "http_proxy=$PROXY_URL")
  BUILD_ARGS+=(--build-arg "https_proxy=$PROXY_URL")
  RUN_PROXY_ARGS+=(-e "http_proxy=$PROXY_URL")
  RUN_PROXY_ARGS+=(-e "https_proxy=$PROXY_URL")
  echo "[INFO] 已启用代理 PROXY_URL"
fi

docker build "${BUILD_ARGS[@]}" -t "$IMAGE_NAME" .

docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

docker run -d \
  --name "$CONTAINER_NAME" \
  -p 5010:5010 \
  "${RUN_PROXY_ARGS[@]}" \
  -e RELEASEPLAN_SECRET_KEY="${RELEASEPLAN_SECRET_KEY:-change-me-to-a-random-long-string}" \
  -e RELEASEPLAN_SAML_ENABLED="${RELEASEPLAN_SAML_ENABLED:-false}" \
  -e RELEASEPLAN_SAML_SETTINGS="/app/saml_settings.json" \
  -v "$BASE_DIR/data:/app/data" \
  -v "$BASE_DIR/docs:/app/docs" \
  --restart unless-stopped \
  "$IMAGE_NAME"

echo "[OK] ReleasePlan Docker 已启动"
echo "[INFO] 访问地址: http://<server-ip>:5010/"
