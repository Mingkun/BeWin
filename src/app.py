from flask import Flask, redirect, render_template, request, session, url_for, Response, flash, send_from_directory
import secrets
from io import StringIO
from urllib.parse import quote
from werkzeug.middleware.proxy_fix import ProxyFix
import csv
import json
import os
import sqlite3
from functools import wraps
from pathlib import Path
from werkzeug.utils import secure_filename
from datetime import datetime
import hashlib
import shutil
import zipfile
import uuid

from src.oauth_auth import DEFAULT_OAUTH_DEBUG_LOG_PATH, get_oauth_debug_log_path, register_oauth_routes
from src import permission_config as permission_config_service

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / '.env'
if ENV_PATH.exists():
    for raw_line in ENV_PATH.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())


PROJECT_CSV_PATH = BASE_DIR / "docs" / "project_table.csv"
FEATURE_CSV_PATH = BASE_DIR / "docs" / "feature_table.csv"
DB_PATH = BASE_DIR / "data" / "releaseplan.db"
SERVICE_RESOURCE_CSV_PATH = BASE_DIR / "docs" / "service_resource_investment.csv"
REQUIREMENTS_LOG_PATH = BASE_DIR / "data" / "requirements_requests.md"
MILESTONE_MEDIA_DIR = BASE_DIR / "data" / "milestone_condolence"
MILESTONE_COLUMNS = [
    "1/31", "2/28", "3/31", "4/30", "5/31", "6/30",
    "7/31", "8/31", "9/30", "10/31", "11/30", "12/31"
]
MONTH_LABELS = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]
QUARTERS = [
    {"name": "Q1", "start": 0, "span": 3},
    {"name": "Q2", "start": 3, "span": 3},
    {"name": "Q3", "start": 6, "span": 3},
    {"name": "Q4", "start": 9, "span": 3},
]
PROJECT_COLUMNS = [
    "立项状态", "管控灶", "投资主体", "项目编码", "项目名称", "项目描述", "项目大类", "项目子类",
    "项目复杂度", "项目角色", "项目经理", "计划启动日期", "计划结束日期", "工作量（人月）",
    "研发费用预算（w）", "人力预算（自有）", "人力预算（OD）", "人力预算（TM）"
]
FEATURE_COLUMNS = [
    "项目名称", "五层部门", "重点工作", "关键特性", "L4服务或服务组", "服务交付PM"
]
PROJECT_ALL_COLUMNS = PROJECT_COLUMNS
FEATURE_ALL_COLUMNS = FEATURE_COLUMNS + MILESTONE_COLUMNS

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"), static_url_path="/static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
app.secret_key = os.getenv("RELEASEPLAN_SECRET_KEY", "releaseplan-dev-secret-change-me")


HOME_CARD_SPECS = [
    {
        "key": "milestone-condolence",
        "default_title": "关键突破&战地激励",
        "desc": "查看关键突破与战地激励相关内容。",
        "href_builder": lambda: url_for('milestone_condolence_page'),
    },
    {
        "key": "department-pipeline-load",
        "default_title": "项目视图",
        "desc": "查看项目视图页面的内容，项目甘特图、项目主要信息。",
        "href_builder": lambda: url_for('view_placeholder', view_key='department-pipeline-load'),
    },
    {
        "key": "roadmap",
        "default_title": "关键特性视图",
        "desc": "查看所规划关键特性的路标信息。",
        "href_builder": lambda: url_for('roadmap'),
    },
    {
        "key": "cloud-service-view",
        "default_title": "云服务视图",
        "desc": "按云服务粒度查看资源投入情况。",
        "href_builder": lambda: url_for('view_placeholder', view_key='cloud-service-view'),
    },
    {
        "key": "department-budget-resource",
        "default_title": "投资视图",
        "desc": "从投资维度看管道。",
        "href_builder": lambda: url_for('view_placeholder', view_key='department-budget-resource'),
    },
    {
        "key": "project-budget-resource",
        "default_title": "资源视图",
        "desc": "了解部门人力资源情况。",
        "href_builder": lambda: url_for('view_placeholder', view_key='project-budget-resource'),
    },
]

HOME_CARD_VIEW_FEATURES = {
    "milestone-condolence": "view_milestone",
    "department-pipeline-load": "view_projects",
    "roadmap": "view_features",
    "cloud-service-view": "view_service_resources",
    "department-budget-resource": "view_investment",
    "project-budget-resource": "view_resource_people",
}


def _build_default_home_cards():
    cards = []
    for index, spec in enumerate(HOME_CARD_SPECS, start=1):
        title = os.getenv(f"RELEASEPLAN_CARD_{index}_TITLE", spec["default_title"])
        cards.append({
            "key": spec["key"],
            "title": title,
            "desc": spec["desc"],
            "href": spec["href_builder"](),
            "default_index": index,
            "position": index,
        })
    return cards


def normalize_home_cards(cards):
    total = len(cards)
    order_items = []
    notices = []
    for index, card in enumerate(cards, start=1):
        raw_order = str(card.get('position', index)).strip()
        try:
            order_value = int(raw_order)
        except (TypeError, ValueError):
            order_value = index
            notices.append(f"{card['title']} 的排序序号无效，已自动改为 {order_value}")
        if order_value < 1:
            notices.append(f"{card['title']} 的排序序号过小，已自动改为 1")
            order_value = 1
        elif order_value > total:
            notices.append(f"{card['title']} 的排序序号过大，已自动改为 {total}")
            order_value = total
        order_items.append((order_value, index, card))

    ordered = []
    used_positions = set()
    for requested_position, _, card in sorted(order_items, key=lambda item: (item[0], item[1])):
        position = requested_position
        while position in used_positions:
            position += 1
        if position > total:
            position = 1
            while position in used_positions and position <= total:
                position += 1
        if position != requested_position:
            notices.append(f"{card['title']} 的排序序号 {requested_position} 与其他卡片重复，已自动顺延到 {position}")
        used_positions.add(position)
        card['position'] = position
        ordered.append(card)

    ordered.sort(key=lambda card: (card['position'], card['default_index']))
    return ordered, notices


def get_home_cards():
    default_cards = _build_default_home_cards()
    for index, card in enumerate(default_cards, start=1):
        card['position'] = os.getenv(f"RELEASEPLAN_CARD_{index}_ORDER", str(index)) or str(index)
    ordered, _ = normalize_home_cards(default_cards)
    return ordered


def get_visible_home_cards(user=None):
    cards = get_home_cards()
    return [
        card for card in cards
        if can_access(HOME_CARD_VIEW_FEATURES.get(card.get('key'), ''), user)
    ]


def milestone_month_options():
    return list(enumerate(MONTH_LABELS, start=1))


def load_milestone_condolence_items():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS milestone_condolence_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                five_level_department TEXT NOT NULL,
                month_index INTEGER NOT NULL,
                activity_date TEXT,
                participant_names TEXT,
                breakthrough_text TEXT,
                condolence_region TEXT,
                image_path TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(milestone_condolence_items)").fetchall()}
        if 'activity_date' not in existing_columns:
            conn.execute("ALTER TABLE milestone_condolence_items ADD COLUMN activity_date TEXT")
        if 'participant_names' not in existing_columns:
            conn.execute("ALTER TABLE milestone_condolence_items ADD COLUMN participant_names TEXT")
        conn.commit()
        rows = conn.execute(
            """
            SELECT id, five_level_department, month_index, activity_date, participant_names, breakthrough_text, condolence_region, image_path, created_at, updated_at
            FROM milestone_condolence_items
            ORDER BY month_index ASC, five_level_department ASC, id ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_milestone_departments(items):
    return sorted({(item.get('five_level_department') or '').strip() for item in items if (item.get('five_level_department') or '').strip()})


def build_milestone_board(items):
    departments = get_milestone_departments(items)
    month_cells = {department: {index: [] for index in range(1, 13)} for department in departments}
    for item in items:
        department = (item.get('five_level_department') or '').strip()
        month_index = int(item.get('month_index') or 0)
        activity_date = (item.get('activity_date') or '').strip()
        if activity_date:
            try:
                month_index = datetime.strptime(activity_date, '%Y-%m-%d').month
            except Exception:
                pass
        if not department or month_index not in range(1, 13):
            continue
        month_cells.setdefault(department, {index: [] for index in range(1, 13)})
        month_cells[department][month_index].append(item)
    return {
        'departments': departments,
        'months': milestone_month_options(),
        'cells': month_cells,
    }


def save_milestone_condolence_image(file_storage):
    if not file_storage or not getattr(file_storage, 'filename', ''):
        return ''
    filename = secure_filename(file_storage.filename or '')
    if not filename:
        return ''
    ext = Path(filename).suffix.lower()
    if ext not in {'.png', '.jpg', '.jpeg', '.gif', '.webp'}:
        return ''
    MILESTONE_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    target_name = f"{uuid.uuid4().hex}{ext}"
    target_path = MILESTONE_MEDIA_DIR / target_name
    file_storage.save(target_path)
    return f"data/milestone_condolence/{target_name}"


def milestone_image_url(image_path):
    path = (image_path or '').strip()
    if not path:
        return ''
    if path.startswith('data/milestone_condolence/'):
        filename = path.split('/', 2)[-1]
        return url_for('milestone_condolence_image_route', filename=filename)
    if path.startswith('picture/milestone_condolence/'):
        filename = path.split('/', 2)[-1]
        return url_for('milestone_condolence_image_route', filename=filename)
    return url_for('static', filename=path)


@app.context_processor
def inject_template_helpers():
    return {
        'milestone_image_url': milestone_image_url,
    }


def get_branding():
    home_title = os.getenv("RELEASEPLAN_HOME_TITLE", "作战平台")
    browser_title = os.getenv("RELEASEPLAN_BROWSER_TITLE", "作战平台")
    roadmap_browser_title = os.getenv("RELEASEPLAN_ROADMAP_BROWSER_TITLE", "关键特性视图")
    theme = os.getenv("RELEASEPLAN_THEME", "ios-light")
    return {
        "home_title": home_title,
        "browser_title": browser_title,
        "roadmap_browser_title": roadmap_browser_title,
        "theme": theme,
    }


def save_env_settings(updates):
    env_path = BASE_DIR / ".env"
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    kv = {}
    for line in lines:
        if not line or line.lstrip().startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        kv[key] = value
    kv.update(updates)
    ordered_keys = [
        "RELEASEPLAN_SECRET_KEY",
        "RELEASEPLAN_HOME_TITLE",
        "RELEASEPLAN_BROWSER_TITLE",
        "RELEASEPLAN_ROADMAP_BROWSER_TITLE",
        "RELEASEPLAN_THEME",
        "RELEASEPLAN_BACKUP_DIR",
        "RELEASEPLAN_AUTO_BACKUP_ENABLED",
        "RELEASEPLAN_AUTO_BACKUP_TIME",
        "RELEASEPLAN_AUTO_BACKUP_SCHEDULE",
        "RELEASEPLAN_LOCAL_ADMIN_USERNAME",
        "RELEASEPLAN_LOCAL_ADMIN_PASSWORD",
        "RELEASEPLAN_LOCAL_USER_USERNAME",
        "RELEASEPLAN_LOCAL_USER_PASSWORD",
        "RELEASEPLAN_LOCAL_GUEST_USERNAME",
        "RELEASEPLAN_LOCAL_GUEST_PASSWORD",
        "HOST",
        "PORT",
    ]
    merged_lines = []
    used = set()
    for key in ordered_keys:
        if key in kv:
            merged_lines.append(f"{key}={kv[key]}")
            used.add(key)
    for key, value in kv.items():
        if key not in used:
            merged_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(merged_lines) + "\n", encoding="utf-8")


def get_backup_dir():
    configured = (os.getenv('RELEASEPLAN_BACKUP_DIR') or '').strip()
    return Path(configured) if configured else BASE_DIR / 'backups'


FEATURE_KEYS = permission_config_service.FEATURE_KEYS


def load_permission_rules():
    return permission_config_service.load_permission_rules(BASE_DIR)


def save_permission_rules(items):
    return permission_config_service.save_permission_rules(BASE_DIR, items)


def default_feature_flags(role):
    return permission_config_service.default_feature_flags(role)


def normalize_permission_role(role_text):
    return permission_config_service.normalize_permission_role(role_text)


def normalize_feature_flags(raw, role):
    return permission_config_service.normalize_feature_flags(raw, role)


def get_permission_presets():
    return permission_config_service.get_permission_presets()


def match_permission_rule(source='sso', username='', email='', employee_number=''):
    return permission_config_service.match_permission_rule(
        BASE_DIR,
        source=source,
        username=username,
        email=email,
        employee_number=employee_number,
    )


def ensure_backup_dir():
    backup_dir = get_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def get_backup_manifest_path():
    return ensure_backup_dir() / 'backup_manifest.json'


def get_backup_include_paths():
    return [
        BASE_DIR / 'data',
        BASE_DIR / 'docs',
        BASE_DIR / '.env',
    ]


def get_backup_config():
    daily_time = (os.getenv('RELEASEPLAN_AUTO_BACKUP_TIME') or '03:00').strip() or '03:00'
    return {
        'backup_dir': str(get_backup_dir()),
        'auto_backup_enabled': (os.getenv('RELEASEPLAN_AUTO_BACKUP_ENABLED', 'false').lower() == 'true'),
        'auto_backup_time': daily_time,
        'auto_backup_schedule': f"{daily_time.split(':')[1]} {daily_time.split(':')[0]} * * *",
    }


def load_backup_manifest():
    manifest_path = get_backup_manifest_path()
    if not manifest_path.exists():
        return []
    try:
        return json.loads(manifest_path.read_text(encoding='utf-8'))
    except Exception:
        return []


def save_backup_manifest(items):
    manifest_path = get_backup_manifest_path()
    manifest_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')


def list_backup_history():
    ensure_backup_dir()
    manifest = load_backup_manifest()
    merged = []
    seen = set()
    for item in manifest:
        filename = item.get('filename')
        if not filename:
            continue
        archive_path = get_backup_dir() / filename
        if archive_path.exists():
            stat = archive_path.stat()
            item['size_bytes'] = stat.st_size
            item['exists'] = True
            merged.append(item)
            seen.add(filename)
    for archive_path in sorted(get_backup_dir().glob('releaseplan-backup-*.zip'), reverse=True):
        if archive_path.name in seen:
            continue
        stat = archive_path.stat()
        merged.append({
            'filename': archive_path.name,
            'created_at': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            'backup_type': 'unknown',
            'contents': ['data', 'docs', '.env'],
            'size_bytes': stat.st_size,
            'exists': True,
        })
    merged.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return merged


def record_backup_history(archive_path, backup_type='manual'):
    history = load_backup_manifest()
    stat = archive_path.stat()
    history = [item for item in history if item.get('filename') != archive_path.name]
    history.insert(0, {
        'filename': archive_path.name,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'backup_type': backup_type,
        'contents': ['data', 'docs', '.env'],
        'size_bytes': stat.st_size,
        'exists': True,
    })
    save_backup_manifest(history[:200])


def build_backup_archive(backup_type='manual'):
    backup_dir = ensure_backup_dir()
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    archive_path = backup_dir / f'releaseplan-backup-{timestamp}.zip'
    include_paths = get_backup_include_paths()

    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for path in include_paths:
            if not path.exists():
                continue
            if path.is_dir():
                for child in path.rglob('*'):
                    if child.is_file():
                        zf.write(child, child.relative_to(BASE_DIR))
            elif path.is_file():
                zf.write(path, path.relative_to(BASE_DIR))
    record_backup_history(archive_path, backup_type=backup_type)
    return archive_path


def restore_backup_archive(filename):
    archive_path = ensure_backup_dir() / filename
    if not archive_path.exists() or archive_path.suffix.lower() != '.zip' or '/' in filename or '..' in filename:
        raise FileNotFoundError(filename)

    restore_tmp_dir = ensure_backup_dir() / '_restore_tmp'
    if restore_tmp_dir.exists():
        shutil.rmtree(restore_tmp_dir)
    restore_tmp_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path, 'r') as zf:
        zf.extractall(restore_tmp_dir)

    for relative in ['data', 'docs', '.env']:
        src = restore_tmp_dir / relative
        dst = BASE_DIR / relative
        if not src.exists():
            continue
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    shutil.rmtree(restore_tmp_dir, ignore_errors=True)
    return archive_path


def delete_backup_archive(filename):
    archive_path = ensure_backup_dir() / filename
    if not archive_path.exists() or archive_path.suffix.lower() != '.zip' or '/' in filename or '..' in filename:
        raise FileNotFoundError(filename)

    archive_path.unlink()
    history = [item for item in load_backup_manifest() if item.get('filename') != filename]
    save_backup_manifest(history)
    return filename


def write_auto_backup_crontab(enabled, daily_time):
    cron_file = Path('/etc/cron.d/releaseplan-backup')
    if not enabled:
        if cron_file.exists():
            cron_file.unlink()
        return

    try:
        hour_text, minute_text = daily_time.split(':', 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        raise ValueError('invalid daily time')

    schedule = f'{minute} {hour} * * *'
    cmd = f'cd {BASE_DIR} && /usr/bin/python3 {BASE_DIR / "src/app.py"} --backup-now --backup-type auto >> /var/log/releaseplan-backup.log 2>&1'
    content = f'{schedule} root {cmd}\n'
    cron_file.write_text(content, encoding='utf-8')


def oauth_enabled():
    return os.getenv("RELEASEPLAN_OAUTH_ENABLED", "false").lower() == "true"


def local_admin_enabled():
    admin_username = (os.getenv('RELEASEPLAN_LOCAL_ADMIN_USERNAME') or '').strip()
    admin_password = (os.getenv('RELEASEPLAN_LOCAL_ADMIN_PASSWORD') or '').strip()
    user_username = (os.getenv('RELEASEPLAN_LOCAL_USER_USERNAME') or os.getenv('RELEASEPLAN_LOCAL_GUEST_USERNAME') or '').strip()
    user_password = (os.getenv('RELEASEPLAN_LOCAL_USER_PASSWORD') or os.getenv('RELEASEPLAN_LOCAL_GUEST_PASSWORD') or '').strip()
    return bool((admin_username and admin_password) or (user_username and user_password))


def auth_mode():
    if oauth_enabled() and local_admin_enabled():
        return 'hybrid'
    if oauth_enabled():
        return 'oauth2'
    if local_admin_enabled():
        return 'local'
    return 'none'


def get_current_user():
    return session.get('oauth_user') or session.get('local_user')


def get_current_user_roles():
    user = get_current_user() or {}
    roles = user.get('roles') or []
    if isinstance(roles, str):
        roles = [roles]
    return [str(role).strip().lower() for role in roles if str(role).strip()]


def get_current_user_features(user=None):
    user = user if user is not None else get_current_user()
    if not isinstance(user, dict):
        return default_feature_flags('user')
    features = user.get('features') or {}
    roles = user.get('roles') or []
    if isinstance(roles, str):
        roles = [roles]
    normalized_roles = [str(role).strip().lower() for role in roles]
    role = 'admin' if 'admin' in normalized_roles else 'guest' if 'guest' in normalized_roles else 'user'
    return normalize_feature_flags(features, role)


def is_admin_user(user=None):
    user = user if user is not None else get_current_user()
    if not isinstance(user, dict):
        return False
    roles = user.get('roles') or []
    if isinstance(roles, str):
        roles = [roles]
    normalized = {str(role).strip().lower() for role in roles if str(role).strip()}
    return 'admin' in normalized


def is_guest_user(user=None):
    user = user if user is not None else get_current_user()
    if not isinstance(user, dict):
        return False
    roles = user.get('roles') or []
    if isinstance(roles, str):
        roles = [roles]
    normalized = {str(role).strip().lower() for role in roles if str(role).strip()}
    return 'guest' in normalized and 'admin' not in normalized and 'user' not in normalized


def can_access(feature_key, user=None):
    mode = auth_mode()
    if mode == 'none':
        return True
    features = get_current_user_features(user)
    return bool(features.get(feature_key))


def can_edit(user=None):
    return can_access('manage_projects', user) or can_access('manage_features', user) or can_access('manage_service_resources', user) or can_access('manage_backup', user) or can_access('manage_permissions', user)


def build_auth_context():
    user = get_current_user()
    auth_type = (user or {}).get('auth_type') if isinstance(user, dict) else None
    role_labels = get_current_user_roles()
    return {
        'auth_mode': auth_mode(),
        'current_user': user,
        'can_edit': can_edit(user),
        'user_roles': role_labels,
        'user_features': get_current_user_features(user),
        'login_source_label': 'SSO' if auth_type == 'oauth2' else '本地' if auth_type == 'local' else '',
        'role_label': '管理员' if 'admin' in role_labels else 'Guest' if 'guest' in role_labels else '用户' if 'user' in role_labels else '',
    }


def verify_local_admin(username, password):
    expected_username = (os.getenv('RELEASEPLAN_LOCAL_ADMIN_USERNAME') or '').strip()
    expected_password = (os.getenv('RELEASEPLAN_LOCAL_ADMIN_PASSWORD') or '').strip()
    return username == expected_username and password == expected_password


def verify_local_user(username, password):
    expected_username = (os.getenv('RELEASEPLAN_LOCAL_USER_USERNAME') or '').strip()
    expected_password = (os.getenv('RELEASEPLAN_LOCAL_USER_PASSWORD') or '').strip()
    return username == expected_username and password == expected_password


def verify_local_guest(username, password):
    expected_username = (os.getenv('RELEASEPLAN_LOCAL_GUEST_USERNAME') or '').strip()
    expected_password = (os.getenv('RELEASEPLAN_LOCAL_GUEST_PASSWORD') or '').strip()
    return username == expected_username and password == expected_password


def get_request_client_ip():
    forwarded_for = (request.headers.get('X-Forwarded-For') or '').strip()
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    real_ip = (request.headers.get('X-Real-IP') or '').strip()
    if real_ip:
        return real_ip
    return (request.remote_addr or '').strip()


def record_login_audit(user):
    if not isinstance(user, dict):
        return
    init_db()
    session_token = secrets.token_urlsafe(24)
    session['login_audit_token'] = session_token
    roles = user.get('roles') or []
    if isinstance(roles, str):
        roles = [roles]
    role_text = ','.join([str(role).strip() for role in roles if str(role).strip()])
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO login_audit (user_id, user_name, email, auth_type, role_text, login_ip, user_agent, session_token, login_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                (user.get('user_id') or '').strip(),
                (user.get('name') or '').strip(),
                (user.get('email') or '').strip(),
                (user.get('auth_type') or '').strip(),
                role_text,
                get_request_client_ip(),
                (request.headers.get('User-Agent') or '').strip()[:500],
                session_token,
            ),
        )
        conn.commit()


def list_recent_active_logins(hours=24):
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT user_id, user_name, email, auth_type, role_text, login_ip, login_at, last_seen_at
            FROM login_audit
            WHERE datetime(last_seen_at) >= datetime('now', ?)
            ORDER BY datetime(last_seen_at) DESC, id DESC
            LIMIT 100
            """,
            (f'-{int(hours)} hours',),
        ).fetchall()
        return [dict(row) for row in rows]


def get_releaseplan_root_path():
    prefix = (request.headers.get('X-Forwarded-Prefix') or '').strip()
    if prefix:
        return prefix.rstrip('/') or '/'
    script_name = (request.environ.get('SCRIPT_NAME') or '').strip()
    if script_name:
        return script_name.rstrip('/') or '/'
    return '/'


def normalize_next_url(next_url):
    default_path = get_releaseplan_root_path()
    value = (next_url or '').strip()
    if not value or value == '/':
        return default_path
    if value.startswith('http://') or value.startswith('https://') or value.startswith('//'):
        return default_path
    if not value.startswith('/'):
        return default_path
    return value


def require_feature(feature_key, message='当前账号没有该操作权限'):
    if can_access(feature_key):
        return None
    flash(message)
    return redirect(url_for('index'))


def require_admin():
    if is_admin_user():
        return None
    flash('当前账号没有管理员权限')
    return redirect(url_for('index'))


GUEST_ALLOWED_ENDPOINTS = {
    'index',
    'milestone_condolence_page',
    'milestone_condolence_image_route',
    'requirements_page',
    'settings_auth_debug_page',
    'logout',
    'static',
}


@app.before_request
def restrict_guest_access():
    if not is_guest_user():
        return None
    endpoint = request.endpoint or ''
    if endpoint in GUEST_ALLOWED_ENDPOINTS or endpoint.startswith('login') or endpoint.startswith('oauth_'):
        return None
    flash('Guest 角色只能访问关键突破信息卡片、需求和当前登录用户信息')
    return redirect(url_for('index'))


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        mode = auth_mode()
        if mode == 'none':
            return view_func(*args, **kwargs)
        if get_current_user():
            return view_func(*args, **kwargs)
        if mode == 'hybrid':
            return redirect(url_for('login_entry', next=request.full_path if request.query_string else request.path))
        if mode == 'local':
            return redirect(url_for('local_login_form', next=request.full_path if request.query_string else request.path))
        return redirect(url_for('oauth_login', next=request.full_path if request.query_string else request.path))
    return wrapped


def get_latest_download_package_info():
    downloads_dir = BASE_DIR / 'static' / 'downloads'
    package_types = {
        'portable_lite': ('releaseplan-portable-lite-v', '轻量安装包'),
        'portable_full': ('releaseplan-portable-full-v', '完整安装包'),
        'portable_online': ('releaseplan-portable-online-v', '轻量安装包'),
        'portable_offline': ('releaseplan-portable-offline-v', '完整安装包'),
        'portable_legacy': ('releaseplan-portable-v', '安装包'),
        'update': ('releaseplan-update-v', '升级包'),
    }
    result = {}
    for key, config in package_types.items():
        prefix, default_name = config
        latest = None
        if downloads_dir.exists():
            for path in downloads_dir.glob(f'{prefix}*.tar.gz'):
                version = path.name[len(prefix):-7]
                version_parts = []
                for part in version.lstrip('v').split('.'):
                    try:
                        version_parts.append(int(part))
                    except ValueError:
                        version_parts.append(part)
                candidate = {
                    'filename': path.name,
                    'version': version,
                    'label': f"{default_name} v{version}" if version else path.name,
                    'sort_key': tuple(version_parts),
                }
                if latest is None or candidate['sort_key'] > latest['sort_key']:
                    latest = candidate
        result[key] = latest or {'filename': '', 'version': '', 'label': ''}
    return result


register_oauth_routes(
    app,
    oauth_enabled=oauth_enabled,
    normalize_next_url=normalize_next_url,
    match_permission_rule=match_permission_rule,
    default_feature_flags=default_feature_flags,
    normalize_feature_flags=normalize_feature_flags,
)


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        month_defs = ",\n                ".join([f'"{month}" TEXT' for month in MILESTONE_COLUMNS])
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_status TEXT,
                control_gate TEXT,
                investment_subject TEXT,
                project_code TEXT,
                project_name TEXT UNIQUE,
                project_description TEXT,
                project_category TEXT,
                project_subcategory TEXT,
                project_complexity TEXT,
                project_role TEXT,
                project_manager TEXT,
                planned_start_date TEXT,
                planned_end_date TEXT,
                workload_person_month TEXT,
                rd_budget_w TEXT,
                headcount_budget_self_owned TEXT,
                headcount_budget_od TEXT,
                headcount_budget_tm TEXT,
                focus_work TEXT,
                feature_name TEXT,
                service_group TEXT,
                delivery_pm TEXT,
                {month_defs},
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
        required_project_columns = [
            'project_status', 'control_gate', 'investment_subject', 'project_code', 'project_description',
            'project_category', 'project_subcategory', 'project_complexity', 'project_role', 'planned_start_date',
            'planned_end_date', 'rd_budget_w', 'headcount_budget_self_owned', 'headcount_budget_od',
            'headcount_budget_tm'
        ]
        for field in required_project_columns:
            if field not in existing_columns:
                conn.execute(f"ALTER TABLE projects ADD COLUMN {field} TEXT")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS project_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER,
                project_name TEXT,
                five_level_department TEXT,
                focus_work TEXT,
                feature_name TEXT,
                service_group TEXT,
                delivery_pm TEXT,
                {month_defs},
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        existing_feature_columns = {row[1] for row in conn.execute("PRAGMA table_info(project_features)").fetchall()}
        if 'five_level_department' not in existing_feature_columns:
            conn.execute("ALTER TABLE project_features ADD COLUMN five_level_department TEXT")
        feature_count = conn.execute("SELECT COUNT(*) FROM project_features").fetchone()[0]
        if feature_count == 0 and 'feature_name' in existing_columns:
            old_rows = conn.execute(
                f"""
                SELECT id, project_name, focus_work, feature_name, service_group, delivery_pm,
                       {', '.join([f'"{m}"' for m in MILESTONE_COLUMNS])}
                FROM projects
                """
            ).fetchall()
            for row in old_rows:
                values = [(row[m] or '') for m in MILESTONE_COLUMNS]
                if any([(row['feature_name'] or '').strip(), (row['focus_work'] or '').strip(), (row['service_group'] or '').strip(), (row['delivery_pm'] or '').strip(), *[str(v).strip() for v in values]]):
                    conn.execute(
                        f"""
                        INSERT INTO project_features (
                            project_id, project_name, five_level_department, focus_work, feature_name, service_group, delivery_pm,
                            {', '.join([f'"{m}"' for m in MILESTONE_COLUMNS])}
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, {', '.join(['?'] * len(MILESTONE_COLUMNS))})
                        """,
                        [row['id'], row['project_name'], '', row['focus_work'], row['feature_name'], row['service_group'], row['delivery_pm'], *values]
                    )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS service_resource_investment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                five_level_department TEXT,
                l4_cloud_service TEXT,
                function_description TEXT,
                summary_self_owned TEXT,
                summary_od TEXT,
                summary_tm TEXT,
                hc_self_owned TEXT,
                hc_od TEXT,
                hc_tm TEXT,
                hcs_self_owned TEXT,
                hcs_od TEXT,
                hcs_tm TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS investment_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_project_id INTEGER UNIQUE,
                investment_subject TEXT,
                control_gate TEXT,
                invested_project TEXT,
                investment_amount TEXT,
                total_person_months TEXT,
                headcount_self_owned TEXT,
                headcount_od TEXT,
                headcount_tm TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(source_project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        existing_investment_columns = {row[1] for row in conn.execute("PRAGMA table_info(investment_records)").fetchall()}
        required_investment_columns = [
            'source_project_id', 'investment_subject', 'control_gate', 'invested_project',
            'investment_amount', 'total_person_months', 'headcount_self_owned',
            'headcount_od', 'headcount_tm',
        ]
        for field in required_investment_columns:
            if field not in existing_investment_columns:
                conn.execute(f"ALTER TABLE investment_records ADD COLUMN {field} TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_investment_records_source_project_id ON investment_records(source_project_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS departments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level_1_department TEXT,
                level_2_department TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS resource_people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT,
                employee_name TEXT,
                person_type TEXT,
                department_id INTEGER,
                project_id INTEGER,
                allocation_ratio TEXT,
                role_name TEXT,
                status TEXT,
                remarks TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(department_id) REFERENCES departments(id) ON DELETE SET NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS requirements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_code TEXT,
                requirement_content TEXT NOT NULL,
                submit_date TEXT NOT NULL,
                close_date TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                submitter TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS login_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                user_name TEXT,
                email TEXT,
                auth_type TEXT,
                role_text TEXT,
                login_ip TEXT,
                user_agent TEXT,
                session_token TEXT,
                login_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_feature_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                project_id INTEGER NOT NULL,
                feature_id INTEGER NOT NULL,
                sort_index INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, project_id, feature_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_code_consumption (
                code TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS milestone_condolence_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                five_level_department TEXT NOT NULL,
                month_index INTEGER NOT NULL,
                activity_date TEXT,
                participant_names TEXT,
                breakthrough_text TEXT,
                condolence_region TEXT,
                image_path TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        existing_milestone_columns = {row[1] for row in conn.execute("PRAGMA table_info(milestone_condolence_items)").fetchall()}
        if 'activity_date' not in existing_milestone_columns:
            conn.execute("ALTER TABLE milestone_condolence_items ADD COLUMN activity_date TEXT")
        if 'participant_names' not in existing_milestone_columns:
            conn.execute("ALTER TABLE milestone_condolence_items ADD COLUMN participant_names TEXT")
        existing_requirement_columns = {row[1] for row in conn.execute("PRAGMA table_info(requirements)").fetchall()}
        if 'submitter' not in existing_requirement_columns:
            conn.execute("ALTER TABLE requirements ADD COLUMN submitter TEXT")
        conn.commit()


def normalize_project_row(row):
    return {
        "立项状态": (row.get("立项状态") or row.get("project_status") or "").strip(),
        "管控灶": (row.get("管控灶") or row.get("control_gate") or "").strip(),
        "投资主体": (row.get("投资主体") or row.get("investment_subject") or "").strip(),
        "项目编码": (row.get("项目编码") or row.get("project_code") or "").strip(),
        "项目名称": (row.get("项目名称") or row.get("project_name") or "").strip(),
        "项目描述": (row.get("项目描述") or row.get("project_description") or "").strip(),
        "项目大类": (row.get("项目大类") or row.get("project_category") or "").strip(),
        "项目子类": (row.get("项目子类") or row.get("project_subcategory") or "").strip(),
        "项目复杂度": (row.get("项目复杂度") or row.get("project_complexity") or "").strip(),
        "项目角色": (row.get("项目角色") or row.get("project_role") or "").strip(),
        "项目经理": (row.get("项目经理") or row.get("project_manager") or "").strip(),
        "计划启动日期": (row.get("计划启动日期") or row.get("planned_start_date") or "").strip(),
        "计划结束日期": (row.get("计划结束日期") or row.get("planned_end_date") or "").strip(),
        "工作量（人月）": (row.get("工作量（人月）") or row.get("工作量(人月)") or row.get("工作量") or row.get("workload_person_month") or "").strip(),
        "研发费用预算（w）": (row.get("研发费用预算（w）") or row.get("研发费用预算(w)") or row.get("rd_budget_w") or "").strip(),
        "人力预算（自有）": (row.get("人力预算（自有）") or row.get("headcount_budget_self_owned") or "").strip(),
        "人力预算（OD）": (row.get("人力预算（OD）") or row.get("headcount_budget_od") or "").strip(),
        "人力预算（TM）": (row.get("人力预算（TM）") or row.get("headcount_budget_tm") or "").strip(),
    }


def normalize_feature_row(row):
    normalized = {
        "项目名称": (row.get("项目名称") or row.get("project_name") or "").strip(),
        "五层部门": (row.get("五层部门") or row.get("five_level_department") or "").strip(),
        "重点工作": (row.get("重点工作") or row.get("focus_work") or "").strip(),
        "关键特性": (row.get("关键特性") or row.get("feature_name") or "").strip(),
        "L4服务或服务组": (row.get("L4服务或服务组") or row.get("service_group") or "").strip(),
        "服务交付PM": (row.get("服务交付PM") or row.get("delivery_pm") or "").strip(),
    }
    for month in MILESTONE_COLUMNS:
        normalized[month] = (row.get(month) or "").strip()
    return normalized


def project_row_to_db_tuple(row):
    return (
        row["立项状态"], row["管控灶"], row["投资主体"], row["项目编码"], row["项目名称"], row["项目描述"],
        row["项目大类"], row["项目子类"], row["项目复杂度"], row["项目角色"], row["项目经理"], row["计划启动日期"], row["计划结束日期"],
        row["工作量（人月）"], row["研发费用预算（w）"], row["人力预算（自有）"], row["人力预算（OD）"], row["人力预算（TM）"],
    )


def feature_row_to_db_tuple(row, project_id=None):
    return (
        project_id, row["项目名称"], row["五层部门"], row["重点工作"], row["关键特性"], row["L4服务或服务组"], row["服务交付PM"],
        *[row[month] for month in MILESTONE_COLUMNS],
    )


def save_project_csv_content(content, replace=False):
    init_db()
    reader = csv.DictReader(StringIO(content))
    rows = [normalize_project_row(row) for row in reader]
    if not rows:
        return 0
    sql_columns = [
        "project_status", "control_gate", "investment_subject", "project_code", "project_name", "project_description",
        "project_category", "project_subcategory", "project_complexity", "project_role", "project_manager", "planned_start_date", "planned_end_date",
        "workload_person_month", "rd_budget_w", "headcount_budget_self_owned", "headcount_budget_od", "headcount_budget_tm"
    ]
    placeholders = ", ".join(["?"] * len(sql_columns))
    with get_conn() as conn:
        if replace:
            conn.execute("DELETE FROM projects")
        conn.executemany(
            f"INSERT INTO projects ({', '.join(sql_columns)}) VALUES ({placeholders})",
            [project_row_to_db_tuple(row) for row in rows],
        )
        conn.commit()
    return len(rows)


def save_feature_csv_content(content, replace=False):
    init_db()
    reader = csv.DictReader(StringIO(content))
    rows = [normalize_feature_row(row) for row in reader]
    if not rows:
        return 0
    with get_conn() as conn:
        if replace:
            conn.execute("DELETE FROM project_features")
        feature_month_columns = ', '.join([f'"{m}"' for m in MILESTONE_COLUMNS])
        feature_month_placeholders = ', '.join(['?'] * len(MILESTONE_COLUMNS))
        for row in rows:
            project_row = conn.execute("SELECT id FROM projects WHERE project_name = ? ORDER BY id LIMIT 1", (row["项目名称"],)).fetchone()
            project_id = project_row['id'] if project_row else None
            conn.execute(
                f"INSERT INTO project_features (project_id, project_name, five_level_department, focus_work, feature_name, service_group, delivery_pm, {feature_month_columns}) VALUES (?, ?, ?, ?, ?, ?, ?, {feature_month_placeholders})",
                feature_row_to_db_tuple(row, project_id=project_id),
            )
        conn.commit()
    return len(rows)


def import_project_csv_file(file_storage, replace=True):
    raw = file_storage.read()
    if isinstance(raw, bytes):
        content = raw.decode('utf-8-sig')
    else:
        content = raw
    return save_project_csv_content(content, replace=replace)


def import_csv(replace=False):
    init_db()
    if not PROJECT_CSV_PATH.exists():
        return 0
    with PROJECT_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        return save_project_csv_content(f.read(), replace=replace)


def import_csv_if_needed():
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    if count == 0:
        import_csv(replace=False)


def load_projects():
    init_db()
    import_csv_if_needed()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                project_status,
                control_gate,
                investment_subject,
                project_code,
                project_name,
                project_description,
                project_category,
                project_subcategory,
                project_complexity,
                project_role,
                project_manager,
                planned_start_date,
                planned_end_date,
                workload_person_month,
                rd_budget_w,
                headcount_budget_self_owned,
                headcount_budget_od,
                headcount_budget_tm
            FROM projects
            ORDER BY project_name ASC, id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def sync_investment_records_from_projects():
    init_db()
    with get_conn() as conn:
        project_rows = conn.execute(
            """
            SELECT
                id,
                investment_subject,
                control_gate,
                project_name,
                rd_budget_w,
                workload_person_month,
                headcount_budget_self_owned,
                headcount_budget_od,
                headcount_budget_tm
            FROM projects
            """
        ).fetchall()
        project_ids = [row['id'] for row in project_rows]
        if project_ids:
            placeholders = ','.join(['?'] * len(project_ids))
            conn.execute(
                f"DELETE FROM investment_records WHERE source_project_id IS NOT NULL AND source_project_id NOT IN ({placeholders})",
                project_ids,
            )
        else:
            conn.execute("DELETE FROM investment_records WHERE source_project_id IS NOT NULL")
        for row in project_rows:
            conn.execute(
                """
                INSERT INTO investment_records (
                    source_project_id,
                    investment_subject,
                    control_gate,
                    invested_project,
                    investment_amount,
                    total_person_months,
                    headcount_self_owned,
                    headcount_od,
                    headcount_tm
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_project_id) DO UPDATE SET
                    investment_subject = excluded.investment_subject,
                    control_gate = excluded.control_gate,
                    invested_project = excluded.invested_project,
                    investment_amount = excluded.investment_amount,
                    total_person_months = excluded.total_person_months,
                    headcount_self_owned = excluded.headcount_self_owned,
                    headcount_od = excluded.headcount_od,
                    headcount_tm = excluded.headcount_tm,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    row['id'],
                    row['investment_subject'] or '',
                    row['control_gate'] or '',
                    row['project_name'] or '',
                    row['rd_budget_w'] or '',
                    row['workload_person_month'] or '',
                    row['headcount_budget_self_owned'] or '',
                    row['headcount_budget_od'] or '',
                    row['headcount_budget_tm'] or '',
                ),
            )
        conn.commit()


def load_investment_records():
    init_db()
    import_csv_if_needed()
    sync_investment_records_from_projects()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                source_project_id,
                investment_subject,
                control_gate,
                invested_project,
                investment_amount,
                total_person_months,
                headcount_self_owned,
                headcount_od,
                headcount_tm
            FROM investment_records
            ORDER BY investment_subject ASC, control_gate ASC, invested_project ASC, id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def load_project_features():
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
                id,
                project_id,
                project_name,
                five_level_department,
                focus_work,
                feature_name,
                service_group,
                delivery_pm,
                {', '.join([f'"{month}"' for month in MILESTONE_COLUMNS])}
            FROM project_features
            ORDER BY project_name ASC, id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def load_project(project_id):
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            f"""
            SELECT
                id,
                project_status,
                control_gate,
                investment_subject,
                project_code,
                project_name,
                project_description,
                project_category,
                project_subcategory,
                project_complexity,
                project_role,
                project_manager,
                planned_start_date,
                planned_end_date,
                workload_person_month,
                rd_budget_w,
                headcount_budget_self_owned,
                headcount_budget_od,
                headcount_budget_tm,
                focus_work,
                feature_name,
                service_group,
                delivery_pm,
                {', '.join([f'"{month}"' for month in MILESTONE_COLUMNS])}
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        ).fetchone()
        return dict(row) if row else None


def load_project_options():
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, project_name
            FROM projects
            WHERE TRIM(COALESCE(project_name, '')) <> ''
            ORDER BY project_name ASC, id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def load_departments():
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, level_1_department, level_2_department
            FROM departments
            ORDER BY level_1_department ASC, level_2_department ASC, id ASC
            """
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['department_full_name'] = ' / '.join([
                (item.get('level_1_department') or '').strip(),
                (item.get('level_2_department') or '').strip(),
            ])
            item['department_full_name'] = ' / '.join([part for part in item['department_full_name'].split(' / ') if part])
            result.append(item)
        return result


def load_department(department_id):
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, level_1_department, level_2_department
            FROM departments
            WHERE id = ?
            """,
            (department_id,),
        ).fetchone()
        return dict(row) if row else None


def form_to_department_data(form):
    return {
        'level_1_department': (form.get('level_1_department') or '').strip(),
        'level_2_department': (form.get('level_2_department') or '').strip(),
    }


def load_resource_people():
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                rp.id,
                rp.employee_id,
                rp.employee_name,
                rp.person_type,
                rp.department_id,
                rp.project_id,
                rp.allocation_ratio,
                rp.role_name,
                rp.status,
                rp.remarks,
                d.level_1_department,
                d.level_2_department,
                p.project_name
            FROM resource_people rp
            LEFT JOIN departments d ON d.id = rp.department_id
            LEFT JOIN projects p ON p.id = rp.project_id
            ORDER BY rp.employee_id ASC, rp.employee_name ASC, rp.id ASC
            """
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            upper_department = (item.get('level_1_department') or '').strip()
            level_2_department = (item.get('level_2_department') or '').strip()
            smallest_department = level_2_department or upper_department
            item['upper_department_name'] = upper_department
            item['smallest_department_name'] = smallest_department
            item['department_full_name'] = ' / '.join([part for part in [upper_department, level_2_department] if part])
            result.append(item)
        return result


def get_resource_people_admin_filter_options(rows):
    return {
        'projects': sorted({(row.get('project_name') or '').strip() for row in rows if (row.get('project_name') or '').strip()}),
        'departments': sorted({(row.get('department_full_name') or '').strip() for row in rows if (row.get('department_full_name') or '').strip()}),
        'upper_departments': sorted({(row.get('upper_department_name') or '').strip() for row in rows if (row.get('upper_department_name') or '').strip()}),
        'smallest_departments': sorted({(row.get('smallest_department_name') or '').strip() for row in rows if (row.get('smallest_department_name') or '').strip()}),
        'roles': sorted({(row.get('role_name') or '').strip() for row in rows if (row.get('role_name') or '').strip()}),
        'statuses': sorted({(row.get('status') or '').strip() for row in rows if (row.get('status') or '').strip()}),
    }


def filter_resource_people_admin(rows, keyword='', project_name='', department_name='', upper_department='', smallest_department='', role_name='', status=''):
    keyword = (keyword or '').strip().lower()
    project_name = (project_name or '').strip().lower()
    department_name = (department_name or '').strip().lower()
    upper_department = (upper_department or '').strip().lower()
    smallest_department = (smallest_department or '').strip().lower()
    role_name = (role_name or '').strip().lower()
    status = (status or '').strip().lower()

    def matched(row):
        keyword_ok = (not keyword) or keyword in (row.get('employee_id') or '').strip().lower() or keyword in (row.get('employee_name') or '').strip().lower()
        project_ok = (not project_name) or (row.get('project_name') or '').strip().lower() == project_name
        department_ok = (not department_name) or (row.get('department_full_name') or '').strip().lower() == department_name
        upper_department_ok = (not upper_department) or (row.get('upper_department_name') or '').strip().lower() == upper_department
        smallest_department_ok = (not smallest_department) or (row.get('smallest_department_name') or '').strip().lower() == smallest_department
        role_ok = (not role_name) or (row.get('role_name') or '').strip().lower() == role_name
        status_ok = (not status) or (row.get('status') or '').strip().lower() == status
        return keyword_ok and project_ok and department_ok and upper_department_ok and smallest_department_ok and role_ok and status_ok

    return [row for row in rows if matched(row)]


def load_resource_person(record_id):
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                rp.id,
                rp.employee_id,
                rp.employee_name,
                rp.person_type,
                rp.department_id,
                rp.project_id,
                rp.allocation_ratio,
                rp.role_name,
                rp.status,
                rp.remarks,
                d.level_1_department,
                d.level_2_department
            FROM resource_people rp
            LEFT JOIN departments d ON d.id = rp.department_id
            WHERE rp.id = ?
            """,
            (record_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        upper_department = (item.get('level_1_department') or '').strip()
        smallest_department = (item.get('level_2_department') or '').strip() or upper_department
        item['upper_department_name'] = upper_department
        item['smallest_department_name'] = smallest_department
        return item


def form_to_resource_person_data(form):
    department_id = (form.get('department_id') or '').strip()
    project_id = (form.get('project_id') or '').strip()
    return {
        'employee_id': (form.get('employee_id') or '').strip(),
        'employee_name': (form.get('employee_name') or '').strip(),
        'person_type': (form.get('person_type') or '').strip(),
        'department_id': int(department_id) if department_id.isdigit() else None,
        'project_id': int(project_id) if project_id.isdigit() else None,
        'allocation_ratio': (form.get('allocation_ratio') or '').strip(),
        'role_name': (form.get('role_name') or '').strip(),
        'status': (form.get('status') or '').strip(),
        'remarks': (form.get('remarks') or '').strip(),
    }


def parse_ratio_value(value):
    text = (value or '').strip()
    if not text:
        return 0.0
    if text.endswith('%'):
        try:
            return float(text[:-1]) / 100.0
        except ValueError:
            return 0.0
    try:
        number = float(text)
        return number / 100.0 if number > 1 else number
    except ValueError:
        return 0.0


def build_resource_people_summary(rows):
    active_count = sum(1 for row in rows if (row.get('status') or '').strip())
    project_bound_count = sum(1 for row in rows if (row.get('project_name') or '').strip())
    department_bound_count = sum(1 for row in rows if (row.get('department_full_name') or '').strip())
    allocation_total = round(sum(parse_ratio_value(row.get('allocation_ratio')) for row in rows), 2)
    count = len(rows)
    project_bound_ratio = round((project_bound_count / count) if count else 0.0, 4)
    return {
        'count': count,
        'active_count': active_count,
        'project_bound_count': project_bound_count,
        'department_bound_count': department_bound_count,
        'allocation_total': allocation_total,
        'project_bound_ratio': project_bound_ratio,
    }


def get_resource_people_filter_options(rows):
    return {
        'person_types': sorted({(row.get('person_type') or '').strip() for row in rows if (row.get('person_type') or '').strip()}),
        'departments': sorted({(row.get('department_full_name') or '').strip() for row in rows if (row.get('department_full_name') or '').strip()}),
        'projects': sorted({(row.get('project_name') or '').strip() for row in rows if (row.get('project_name') or '').strip()}),
    }


def filter_resource_people(rows, person_type='', department_name='', project_name='', keyword=''):
    person_type = (person_type or '').strip().lower()
    department_name = (department_name or '').strip().lower()
    project_name = (project_name or '').strip().lower()
    keyword = (keyword or '').strip().lower()

    def matched(row):
        person_type_ok = not person_type or (row.get('person_type') or '').strip().lower() == person_type
        department_ok = not department_name or (row.get('department_full_name') or '').strip().lower() == department_name
        project_ok = not project_name or (row.get('project_name') or '').strip().lower() == project_name
        keyword_ok = not keyword or keyword in (row.get('employee_id') or '').strip().lower() or keyword in (row.get('employee_name') or '').strip().lower()
        return person_type_ok and department_ok and project_ok and keyword_ok

    return [row for row in rows if matched(row)]


def get_resource_person_type_bucket(person_type):
    value = (person_type or '').strip().lower()
    if value == '自有':
        return 'self_owned_count'
    if value == 'od':
        return 'od_count'
    if value in ('tm', '外包'):
        return 'tm_count'
    return None


def build_resource_group_summary(rows, group_key, mode='allocation_total'):
    grouped = {}
    for row in rows:
        key = (row.get(group_key) or '').strip() or '未填写'
        if key not in grouped:
            grouped[key] = {
                'name': key,
                'count': 0,
                'self_owned_count': 0,
                'od_count': 0,
                'tm_count': 0,
                'allocation_total': 0.0,
                'project_bound_count': 0,
                'project_bound_ratio': 0.0,
            }
        grouped[key]['count'] += 1
        type_bucket = get_resource_person_type_bucket(row.get('person_type'))
        if type_bucket:
            grouped[key][type_bucket] += 1
        grouped[key]['allocation_total'] += parse_ratio_value(row.get('allocation_ratio'))
        if (row.get('project_name') or '').strip():
            grouped[key]['project_bound_count'] += 1
    result = list(grouped.values())
    for item in result:
        item['allocation_total'] = round(item['allocation_total'], 2)
        item['project_bound_ratio'] = round((item['project_bound_count'] / item['count']) if item['count'] else 0.0, 4)
    result.sort(key=lambda item: (-item['count'], item['name']))
    return result


def parse_date_parts(date_text):
    value = (date_text or '').strip()
    if not value:
        return None, None
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y-%m', '%Y/%m', '%Y.%m'):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.year, parsed.month
        except ValueError:
            continue
    return None, None


def parse_workload_value(value):
    text = (value or '').strip()
    if not text:
        return -1
    try:
        return float(text)
    except ValueError:
        return -1


def build_project_gantt(project_rows, display_year):
    gantt_projects = []
    for row in project_rows:
        start_value = (row.get("planned_start_date") or "").strip()
        end_value = (row.get("planned_end_date") or "").strip()
        start_year, start_month = parse_date_parts(start_value)
        end_year, end_month = parse_date_parts(end_value)

        start_index = start_month - 1 if start_year == display_year and start_month else None
        end_index = end_month - 1 if end_year == display_year and end_month else None

        if start_index is not None and end_index is None:
            end_index = start_index
        if end_index is not None and start_index is None:
            start_index = end_index
        if start_index is not None and end_index is not None and end_index < start_index:
            start_index, end_index = end_index, start_index

        gantt_projects.append({
            "id": row.get("id"),
            "project_name": (row.get("project_name") or "").strip() or "未命名项目",
            "project_role": (row.get("project_role") or "").strip(),
            "project_manager": (row.get("project_manager") or "").strip(),
            "workload_person_month": (row.get("workload_person_month") or "").strip(),
            "planned_start_date": start_value or '未填写',
            "planned_end_date": end_value or '未填写',
            "start_label": MONTH_LABELS[start_index] if start_index is not None else "-",
            "end_label": MONTH_LABELS[end_index] if end_index is not None else "-",
            "start_percent": (start_index / 12 * 100) if start_index is not None else 0,
            "width_percent": ((end_index - start_index + 1) / 12 * 100) if start_index is not None and end_index is not None else 0,
            "has_schedule": start_index is not None and end_index is not None,
        })
    return gantt_projects


def load_user_feature_orders(user_id):
    user_id = (user_id or '').strip()
    if not user_id:
        return {}
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT project_id, feature_id, sort_index
            FROM user_feature_orders
            WHERE user_id = ?
            ORDER BY sort_index ASC, id ASC
            """,
            (user_id,),
        ).fetchall()
    return {(row['project_id'], row['feature_id']): row['sort_index'] for row in rows}


def build_project_roadmap(project_rows, feature_rows, user_feature_orders=None):
    user_feature_orders = user_feature_orders or {}
    grouped = {}
    project_id_map = {}
    for row in project_rows:
        project_name = (row.get("project_name") or "").strip() or "未命名项目"
        grouped[project_name] = {
            "project_id": row.get("id"),
            "project_name": project_name,
            "project_manager": (row.get("project_manager") or "").strip(),
            "project_code": (row.get("project_code") or "").strip(),
            "project_status": (row.get("project_status") or "").strip(),
            "features": [],
        }
        project_id_map[row.get("id")] = project_name

    for row in feature_rows:
        project_name = (row.get("project_name") or "").strip() or project_id_map.get(row.get("project_id")) or "未命名项目"
        feature_name = (row.get("feature_name") or "").strip() or "未命名关键特性"
        active_indexes = [i for i, month in enumerate(MILESTONE_COLUMNS) if (row.get(month) or "").strip()]
        month_values = [(row.get(month) or "").strip() for month in MILESTONE_COLUMNS]

        if active_indexes:
            start_index = active_indexes[0]
            end_index = active_indexes[-1]
            start_percent = start_index / 12 * 100
            width_percent = (end_index - start_index + 1) / 12 * 100
        else:
            start_index = None
            end_index = None
            start_percent = 0
            width_percent = 0

        feature_order = user_feature_orders.get((row.get("project_id"), row.get("id")))
        is_pinned = feature_order is not None and feature_order <= 0
        feature = {
            "id": row.get("id"),
            "project_id": row.get("project_id"),
            "sort_index": feature_order if feature_order is not None else 10**9,
            "base_index": row.get("id") or 10**9,
            "is_pinned": is_pinned,
            "five_level_department": (row.get("five_level_department") or "").strip(),
            "feature_name": feature_name,
            "focus_work": (row.get("focus_work") or "").strip(),
            "service_group": (row.get("service_group") or "").strip(),
            "delivery_pm": (row.get("delivery_pm") or "").strip(),
            "start_label": MONTH_LABELS[start_index] if start_index is not None else "-",
            "end_label": MONTH_LABELS[end_index] if end_index is not None else "-",
            "start_percent": start_percent,
            "width_percent": width_percent,
            "month_values": month_values,
            "active_indexes": active_indexes,
        }

        if project_name not in grouped:
            grouped[project_name] = {
                "project_id": row.get("project_id"),
                "project_name": project_name,
                "project_manager": "",
                "project_code": "",
                "project_status": "",
                "features": [],
            }
        grouped[project_name]["features"].append(feature)

    for project in grouped.values():
        project["features"].sort(
            key=lambda item: (
                0 if item.get("is_pinned") else 1,
                item.get("sort_index", 10**9) if item.get("is_pinned") else item.get("base_index", 10**9)
            )
        )

    return list(grouped.values())


def form_to_project_data(form):
    data = {
        "project_status": (form.get("project_status") or "").strip(),
        "control_gate": (form.get("control_gate") or "").strip(),
        "investment_subject": (form.get("investment_subject") or "").strip(),
        "project_code": (form.get("project_code") or "").strip(),
        "project_name": (form.get("project_name") or "").strip(),
        "project_description": (form.get("project_description") or "").strip(),
        "project_category": (form.get("project_category") or "").strip(),
        "project_subcategory": (form.get("project_subcategory") or "").strip(),
        "project_complexity": (form.get("project_complexity") or "").strip(),
        "project_role": (form.get("project_role") or "").strip(),
        "project_manager": (form.get("project_manager") or "").strip(),
        "planned_start_date": (form.get("planned_start_date") or "").strip(),
        "planned_end_date": (form.get("planned_end_date") or "").strip(),
        "workload_person_month": (form.get("workload_person_month") or "").strip(),
        "rd_budget_w": (form.get("rd_budget_w") or "").strip(),
        "headcount_budget_self_owned": (form.get("headcount_budget_self_owned") or "").strip(),
        "headcount_budget_od": (form.get("headcount_budget_od") or "").strip(),
        "headcount_budget_tm": (form.get("headcount_budget_tm") or "").strip(),
        "focus_work": (form.get("focus_work") or "").strip(),
        "feature_name": (form.get("feature_name") or "").strip(),
        "service_group": (form.get("service_group") or "").strip(),
        "delivery_pm": (form.get("delivery_pm") or "").strip(),
    }
    for month in MILESTONE_COLUMNS:
        data[month] = (form.get(month) or "").strip()
    return data


def form_to_feature_data(form):
    data = {
        "project_name": (form.get("project_name") or "").strip(),
        "five_level_department": (form.get("five_level_department") or "").strip(),
        "focus_work": (form.get("focus_work") or "").strip(),
        "feature_name": (form.get("feature_name") or "").strip(),
        "service_group": (form.get("service_group") or "").strip(),
        "delivery_pm": (form.get("delivery_pm") or "").strip(),
    }
    for month in MILESTONE_COLUMNS:
        data[month] = (form.get(month) or "").strip()
    return data


def get_project_options():
    rows = load_projects()
    return [
        {
            "id": row.get("id"),
            "project_name": row.get("project_name") or "",
            "project_code": row.get("project_code") or "",
        }
        for row in rows
        if (row.get("project_name") or "").strip()
    ]


def load_project_feature(feature_id):
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            f"""
            SELECT id, project_id, project_name, five_level_department, focus_work, feature_name, service_group, delivery_pm,
                   {', '.join([f'"{month}"' for month in MILESTONE_COLUMNS])}
            FROM project_features
            WHERE id = ?
            """,
            (feature_id,),
        ).fetchone()
        return dict(row) if row else None


def form_to_service_resource_data(form):
    hc_self_owned = (form.get("hc_self_owned") or "").strip()
    hc_od = (form.get("hc_od") or "").strip()
    hc_tm = (form.get("hc_tm") or "").strip()
    hcs_self_owned = (form.get("hcs_self_owned") or "").strip()
    hcs_od = (form.get("hcs_od") or "").strip()
    hcs_tm = (form.get("hcs_tm") or "").strip()

    return {
        "five_level_department": (form.get("five_level_department") or "").strip(),
        "l4_cloud_service": (form.get("l4_cloud_service") or "").strip(),
        "function_description": (form.get("function_description") or "").strip(),
        "summary_self_owned": format_number(to_number(hc_self_owned) + to_number(hcs_self_owned)),
        "summary_od": format_number(to_number(hc_od) + to_number(hcs_od)),
        "summary_tm": format_number(to_number(hc_tm) + to_number(hcs_tm)),
        "hc_self_owned": hc_self_owned,
        "hc_od": hc_od,
        "hc_tm": hc_tm,
        "hcs_self_owned": hcs_self_owned,
        "hcs_od": hcs_od,
        "hcs_tm": hcs_tm,
    }


def load_service_resources():
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                five_level_department,
                l4_cloud_service,
                function_description,
                summary_self_owned,
                summary_od,
                summary_tm,
                hc_self_owned,
                hc_od,
                hc_tm,
                hcs_self_owned,
                hcs_od,
                hcs_tm
            FROM service_resource_investment
            ORDER BY five_level_department ASC, l4_cloud_service ASC, id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def load_service_resource(record_id):
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                five_level_department,
                l4_cloud_service,
                function_description,
                summary_self_owned,
                summary_od,
                summary_tm,
                hc_self_owned,
                hc_od,
                hc_tm,
                hcs_self_owned,
                hcs_od,
                hcs_tm
            FROM service_resource_investment
            WHERE id = ?
            """,
            (record_id,),
        ).fetchone()
        return dict(row) if row else None


def to_number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def format_number(value):
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip('0').rstrip('.')


def build_service_resource_summary(rows):
    return {
        "count": len(rows),
        "summary_self_owned": round(sum(to_number(row.get("summary_self_owned")) for row in rows), 2),
        "summary_od": round(sum(to_number(row.get("summary_od")) for row in rows), 2),
        "summary_tm": round(sum(to_number(row.get("summary_tm")) for row in rows), 2),
        "summary_total": round(sum(to_number(row.get("summary_self_owned")) + to_number(row.get("summary_od")) + 0.8 * to_number(row.get("summary_tm")) for row in rows), 2),
        "hc_total": round(sum(to_number(row.get("hc_self_owned")) + to_number(row.get("hc_od")) + to_number(row.get("hc_tm")) for row in rows), 2),
        "hcs_total": round(sum(to_number(row.get("hcs_self_owned")) + to_number(row.get("hcs_od")) + to_number(row.get("hcs_tm")) for row in rows), 2),
    }


def filter_service_resources(rows, department_keyword='', service_keyword=''):
    department_keyword = (department_keyword or '').strip().lower()
    service_keyword = (service_keyword or '').strip().lower()

    def matched(row):
        department_value = (row.get('five_level_department') or '').lower()
        service_value = (row.get('l4_cloud_service') or '').lower()
        department_ok = not department_keyword or department_keyword == department_value
        service_ok = not service_keyword or service_keyword == service_value
        return department_ok and service_ok

    return [row for row in rows if matched(row)]


def get_service_resource_filter_options(rows):
    departments = sorted({(row.get('five_level_department') or '').strip() for row in rows if (row.get('five_level_department') or '').strip()})
    services = sorted({(row.get('l4_cloud_service') or '').strip() for row in rows if (row.get('l4_cloud_service') or '').strip()})
    return {
        'departments': departments,
        'services': services,
    }


def normalize_service_resource_row(row):
    data = {
        "five_level_department": (row.get("五层部门") or row.get("five_level_department") or "").strip(),
        "l4_cloud_service": (row.get("L4云服务") or row.get("l4_cloud_service") or "").strip(),
        "function_description": (row.get("功能和用途简介") or row.get("function_description") or "").strip(),
        "hc_self_owned": (row.get("HC（自有）") or row.get("hc_self_owned") or "").strip(),
        "hc_od": (row.get("HC（OD）") or row.get("hc_od") or "").strip(),
        "hc_tm": (row.get("HC（TM）") or row.get("hc_tm") or "").strip(),
        "hcs_self_owned": (row.get("HCS（自有）") or row.get("hcs_self_owned") or "").strip(),
        "hcs_od": (row.get("HCS（OD）") or row.get("hcs_od") or "").strip(),
        "hcs_tm": (row.get("HCS（TM）") or row.get("hcs_tm") or "").strip(),
    }
    data["summary_self_owned"] = format_number(to_number(data["hc_self_owned"]) + to_number(data["hcs_self_owned"]))
    data["summary_od"] = format_number(to_number(data["hc_od"]) + to_number(data["hcs_od"]))
    data["summary_tm"] = format_number(to_number(data["hc_tm"]) + to_number(data["hcs_tm"]))
    return data


def import_service_resource_rows(rows, replace=True):
    init_db()
    if not rows:
        return 0

    with get_conn() as conn:
        if replace:
            conn.execute("DELETE FROM service_resource_investment")
        conn.executemany(
            """
            INSERT INTO service_resource_investment (
                five_level_department,
                l4_cloud_service,
                function_description,
                summary_self_owned,
                summary_od,
                summary_tm,
                hc_self_owned,
                hc_od,
                hc_tm,
                hcs_self_owned,
                hcs_od,
                hcs_tm
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["five_level_department"], row["l4_cloud_service"], row["function_description"],
                    row["summary_self_owned"], row["summary_od"], row["summary_tm"],
                    row["hc_self_owned"], row["hc_od"], row["hc_tm"],
                    row["hcs_self_owned"], row["hcs_od"], row["hcs_tm"],
                )
                for row in rows
            ],
        )
        conn.commit()
    return len(rows)


def import_service_resource_csv_file(file_storage, replace=True):
    content = file_storage.read().decode('utf-8-sig')
    reader = csv.DictReader(StringIO(content))
    rows = [normalize_service_resource_row(row) for row in reader]
    return import_service_resource_rows(rows, replace=replace)


def import_resource_people_csv_file(file_storage, replace=True):
    content = file_storage.read().decode('utf-8-sig')
    reader = csv.DictReader(StringIO(content))
    rows = list(reader)
    department_options = load_departments()
    project_options = load_project_options()
    department_map = {((item.get('department_full_name') or '').strip()): item.get('id') for item in department_options}
    department_pair_map = {
        (
            (item.get('level_1_department') or '').strip(),
            (item.get('level_2_department') or '').strip() or (item.get('level_1_department') or '').strip(),
        ): item.get('id')
        for item in department_options
    }
    department_leaf_counts = {}
    for item in department_options:
        leaf_name = ((item.get('level_2_department') or '').strip() or (item.get('level_1_department') or '').strip())
        if leaf_name:
            department_leaf_counts[leaf_name] = department_leaf_counts.get(leaf_name, 0) + 1
    department_leaf_map = {
        ((item.get('level_2_department') or '').strip() or (item.get('level_1_department') or '').strip()): item.get('id')
        for item in department_options
        if department_leaf_counts.get(((item.get('level_2_department') or '').strip() or (item.get('level_1_department') or '').strip())) == 1
    }
    project_map = {((item.get('project_name') or '').strip()): item.get('id') for item in project_options}

    normalized_rows = []
    for row in rows:
        upper_department_name = (row.get('上层部门') or row.get('一级部门') or '').strip()
        smallest_department_name = (row.get('最小部门') or row.get('二级部门') or '').strip()
        legacy_department_name = (row.get('部门') or '').strip()
        department_name = ' / '.join([part for part in [upper_department_name, smallest_department_name] if part])
        department_id = None
        if upper_department_name or smallest_department_name:
            department_id = department_pair_map.get((upper_department_name, smallest_department_name))
            if department_id is None and upper_department_name and not smallest_department_name:
                department_id = department_pair_map.get((upper_department_name, upper_department_name))
            if department_id is None:
                department_id = department_map.get(department_name)
            if department_id is None and not upper_department_name:
                department_id = department_map.get(smallest_department_name) or department_leaf_map.get(smallest_department_name)
        elif legacy_department_name:
            department_id = department_map.get(legacy_department_name) or department_leaf_map.get(legacy_department_name)
        project_name = (row.get('所属项目') or '').strip()
        normalized_rows.append({
            'employee_id': (row.get('工号') or '').strip(),
            'employee_name': (row.get('姓名') or '').strip(),
            'person_type': (row.get('人员类型') or '').strip(),
            'department_id': department_id,
            'project_id': project_map.get(project_name) if project_name else None,
            'allocation_ratio': (row.get('投入比例') or '').strip(),
            'role_name': (row.get('角色') or '').strip(),
            'status': (row.get('状态') or '').strip(),
            'remarks': (row.get('备注') or '').strip(),
        })

    with get_conn() as conn:
        if replace:
            conn.execute('DELETE FROM resource_people')
        conn.executemany(
            """
            INSERT INTO resource_people (
                employee_id, employee_name, person_type, department_id, project_id,
                allocation_ratio, role_name, status, remarks
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row['employee_id'], row['employee_name'], row['person_type'], row['department_id'], row['project_id'],
                    row['allocation_ratio'], row['role_name'], row['status'], row['remarks'],
                )
                for row in normalized_rows
            ],
        )
        conn.commit()
    return len(normalized_rows)


def seed_service_resources_if_empty():
    init_db()
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM service_resource_investment").fetchone()[0]
        if count > 0:
            return
        seeded_flag = conn.execute("SELECT value FROM app_settings WHERE key = ?", ('service_resources_seeded_once',)).fetchone()
        if seeded_flag and str(seeded_flag[0] or '').strip() == '1':
            return

    imported = 0
    if SERVICE_RESOURCE_CSV_PATH.exists():
        with SERVICE_RESOURCE_CSV_PATH.open('rb') as f:
            class LocalFile:
                def read(self_inner):
                    return f.read()
            imported = import_service_resource_csv_file(LocalFile(), replace=True)

    if imported <= 0:
        seed_rows = [
            {"五层部门": "云平台部", "L4云服务": "容器云", "功能和用途简介": "提供容器编排与运行环境", "HC（自有）": "4", "HC（OD）": "1", "HC（TM）": "1", "HCS（自有）": "120", "HCS（OD）": "30", "HCS（TM）": "15"},
            {"五层部门": "云平台部", "L4云服务": "对象存储", "功能和用途简介": "提供对象存储与归档能力", "HC（自有）": "3", "HC（OD）": "1", "HC（TM）": "1", "HCS（自有）": "90", "HCS（OD）": "20", "HCS（TM）": "12"},
            {"五层部门": "基础设施部", "L4云服务": "云网络", "功能和用途简介": "提供 VPC、负载均衡与网络连接能力", "HC（自有）": "5", "HC（OD）": "1", "HC（TM）": "1", "HCS（自有）": "140", "HCS（OD）": "35", "HCS（TM）": "18"},
        ]
        imported = import_service_resource_rows([normalize_service_resource_row(row) for row in seed_rows], replace=True)

    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            ('service_resources_seeded_once', '1')
        )
        conn.commit()


try:
    import src.routes_auth  # noqa: F401
    import src.routes_settings  # noqa: F401
    import src.routes_milestone  # noqa: F401
    import src.routes_misc  # noqa: F401
    import src.routes_resources  # noqa: F401
    import src.routes_core_views  # noqa: F401
    import src.routes_projects  # noqa: F401
except Exception:
    pass


if __name__ == '__main__':
    import sys

    if '--backup-now' in sys.argv:
        backup_type = 'auto' if '--backup-type' in sys.argv and 'auto' in sys.argv else 'manual'
        archive_path = build_backup_archive(backup_type=backup_type)
        print(archive_path)
        raise SystemExit(0)

    app.run(host='0.0.0.0', port=5010, debug=False)
