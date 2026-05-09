#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$BASE_DIR/.venv"
ENV_FILE="$BASE_DIR/.env"

cd "$BASE_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 未安装"
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  cp .env.example "$ENV_FILE"
  echo "[INFO] 已生成 .env，请按需修改后再启动"
fi

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
exec "$BASE_DIR/.venv/bin/gunicorn" --workers 2 --bind "${HOST:-0.0.0.0}:${PORT:-5010}" wsgi:app
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

echo "[OK] 安装完成"
echo "1) 如需配置，编辑: $ENV_FILE"
echo "2) 启动命令: $BASE_DIR/start.sh"
