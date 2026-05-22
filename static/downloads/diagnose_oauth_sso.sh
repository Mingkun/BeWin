#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/work/ReleasePlan}"
CONTAINER_NAME="${2:-releaseplan}"
TMP_OUT="$(mktemp)"
trap 'rm -f "$TMP_OUT"' EXIT

HOST_ENV=""
DOCKER_ENV=""
DOCKER_CMD_LINE=""
CONTAINER_PS=""
NGINX_CFG=""
DEBUG_LOG_INFO=""
DB_INFO=""
ROUTES_INFO=""

print_section() {
  echo
  echo "==================== $1 ====================" | tee -a "$TMP_OUT"
}

capture() {
  local title="$1"
  shift
  print_section "$title"
  ( "$@" 2>&1 || true ) | tee -a "$TMP_OUT"
}

safe_grep_env_file() {
  local file="$1"
  if [ ! -f "$file" ]; then
    echo "[WARN] env file not found: $file"
    return 0
  fi
  grep -E '^(RELEASEPLAN_AUTH_MODE|RELEASEPLAN_OAUTH_AUTHORIZE_URL|RELEASEPLAN_OAUTH_TOKEN_URL|RELEASEPLAN_OAUTH_USERINFO_URL|RELEASEPLAN_OAUTH_REDIRECT_URI|RELEASEPLAN_OAUTH_CLIENT_ID|RELEASEPLAN_OAUTH_SCOPE)=' "$file" || true
}

capture_eval() {
  local title="$1"
  local var_name="$2"
  shift 2
  print_section "$title"
  local output
  output="$("$@" 2>&1 || true)"
  printf '%s\n' "$output" | tee -a "$TMP_OUT"
  printf -v "$var_name" '%s' "$output"
}

capture_shell() {
  local title="$1"
  local var_name="$2"
  shift 2
  print_section "$title"
  local output
  output="$(bash -lc "$*" 2>&1 || true)"
  printf '%s\n' "$output" | tee -a "$TMP_OUT"
  printf -v "$var_name" '%s' "$output"
}

print_section "host basic"
{
  echo "APP_DIR=$APP_DIR"
  echo "CONTAINER_NAME=$CONTAINER_NAME"
  hostname || true
  date || true
} | tee -a "$TMP_OUT"

capture_shell "host gunicorn/docker process" CONTAINER_PS "ps -ef | grep -E '[g]unicorn|[d]ocker.*releaseplan'"
capture_shell "host nginx releaseplan config" NGINX_CFG "grep -RIn 'releaseplan\\|5010\\|auth/callback\\|X-Forwarded-Prefix\\|proxy_pass\\|rewrite\\|return 30[12]' /etc/nginx 2>/dev/null"
capture_shell "host app env (safe subset)" HOST_ENV "if [ -f '$APP_DIR/.env' ]; then grep -E '^(RELEASEPLAN_AUTH_MODE|RELEASEPLAN_OAUTH_AUTHORIZE_URL|RELEASEPLAN_OAUTH_TOKEN_URL|RELEASEPLAN_OAUTH_USERINFO_URL|RELEASEPLAN_OAUTH_REDIRECT_URI|RELEASEPLAN_OAUTH_CLIENT_ID|RELEASEPLAN_OAUTH_SCOPE)=' '$APP_DIR/.env'; else echo '[WARN] env file not found: $APP_DIR/.env'; fi"
capture_shell "docker ps" DOCKER_PS "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'"
capture_shell "docker inspect env (safe subset)" DOCKER_ENV "docker inspect '$CONTAINER_NAME' --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep -E '^(RELEASEPLAN_AUTH_MODE|RELEASEPLAN_OAUTH_AUTHORIZE_URL|RELEASEPLAN_OAUTH_TOKEN_URL|RELEASEPLAN_OAUTH_USERINFO_URL|RELEASEPLAN_OAUTH_REDIRECT_URI|RELEASEPLAN_OAUTH_CLIENT_ID|RELEASEPLAN_OAUTH_SCOPE)='"
capture_shell "docker command / workdir" DOCKER_CMD_LINE "docker inspect '$CONTAINER_NAME' --format 'WorkDir={{.Config.WorkingDir}} Cmd={{json .Config.Cmd}} Entrypoint={{json .Config.Entrypoint}}' 2>/dev/null"
capture_shell "container gunicorn process" CONTAINER_GUNICORN "docker exec '$CONTAINER_NAME' sh -c \"ps -ef | grep '[g]unicorn'\" 2>/dev/null"
capture_shell "container app env file (safe subset)" CONTAINER_ENV_FILE "docker exec '$CONTAINER_NAME' sh -c \"if [ -f /app/.env ]; then grep -E '^(RELEASEPLAN_AUTH_MODE|RELEASEPLAN_OAUTH_AUTHORIZE_URL|RELEASEPLAN_OAUTH_TOKEN_URL|RELEASEPLAN_OAUTH_USERINFO_URL|RELEASEPLAN_OAUTH_REDIRECT_URI|RELEASEPLAN_OAUTH_CLIENT_ID|RELEASEPLAN_OAUTH_SCOPE)=' /app/.env; else echo '[INFO] /app/.env not found'; fi\" 2>/dev/null"
capture_shell "container oauth debug log existence" DEBUG_LOG_INFO "docker exec '$CONTAINER_NAME' sh -c \"ls -l /app/logs 2>/dev/null || true; echo '---'; if [ -f /app/logs/oauth_callback_debug.log ]; then tail -50 /app/logs/oauth_callback_debug.log; else echo '[INFO] /app/logs/oauth_callback_debug.log not found'; fi\" 2>/dev/null"
capture_shell "container oauth code db state" DB_INFO "docker exec '$CONTAINER_NAME' sh -c \"python3 - <<'PY'
import sqlite3
from pathlib import Path
p = Path('/app/data/releaseplan.db')
print('db_exists=', p.exists())
if not p.exists():
    raise SystemExit(0)
conn = sqlite3.connect(p)
try:
    cur = conn.execute(\\\"SELECT name FROM sqlite_master WHERE type='table' AND name='oauth_code_consumption'\\\")
    has_table = cur.fetchone() is not None
    print('has_oauth_code_consumption=', has_table)
    if has_table:
        row = conn.execute(\\\"SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM oauth_code_consumption\\\").fetchone()
        print('oauth_code_consumption_summary=', row)
finally:
    conn.close()
PY\" 2>/dev/null"
capture_shell "container route smoke" ROUTES_INFO "docker exec '$CONTAINER_NAME' sh -c \"python3 - <<'PY'
from src.app import app
for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
    if 'auth' in rule.rule or 'login' in rule.rule or 'logout' in rule.rule:
        print(rule)
PY\" 2>/dev/null"

print_section "auto diagnosis"
ISSUES=()

if ! printf '%s' "$CONTAINER_GUNICORN" | grep -q -- '--workers 1'; then
  ISSUES+=("容器内 gunicorn 不是 workers=1，仍可能有并发重复消费 code")
fi

if ! printf '%s' "$NGINX_CFG" | grep -q '/releaseplan/'; then
  ISSUES+=("nginx 里没看到 /releaseplan/ 反代配置，子路径部署可能不完整")
fi

ALL_ENV="$HOST_ENV
$DOCKER_ENV
$CONTAINER_ENV_FILE"
REDIRECT_URI="$(printf '%s\n' "$ALL_ENV" | grep '^RELEASEPLAN_OAUTH_REDIRECT_URI=' | tail -1 | cut -d= -f2- || true)"
if [ -n "$REDIRECT_URI" ]; then
  if ! printf '%s' "$REDIRECT_URI" | grep -q '/releaseplan/auth/callback'; then
    ISSUES+=("RELEASEPLAN_OAUTH_REDIRECT_URI 不是 /releaseplan/auth/callback，回调地址疑似不匹配")
  fi
else
  ISSUES+=("未发现 RELEASEPLAN_OAUTH_REDIRECT_URI，需确认系统是否自动拼接正确回调地址")
fi

if printf '%s' "$DEBUG_LOG_INFO" | grep -q 'oauth_callback_debug.log not found'; then
  ISSUES+=("容器里不存在 /app/logs/oauth_callback_debug.log，说明当前镜像未包含调试版或 callback 根本没打到应用")
fi

if printf '%s' "$DB_INFO" | grep -q 'has_oauth_code_consumption= False'; then
  ISSUES+=("数据库里没有 oauth_code_consumption 表，说明当前运行代码不是带共享幂等修复的版本")
fi

if printf '%s' "$ROUTES_INFO" | grep -q '/auth/callback'; then
  :
else
  ISSUES+=("应用路由里没看到 /auth/callback，当前容器代码异常或未正确加载")
fi

if [ ${#ISSUES[@]} -eq 0 ]; then
  echo '[DIAGNOSIS] 未发现明显静态配置问题。更像是上游 SSO 或浏览器侧触发了重复 callback，需要结合 oauth_callback_debug.log 的实际内容继续定位。' | tee -a "$TMP_OUT"
else
  echo '[DIAGNOSIS] 最可能问题如下：' | tee -a "$TMP_OUT"
  for item in "${ISSUES[@]}"; do
    echo "- $item" | tee -a "$TMP_OUT"
  done
fi

print_section "done"
echo "诊断完成。优先把 auto diagnosis 段落发回即可。" | tee -a "$TMP_OUT"
