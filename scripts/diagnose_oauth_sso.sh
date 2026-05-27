#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/work/ReleasePlan}"
CONTAINER_NAME="${2:-releaseplan}"

print_section() {
  echo
  echo "==================== $1 ===================="
}

safe_grep_env() {
  local file="$1"
  if [ ! -f "$file" ]; then
    echo "[WARN] env file not found: $file"
    return 0
  fi
  grep -E '^(RELEASEPLAN_AUTH_MODE|RELEASEPLAN_OAUTH_AUTHORIZE_URL|RELEASEPLAN_OAUTH_TOKEN_URL|RELEASEPLAN_OAUTH_USERINFO_URL|RELEASEPLAN_OAUTH_REDIRECT_URI|RELEASEPLAN_OAUTH_CLIENT_ID|RELEASEPLAN_OAUTH_SCOPE)=' "$file" || true
}

print_section "host basic"
echo "APP_DIR=$APP_DIR"
echo "CONTAINER_NAME=$CONTAINER_NAME"
hostname || true
date || true

print_section "host gunicorn/docker process"
ps -ef | grep -E '[g]unicorn|[d]ocker.*releaseplan' || true

print_section "host nginx releaseplan config"
grep -RIn 'releaseplan\|5010\|auth/callback\|X-Forwarded-Prefix\|proxy_pass\|rewrite\|return 30[12]' /etc/nginx 2>/dev/null || true

print_section "host app env (safe subset)"
safe_grep_env "$APP_DIR/.env"

print_section "docker ps"
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' || true

print_section "docker inspect env (safe subset)"
docker inspect "$CONTAINER_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep -E '^(RELEASEPLAN_AUTH_MODE|RELEASEPLAN_OAUTH_AUTHORIZE_URL|RELEASEPLAN_OAUTH_TOKEN_URL|RELEASEPLAN_OAUTH_USERINFO_URL|RELEASEPLAN_OAUTH_REDIRECT_URI|RELEASEPLAN_OAUTH_CLIENT_ID|RELEASEPLAN_OAUTH_SCOPE)=' || true

print_section "docker command / workdir"
docker inspect "$CONTAINER_NAME" --format 'WorkDir={{.Config.WorkingDir}} Cmd={{json .Config.Cmd}} Entrypoint={{json .Config.Entrypoint}}' 2>/dev/null || true

print_section "container gunicorn process"
docker exec "$CONTAINER_NAME" sh -c "ps -ef | grep '[g]unicorn'" 2>/dev/null || true

print_section "container app env file (safe subset)"
docker exec "$CONTAINER_NAME" sh -c "if [ -f /app/.env ]; then grep -E '^(RELEASEPLAN_AUTH_MODE|RELEASEPLAN_OAUTH_AUTHORIZE_URL|RELEASEPLAN_OAUTH_TOKEN_URL|RELEASEPLAN_OAUTH_USERINFO_URL|RELEASEPLAN_OAUTH_REDIRECT_URI|RELEASEPLAN_OAUTH_CLIENT_ID|RELEASEPLAN_OAUTH_SCOPE)=' /app/.env; else echo '[INFO] /app/.env not found'; fi" 2>/dev/null || true

print_section "container oauth debug log existence"
docker exec "$CONTAINER_NAME" sh -c "ls -l /app/logs 2>/dev/null || true; echo '---'; if [ -f /app/logs/oauth_callback_debug.log ]; then tail -50 /app/logs/oauth_callback_debug.log; else echo '[INFO] /app/logs/oauth_callback_debug.log not found'; fi" 2>/dev/null || true

print_section "container oauth code db state"
docker exec "$CONTAINER_NAME" sh -c "python3 - <<'PY'
import sqlite3
from pathlib import Path
p = Path('/app/data/releaseplan.db')
print('db_exists=', p.exists())
if not p.exists():
    raise SystemExit(0)
conn = sqlite3.connect(p)
try:
    cur = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='oauth_code_consumption'\")
    has_table = cur.fetchone() is not None
    print('has_oauth_code_consumption=', has_table)
    if has_table:
        row = conn.execute(\"SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM oauth_code_consumption\").fetchone()
        print('oauth_code_consumption_summary=', row)
        rows = conn.execute(\"SELECT code, created_at FROM oauth_code_consumption ORDER BY created_at DESC LIMIT 20\").fetchall()
        print('oauth_code_recent=')
        for r in rows:
            print(r)
finally:
    conn.close()
PY" 2>/dev/null || true

print_section "container route smoke"
docker exec "$CONTAINER_NAME" sh -c "python3 - <<'PY'
from src.app import app
for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
    if 'auth' in rule.rule or 'login' in rule.rule or 'logout' in rule.rule:
        print(rule)
PY" 2>/dev/null || true

print_section "done"
echo "诊断完成。把完整输出发回即可。"
