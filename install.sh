#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$BASE_DIR/.venv"
ENV_FILE="$BASE_DIR/.env"
SERVICE_NAME="releaseplan.service"
SERVICE_TEMPLATE="$BASE_DIR/releaseplan.service.template"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"
RUN_USER="${RUN_USER:-root}"
HOST_VALUE="${HOST:-0.0.0.0}"
PORT_VALUE="${PORT:-5010}"
ENABLE_SERVICE="${ENABLE_SERVICE:-true}"
START_SERVICE="${START_SERVICE:-true}"

cd "$BASE_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 未安装"
  exit 1
fi

if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "[ERROR] 当前 python3 不支持 venv"
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  cp .env.example "$ENV_FILE"
  echo "[INFO] 已生成 .env"
fi

set -a
. "$ENV_FILE"
set +a

HOST_VALUE="${HOST:-$HOST_VALUE}"
PORT_VALUE="${PORT:-$PORT_VALUE}"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip

if [ -d "$BASE_DIR/vendor" ] && ls "$BASE_DIR/vendor"/*.whl >/dev/null 2>&1; then
  "$VENV_DIR/bin/pip" install --no-index --find-links "$BASE_DIR/vendor" -r requirements.txt
else
  "$VENV_DIR/bin/pip" install -r requirements.txt
fi

mkdir -p "$BASE_DIR/data"

cat > "$BASE_DIR/start.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"
set -a
[ -f "$BASE_DIR/.env" ] && . "$BASE_DIR/.env"
set +a
exec "$BASE_DIR/.venv/bin/gunicorn" --workers 1 --bind "${HOST:-0.0.0.0}:${PORT:-5010}" wsgi:app
EOF
chmod +x "$BASE_DIR/start.sh"

cat > "$BASE_DIR/start-dev.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"
set -a
[ -f "$BASE_DIR/.env" ] && . "$BASE_DIR/.env"
set +a
exec "$BASE_DIR/.venv/bin/python" src/app.py
EOF
chmod +x "$BASE_DIR/start-dev.sh"
chmod +x "$BASE_DIR/uninstall.sh"

if command -v systemctl >/dev/null 2>&1; then
  if [ "$(id -u)" -ne 0 ]; then
    echo "[ERROR] 安装 systemd 服务需要 root 权限"
    echo "[INFO] 你也可以先手动运行: $BASE_DIR/start.sh"
    exit 1
  fi

  sed \
    -e "s#{{BASE_DIR}}#$BASE_DIR#g" \
    -e "s#{{RUN_USER}}#$RUN_USER#g" \
    -e "s#{{HOST}}#$HOST_VALUE#g" \
    -e "s#{{PORT}}#$PORT_VALUE#g" \
    "$SERVICE_TEMPLATE" > "$SERVICE_FILE"

  systemctl daemon-reload

  if [ "$ENABLE_SERVICE" = "true" ]; then
    systemctl enable "$SERVICE_NAME"
  fi

  if [ "$START_SERVICE" = "true" ]; then
    systemctl restart "$SERVICE_NAME" || systemctl start "$SERVICE_NAME"
  fi

  echo "[OK] systemd 服务安装完成: $SERVICE_NAME"
  echo "[INFO] 查看状态: systemctl status $SERVICE_NAME"
  echo "[INFO] 重启服务: systemctl restart $SERVICE_NAME"
else
  echo "[WARN] 当前系统没有 systemctl，已跳过 systemd 安装"
  echo "[INFO] 请手动启动: $BASE_DIR/start.sh"
fi

echo "[OK] 安装完成"
