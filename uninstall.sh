#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="releaseplan.service"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"

if command -v systemctl >/dev/null 2>&1; then
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  systemctl disable "$SERVICE_NAME" 2>/dev/null || true
fi

if [ -f "$SERVICE_FILE" ]; then
  rm -f "$SERVICE_FILE"
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload
fi

echo "[OK] 已卸载 systemd 服务: $SERVICE_NAME"
