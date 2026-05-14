from flask import Flask, redirect, render_template, request, session, url_for, Response, flash
import requests
import secrets
from io import StringIO
from urllib.parse import quote, urlencode
from werkzeug.middleware.proxy_fix import ProxyFix
import csv
import json
import os
import sqlite3
from functools import wraps
from pathlib import Path
from datetime import datetime
import hashlib
import shutil
import zipfile

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
    "项目复杂度", "项目经理", "计划启动日期", "计划结束日期", "工作量（人月）",
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


def get_home_cards():
    default_cards = [
        {
            "key": "department-pipeline-load",
            "title": os.getenv("RELEASEPLAN_CARD_1_TITLE", "项目视图"),
            "desc": "查看项目视图页面的内容，项目甘特图、项目主要信息。",
            "href": url_for('view_placeholder', view_key='department-pipeline-load'),
        },
        {
            "key": "roadmap",
            "title": os.getenv("RELEASEPLAN_CARD_2_TITLE", "关键特性视图"),
            "desc": "查看所规划关键特性的路标信息。",
            "href": url_for('roadmap'),
        },
        {
            "key": "department-budget-resource",
            "title": os.getenv("RELEASEPLAN_CARD_3_TITLE", "投资视图"),
            "desc": "从投资维度看管道。",
            "href": url_for('view_placeholder', view_key='department-budget-resource'),
        },
        {
            "key": "project-budget-resource",
            "title": os.getenv("RELEASEPLAN_CARD_4_TITLE", "资源视图"),
            "desc": "了解部门人力资源情况。",
            "href": url_for('view_placeholder', view_key='project-budget-resource'),
        },
        {
            "key": "cloud-service-view",
            "title": os.getenv("RELEASEPLAN_CARD_5_TITLE", "云服务视图"),
            "desc": "按云服务粒度查看资源投入情况。",
            "href": url_for('view_placeholder', view_key='cloud-service-view'),
        },
    ]
    preferred_order = [
        os.getenv("RELEASEPLAN_CARD_1_KEY", "department-pipeline-load"),
        os.getenv("RELEASEPLAN_CARD_2_KEY", "roadmap"),
        os.getenv("RELEASEPLAN_CARD_3_KEY", "department-budget-resource"),
        os.getenv("RELEASEPLAN_CARD_4_KEY", "project-budget-resource"),
        os.getenv("RELEASEPLAN_CARD_5_KEY", "cloud-service-view"),
    ]
    card_map = {card["key"]: card for card in default_cards}
    ordered = [card_map[key] for key in preferred_order if key in card_map]
    used = {card["key"] for card in ordered}
    ordered.extend(card for card in default_cards if card["key"] not in used)
    return ordered


def get_branding():
    home_title = os.getenv("RELEASEPLAN_HOME_TITLE", "ReleasePlan")
    browser_title = os.getenv("RELEASEPLAN_BROWSER_TITLE", f"{home_title} 入口")
    roadmap_browser_title = os.getenv("RELEASEPLAN_ROADMAP_BROWSER_TITLE", f"{home_title} 月度进展路标图")
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
    guest_username = (os.getenv('RELEASEPLAN_LOCAL_GUEST_USERNAME') or '').strip()
    guest_password = (os.getenv('RELEASEPLAN_LOCAL_GUEST_PASSWORD') or '').strip()
    return bool((admin_username and admin_password) or (guest_username and guest_password))


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


def is_admin_user(user=None):
    user = user if user is not None else get_current_user()
    if not isinstance(user, dict):
        return False
    roles = user.get('roles') or []
    if isinstance(roles, str):
        roles = [roles]
    normalized = {str(role).strip().lower() for role in roles if str(role).strip()}
    admin_roles = {
        role.strip().lower()
        for role in (os.getenv('RELEASEPLAN_OAUTH_ADMIN_ROLES', 'admin,administrator,releaseplan-admin').split(','))
        if role.strip()
    }
    if normalized & admin_roles:
        return True
    admin_emails = {
        item.strip().lower()
        for item in (os.getenv('RELEASEPLAN_OAUTH_ADMIN_EMAILS', '').split(','))
        if item.strip()
    }
    email = (user.get('email') or '').strip().lower()
    return bool(email and email in admin_emails)


def can_edit(user=None):
    mode = auth_mode()
    if mode == 'none':
        return True
    return is_admin_user(user)


def build_auth_context():
    user = get_current_user()
    auth_type = (user or {}).get('auth_type') if isinstance(user, dict) else None
    role_labels = get_current_user_roles()
    return {
        'auth_mode': auth_mode(),
        'current_user': user,
        'can_edit': can_edit(user),
        'user_roles': role_labels,
        'login_source_label': 'SSO' if auth_type == 'oauth2' else '本地' if auth_type == 'local' else '',
        'role_label': '管理员' if 'admin' in role_labels else '只读' if 'guest' in role_labels else '',
    }


def verify_local_admin(username, password):
    expected_username = (os.getenv('RELEASEPLAN_LOCAL_ADMIN_USERNAME') or '').strip()
    expected_password = (os.getenv('RELEASEPLAN_LOCAL_ADMIN_PASSWORD') or '').strip()
    return username == expected_username and password == expected_password


def verify_local_guest(username, password):
    expected_username = (os.getenv('RELEASEPLAN_LOCAL_GUEST_USERNAME') or '').strip()
    expected_password = (os.getenv('RELEASEPLAN_LOCAL_GUEST_PASSWORD') or '').strip()
    return username == expected_username and password == expected_password


def get_releaseplan_root_path():
    return (request.headers.get('X-Forwarded-Prefix') or '/releaseplan').rstrip('/') or '/releaseplan'


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


def require_admin():
    if can_edit():
        return None
    flash('当前账号只有只读权限')
    return redirect(url_for('index'))


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        mode = auth_mode()
        if mode == 'none':
            return view_func(*args, **kwargs)
        if get_current_user():
            return view_func(*args, **kwargs)
        if mode in {'local', 'hybrid'}:
            return redirect(url_for('local_login', next=request.full_path if request.query_string else request.path))
        return redirect(url_for('oauth_login', next=request.full_path if request.query_string else request.path))
    return wrapped


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
            'project_category', 'project_subcategory', 'project_complexity', 'planned_start_date',
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
        existing_requirement_columns = {row[1] for row in conn.execute("PRAGMA table_info(requirements)").fetchall()}
        if 'submitter' not in existing_requirement_columns:
            conn.execute("ALTER TABLE requirements ADD COLUMN submitter TEXT")
        conn.commit()


def normalize_project_row(row):
    return {
        "立项状态": (row.get("立项状态") or "").strip(),
        "管控灶": (row.get("管控灶") or "").strip(),
        "投资主体": (row.get("投资主体") or "").strip(),
        "项目编码": (row.get("项目编码") or "").strip(),
        "项目名称": (row.get("项目名称") or "").strip(),
        "项目描述": (row.get("项目描述") or "").strip(),
        "项目大类": (row.get("项目大类") or "").strip(),
        "项目子类": (row.get("项目子类") or "").strip(),
        "项目复杂度": (row.get("项目复杂度") or "").strip(),
        "项目经理": (row.get("项目经理") or "").strip(),
        "计划启动日期": (row.get("计划启动日期") or "").strip(),
        "计划结束日期": (row.get("计划结束日期") or "").strip(),
        "工作量（人月）": (row.get("工作量（人月）") or row.get("工作量(人月)") or row.get("工作量") or "").strip(),
        "研发费用预算（w）": (row.get("研发费用预算（w）") or row.get("研发费用预算(w)") or "").strip(),
        "人力预算（自有）": (row.get("人力预算（自有）") or "").strip(),
        "人力预算（OD）": (row.get("人力预算（OD）") or "").strip(),
        "人力预算（TM）": (row.get("人力预算（TM）") or "").strip(),
    }


def normalize_feature_row(row):
    normalized = {
        "项目名称": (row.get("项目名称") or "").strip(),
        "五层部门": (row.get("五层部门") or "").strip(),
        "重点工作": (row.get("重点工作") or "").strip(),
        "关键特性": (row.get("关键特性") or "").strip(),
        "L4服务或服务组": (row.get("L4服务或服务组") or "").strip(),
        "服务交付PM": (row.get("服务交付PM") or "").strip(),
    }
    for month in MILESTONE_COLUMNS:
        normalized[month] = (row.get(month) or "").strip()
    return normalized


def project_row_to_db_tuple(row):
    return (
        row["立项状态"], row["管控灶"], row["投资主体"], row["项目编码"], row["项目名称"], row["项目描述"],
        row["项目大类"], row["项目子类"], row["项目复杂度"], row["项目经理"], row["计划启动日期"], row["计划结束日期"],
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
        "project_category", "project_subcategory", "project_complexity", "project_manager", "planned_start_date", "planned_end_date",
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


def build_project_roadmap(project_rows, feature_rows):
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

        feature = {
            "id": row.get("id"),
            "project_id": row.get("project_id"),
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


def seed_service_resources_if_empty():
    init_db()
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM service_resource_investment").fetchone()[0]
        if count > 0:
            return

    if SERVICE_RESOURCE_CSV_PATH.exists():
        with SERVICE_RESOURCE_CSV_PATH.open('rb') as f:
            class LocalFile:
                def read(self_inner):
                    return f.read()
            imported = import_service_resource_csv_file(LocalFile(), replace=True)
            if imported > 0:
                return

    seed_rows = [
        {"五层部门": "云平台部", "L4云服务": "容器云", "功能和用途简介": "提供容器编排与运行环境", "HC（自有）": "4", "HC（OD）": "1", "HC（TM）": "1", "HCS（自有）": "120", "HCS（OD）": "30", "HCS（TM）": "15"},
        {"五层部门": "云平台部", "L4云服务": "对象存储", "功能和用途简介": "提供对象存储与归档能力", "HC（自有）": "3", "HC（OD）": "1", "HC（TM）": "1", "HCS（自有）": "90", "HCS（OD）": "20", "HCS（TM）": "12"},
        {"五层部门": "基础设施部", "L4云服务": "云网络", "功能和用途简介": "提供 VPC、负载均衡与网络连接能力", "HC（自有）": "5", "HC（OD）": "1", "HC（TM）": "1", "HCS（自有）": "140", "HCS（OD）": "35", "HCS（TM）": "18"},
    ]
    import_service_resource_rows([normalize_service_resource_row(row) for row in seed_rows], replace=True)


def oauth_authorize_url():
    return os.getenv('RELEASEPLAN_OAUTH_AUTHORIZE_URL', '').strip()


def oauth_token_url():
    return os.getenv('RELEASEPLAN_OAUTH_TOKEN_URL', '').strip()


def oauth_userinfo_url():
    return os.getenv('RELEASEPLAN_OAUTH_USERINFO_URL', '').strip()


def oauth_client_id():
    return os.getenv('RELEASEPLAN_OAUTH_CLIENT_ID', '').strip()


def oauth_client_secret():
    return os.getenv('RELEASEPLAN_OAUTH_CLIENT_SECRET', '').strip()


def oauth_scope():
    return os.getenv('RELEASEPLAN_OAUTH_SCOPE', 'openid profile email').strip()


def oauth_redirect_uri():
    configured = os.getenv('RELEASEPLAN_OAUTH_REDIRECT_URI', '').strip()
    if configured:
        return configured
    prefix = (request.headers.get('X-Forwarded-Prefix') or '').strip()
    callback_path = '/auth/callback'
    if prefix:
        callback_path = f"{prefix.rstrip('/')}/auth/callback"
    return url_for('oauth_callback', _external=True, _scheme=request.headers.get('X-Forwarded-Proto', request.scheme)).replace('/auth/callback', callback_path, 1)


def build_oauth_user(userinfo):
    roles = userinfo.get('roles') or userinfo.get('role') or []
    if isinstance(roles, str):
        roles = [roles]
    normalized_roles = [str(role).strip().lower() for role in roles if str(role).strip()]
    email = (userinfo.get('email') or '').strip().lower()
    username = (userinfo.get('preferred_username') or userinfo.get('login') or userinfo.get('name') or '').strip().lower()

    admin_roles = {
        role.strip().lower()
        for role in (os.getenv('RELEASEPLAN_OAUTH_ADMIN_ROLES', 'admin,administrator,releaseplan-admin').split(','))
        if role.strip()
    }
    guest_roles = {
        role.strip().lower()
        for role in (os.getenv('RELEASEPLAN_OAUTH_GUEST_ROLES', 'guest,viewer,readonly,releaseplan-guest').split(','))
        if role.strip()
    }
    admin_emails = {
        item.strip().lower()
        for item in (os.getenv('RELEASEPLAN_OAUTH_ADMIN_EMAILS', '').split(','))
        if item.strip()
    }
    guest_emails = {
        item.strip().lower()
        for item in (os.getenv('RELEASEPLAN_OAUTH_GUEST_EMAILS', '').split(','))
        if item.strip()
    }
    admin_usernames = {
        item.strip().lower()
        for item in (os.getenv('RELEASEPLAN_OAUTH_ADMIN_USERNAMES', '').split(','))
        if item.strip()
    }
    guest_usernames = {
        item.strip().lower()
        for item in (os.getenv('RELEASEPLAN_OAUTH_GUEST_USERNAMES', '').split(','))
        if item.strip()
    }

    final_roles = []
    if set(normalized_roles) & admin_roles or (email and email in admin_emails) or (username and username in admin_usernames):
        final_roles = ['admin']
    elif set(normalized_roles) & guest_roles or (email and email in guest_emails) or (username and username in guest_usernames):
        final_roles = ['guest']
    else:
        default_role = (os.getenv('RELEASEPLAN_OAUTH_DEFAULT_ROLE') or 'guest').strip().lower()
        final_roles = ['admin'] if default_role == 'admin' else ['guest']

    return {
        'user_id': userinfo.get('sub') or userinfo.get('id') or userinfo.get('user_id') or '',
        'name': userinfo.get('name') or userinfo.get('preferred_username') or userinfo.get('login') or '',
        'email': userinfo.get('email') or '',
        'roles': final_roles,
        'raw': userinfo,
        'auth_type': 'oauth2',
    }


@app.route('/auth/login')
def oauth_login():
    if not oauth_enabled():
        return redirect(url_for('index'))
    state = secrets.token_urlsafe(24)
    next_url = normalize_next_url(request.args.get('next') or '/')
    session['oauth_state'] = state
    session['oauth_next'] = next_url
    query = {
        'client_id': oauth_client_id(),
        'redirect_uri': oauth_redirect_uri(),
        'response_type': 'code',
        'scope': oauth_scope(),
        'state': state,
    }
    return redirect(oauth_authorize_url() + ('&' if '?' in oauth_authorize_url() else '?') + urlencode(query))


@app.route('/auth/callback')
def oauth_callback():
    if not oauth_enabled():
        return redirect(url_for('index'))
    code = request.args.get('code', '').strip()
    state = request.args.get('state', '').strip()
    if not code:
        return Response('OAuth2 登录失败: 缺少 code', status=400)
    if not state or state != session.get('oauth_state'):
        return Response('OAuth2 登录失败: state 校验失败', status=400)

    token_resp = requests.post(
        oauth_token_url(),
        data={
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': oauth_redirect_uri(),
            'client_id': oauth_client_id(),
            'client_secret': oauth_client_secret(),
        },
        timeout=15,
    )
    if token_resp.status_code >= 400:
        return Response('OAuth2 登录失败: token 交换失败', status=400)
    token_data = token_resp.json()
    access_token = token_data.get('access_token')
    if not access_token:
        return Response('OAuth2 登录失败: 缺少 access_token', status=400)

    userinfo_resp = requests.get(
        oauth_userinfo_url(),
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=15,
    )
    if userinfo_resp.status_code >= 400:
        return Response('OAuth2 登录失败: 获取用户信息失败', status=400)
    userinfo = userinfo_resp.json()
    session.pop('oauth_state', None)
    session['oauth_user'] = build_oauth_user(userinfo)
    next_url = normalize_next_url(session.pop('oauth_next', None) or '/')
    return redirect(next_url)


@app.route('/auth/logout')
def oauth_logout():
    session.pop('oauth_user', None)
    session.pop('local_user', None)
    session.pop('oauth_state', None)
    session.pop('oauth_next', None)
    logout_url = os.getenv('RELEASEPLAN_OAUTH_LOGOUT_URL', '').strip()
    if logout_url and oauth_enabled():
        return redirect(logout_url)
    return redirect(url_for('index'))


@app.route('/login', methods=['GET', 'POST'])
def local_login():
    if auth_mode() != 'local':
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        next_url = normalize_next_url(request.form.get('next') or request.args.get('next') or '/')
        if verify_local_admin(username, password):
            session['local_user'] = {
                'user_id': username,
                'name': username,
                'email': '',
                'roles': ['admin'],
                'auth_type': 'local',
            }
            return redirect(next_url)
        if verify_local_guest(username, password):
            session['local_user'] = {
                'user_id': username,
                'name': username,
                'email': '',
                'roles': ['guest'],
                'auth_type': 'local',
            }
            return redirect(next_url)
        flash('账号或密码错误')
        return redirect(url_for('local_login', next=next_url))
    return render_template('local_login.html', next=normalize_next_url(request.args.get('next') or '/'), branding=get_branding(), **build_auth_context())


@app.route('/')
@login_required
def index():
    return render_template('home.html', branding=get_branding(), home_cards=get_home_cards(), **build_auth_context())


@app.route('/roadmap')
@login_required
def roadmap():
    project_rows = load_projects()
    feature_rows = load_project_features()
    project_groups = build_project_roadmap(project_rows, feature_rows)
    return render_template(
        'index.html',
        project_groups=project_groups,
        month_labels=MONTH_LABELS,
        quarters=QUARTERS,
        branding=get_branding(),
        **build_auth_context(),
    )


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings_page():
    denied = require_admin()
    if denied:
        return denied
    if request.method == 'POST':
        action = (request.form.get('action') or 'save_settings').strip()
        if action == 'run_backup_now':
            archive_path = build_backup_archive(backup_type='manual')
            flash(f'手动备份已完成：{archive_path}')
            return redirect(url_for('settings_page'))

        if action == 'restore_backup':
            backup_filename = (request.form.get('backup_filename') or '').strip()
            if not backup_filename:
                flash('请选择要恢复的备份')
                return redirect(url_for('settings_page'))
            restore_backup_archive(backup_filename)
            flash(f'备份已恢复：{backup_filename}')
            return redirect(url_for('settings_page'))

        if action == 'delete_backup':
            backup_filename = (request.form.get('backup_filename') or '').strip()
            if not backup_filename:
                flash('请选择要删除的备份')
                return redirect(url_for('settings_page'))
            delete_backup_archive(backup_filename)
            flash(f'备份已删除：{backup_filename}')
            return redirect(url_for('settings_page'))

        auto_backup_enabled = (request.form.get('auto_backup_enabled') or '').strip() == 'on'
        auto_backup_time = (request.form.get('auto_backup_time') or '03:00').strip() or '03:00'
        backup_dir = (request.form.get('backup_dir') or '').strip() or str(BASE_DIR / 'backups')

        updates = {
            "RELEASEPLAN_HOME_TITLE": (request.form.get('home_title') or '').strip() or 'ReleasePlan',
            "RELEASEPLAN_BROWSER_TITLE": (request.form.get('browser_title') or '').strip() or 'ReleasePlan 入口',
            "RELEASEPLAN_THEME": (request.form.get('theme') or 'ios-light').strip() or 'ios-light',
            "RELEASEPLAN_CARD_1_TITLE": (request.form.get('card_1_title') or '').strip() or '项目视图',
            "RELEASEPLAN_CARD_2_TITLE": (request.form.get('card_2_title') or '').strip() or '关键特性视图',
            "RELEASEPLAN_CARD_3_TITLE": (request.form.get('card_3_title') or '').strip() or '投资视图',
            "RELEASEPLAN_CARD_4_TITLE": (request.form.get('card_4_title') or '').strip() or '资源视图',
            "RELEASEPLAN_CARD_5_TITLE": (request.form.get('card_5_title') or '').strip() or '云服务视图',
            "RELEASEPLAN_CARD_1_KEY": (request.form.get('card_1_key') or 'department-pipeline-load').strip() or 'department-pipeline-load',
            "RELEASEPLAN_CARD_2_KEY": (request.form.get('card_2_key') or 'roadmap').strip() or 'roadmap',
            "RELEASEPLAN_CARD_3_KEY": (request.form.get('card_3_key') or 'department-budget-resource').strip() or 'department-budget-resource',
            "RELEASEPLAN_CARD_4_KEY": (request.form.get('card_4_key') or 'project-budget-resource').strip() or 'project-budget-resource',
            "RELEASEPLAN_CARD_5_KEY": (request.form.get('card_5_key') or 'cloud-service-view').strip() or 'cloud-service-view',
            "RELEASEPLAN_BACKUP_DIR": backup_dir,
            "RELEASEPLAN_AUTO_BACKUP_ENABLED": 'true' if auto_backup_enabled else 'false',
            "RELEASEPLAN_AUTO_BACKUP_TIME": auto_backup_time,
            "RELEASEPLAN_AUTO_BACKUP_SCHEDULE": f"{auto_backup_time.split(':')[1]} {auto_backup_time.split(':')[0]} * * *" if ':' in auto_backup_time else '0 3 * * *',
        }
        save_env_settings(updates)
        os.environ.update(updates)
        write_auto_backup_crontab(auto_backup_enabled, auto_backup_time)
        flash('系统设置已保存并立即生效')
        return redirect(url_for('settings_page'))
    return render_template(
        'settings.html',
        branding=get_branding(),
        home_cards=get_home_cards(),
        backup_config=get_backup_config(),
        backup_history=list_backup_history(),
        **build_auth_context(),
    )


@app.route('/requirements', methods=['GET', 'POST'])
@login_required
def requirements_page():
    example_text = "示例：项目视图增加按项目经理筛选，并支持导出当前筛选结果为 Excel。"
    if request.method == 'POST':
        requirement_text = (request.form.get('requirement_text') or '').strip()
        if not requirement_text:
            flash('请输入需求内容')
            return redirect(url_for('requirements_page'))
        submit_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        current_user = get_current_user()
        submitter = current_user.get('name') if isinstance(current_user, dict) else None
        with get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO requirements (requirement_content, submit_date, status, submitter) VALUES (?, ?, 'open', ?)",
                (requirement_text, submit_date, submitter)
            )
            requirement_id = cursor.lastrowid
            requirement_code = f"REQ{requirement_id:04d}"
            conn.execute("UPDATE requirements SET requirement_code = ? WHERE id = ?", (requirement_code, requirement_id))
            conn.commit()
        flash('需求已提交')
        return redirect(url_for('requirements_page'))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, requirement_code, requirement_content, submit_date, close_date, status, submitter FROM requirements ORDER BY id DESC"
        ).fetchall()
    requirements = [dict(row) for row in rows]
    return render_template(
        'requirements.html',
        branding=get_branding(),
        example_text=example_text,
        **build_auth_context(),
        requirements=requirements,
    )


@app.route('/requirements/<int:requirement_id>/status', methods=['POST'])
@login_required
def requirement_status_update(requirement_id):
    denied = require_admin()
    if denied:
        return denied
    status = (request.form.get('status') or 'open').strip().lower()
    if status not in {'open', 'closed'}:
        status = 'open'
    close_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S') if status == 'closed' else None
    with get_conn() as conn:
        conn.execute(
            "UPDATE requirements SET status = ?, close_date = ? WHERE id = ?",
            (status, close_date, requirement_id)
        )
        conn.commit()
    flash('需求状态已更新')
    return redirect(url_for('requirements_page'))


@app.route('/views/<view_key>')
@login_required
def view_placeholder(view_key):
    if view_key == 'cloud-service-view':
        seed_service_resources_if_empty()
        department_keyword = (request.args.get('department') or '').strip()
        service_keyword = (request.args.get('service') or '').strip()
        rows = load_service_resources()
        filter_options = get_service_resource_filter_options(rows)
        filtered_rows = filter_service_resources(rows, department_keyword=department_keyword, service_keyword=service_keyword)
        summary = build_service_resource_summary(filtered_rows)
        return render_template(
            'cloud_service_view.html',
            records=filtered_rows,
            summary=summary,
            filters={
                'department': department_keyword,
                'service': service_keyword,
            },
            filter_options=filter_options,
            auth_mode=auth_mode(),
            current_user=get_current_user(),
        )

    if view_key == 'department-pipeline-load':
        project_rows = load_projects()
        sorted_projects = sorted(
            project_rows,
            key=lambda row: (-parse_workload_value(row.get('workload_person_month')), (row.get('project_name') or '').strip(), row.get('id') or 0),
        )
        now = datetime.utcnow()
        display_year = now.year
        today_marker_percent = ((now.month - 1) + 0.5) / 12 * 100 if now.year == display_year else None
        return render_template(
            'project_view.html',
            projects=sorted_projects,
            gantt_projects=build_project_gantt(project_rows, display_year),
            month_labels=MONTH_LABELS,
            quarters=QUARTERS,
            display_year=display_year,
            today_marker_percent=today_marker_percent,
            auth_mode=auth_mode(),
            current_user=get_current_user(),
        )

    view_map = {
        'department-budget-resource': {
            'title': '投资视图',
            'description': '查看投资维度的整体情况、投入分布与汇总信息。',
        },
        'department-pipeline-load': {
            'title': '项目视图',
            'description': '查看项目维度的整体情况、排期分布与重点内容。',
        },
        'project-budget-resource': {
            'title': '资源视图',
            'description': '查看项目维度的预算与资源分布信息。',
        },
    }
    view_config = view_map.get(view_key)
    if not view_config:
        return redirect(url_for('index'))
    return render_template('view_placeholder.html', **view_config, **build_auth_context())


@app.route('/admin/projects/new', methods=['GET', 'POST'])
@login_required
def admin_project_new():
    denied = require_admin()
    if denied:
        return denied
    if request.method == 'POST':
        data = form_to_project_data(request.form)
        sql_columns = [
            "project_status", "control_gate", "investment_subject", "project_code", "project_name", "project_description",
            "project_category", "project_subcategory", "project_complexity", "project_manager", "planned_start_date", "planned_end_date",
            "workload_person_month", "rd_budget_w", "headcount_budget_self_owned", "headcount_budget_od", "headcount_budget_tm"
        ]
        values = [data[key] for key in sql_columns]
        placeholders = ", ".join(["?"] * len(values))
        with get_conn() as conn:
            conn.execute(
                f"INSERT INTO projects ({', '.join(sql_columns)}) VALUES ({placeholders})",
                values,
            )
            conn.commit()
        return redirect(url_for('view_placeholder', view_key='department-pipeline-load'))
    return render_template('project_form.html', project={}, mode='new', **build_auth_context())


@app.route('/admin/projects/<int:project_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_project_edit(project_id):
    denied = require_admin()
    if denied:
        return denied
    project = load_project(project_id)
    if not project:
        return redirect(url_for('view_placeholder', view_key='department-pipeline-load'))
    if request.method == 'POST':
        data = form_to_project_data(request.form)
        set_clause = [
            "project_status = ?",
            "control_gate = ?",
            "investment_subject = ?",
            "project_code = ?",
            "project_name = ?",
            "project_description = ?",
            "project_category = ?",
            "project_subcategory = ?",
            "project_complexity = ?",
            "project_manager = ?",
            "planned_start_date = ?",
            "planned_end_date = ?",
            "workload_person_month = ?",
            "rd_budget_w = ?",
            "headcount_budget_self_owned = ?",
            "headcount_budget_od = ?",
            "headcount_budget_tm = ?",
            "updated_at = CURRENT_TIMESTAMP"
        ]
        values = [data[key] for key in [
            "project_status", "control_gate", "investment_subject", "project_code", "project_name", "project_description",
            "project_category", "project_subcategory", "project_complexity", "project_manager", "planned_start_date", "planned_end_date",
            "workload_person_month", "rd_budget_w", "headcount_budget_self_owned", "headcount_budget_od", "headcount_budget_tm"
        ]] + [project_id]
        with get_conn() as conn:
            conn.execute(
                f"UPDATE projects SET {', '.join(set_clause)} WHERE id = ?",
                values,
            )
            conn.commit()
        return redirect(url_for('view_placeholder', view_key='department-pipeline-load'))
    return render_template('project_form.html', project=project, mode='edit', **build_auth_context())


@app.route('/admin/projects/<int:project_id>/delete', methods=['POST'])
@login_required
def admin_project_delete(project_id):
    denied = require_admin()
    if denied:
        return denied
    with get_conn() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
    return redirect(url_for('view_placeholder', view_key='department-pipeline-load'))


@app.route('/admin/features/new', methods=['GET', 'POST'])
@login_required
def admin_feature_new():
    denied = require_admin()
    if denied:
        return denied
    project_options = get_project_options()
    if request.method == 'POST':
        data = form_to_feature_data(request.form)
        with get_conn() as conn:
            project_row = conn.execute("SELECT id, project_name, project_code FROM projects WHERE project_name = ? ORDER BY id LIMIT 1", (data['project_name'],)).fetchone()
            if not project_row:
                flash('请选择项目表中已有的项目名称')
                return render_template('feature_form.html', feature=data, months=MILESTONE_COLUMNS, mode='new', project_options=project_options, **build_auth_context())
            project_id = project_row['id']
            feature_month_columns = ', '.join([f'"{m}"' for m in MILESTONE_COLUMNS])
            feature_month_placeholders = ', '.join(['?'] * len(MILESTONE_COLUMNS))
            conn.execute(
                f"INSERT INTO project_features (project_id, project_name, five_level_department, focus_work, feature_name, service_group, delivery_pm, {feature_month_columns}) VALUES (?, ?, ?, ?, ?, ?, ?, {feature_month_placeholders})",
                [project_id, project_row['project_name'], data['five_level_department'], data['focus_work'], data['feature_name'], data['service_group'], data['delivery_pm'], *[data[m] for m in MILESTONE_COLUMNS]],
            )
            conn.commit()
        return redirect(url_for('roadmap'))
    return render_template('feature_form.html', feature={}, months=MILESTONE_COLUMNS, mode='new', project_options=project_options, **build_auth_context())


@app.route('/admin/features/<int:feature_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_feature_edit(feature_id):
    denied = require_admin()
    if denied:
        return denied
    feature = load_project_feature(feature_id)
    if not feature:
        return redirect(url_for('roadmap'))
    project_options = get_project_options()
    if request.method == 'POST':
        data = form_to_feature_data(request.form)
        with get_conn() as conn:
            project_row = conn.execute("SELECT id, project_name, project_code FROM projects WHERE project_name = ? ORDER BY id LIMIT 1", (data['project_name'],)).fetchone()
            if not project_row:
                flash('请选择项目表中已有的项目名称')
                return render_template('feature_form.html', feature=data, months=MILESTONE_COLUMNS, mode='edit', project_options=project_options, **build_auth_context())
            project_id = project_row['id']
            set_clause = [
                "project_id = ?",
                "project_name = ?",
                "five_level_department = ?",
                "focus_work = ?",
                "feature_name = ?",
                "service_group = ?",
                "delivery_pm = ?",
            ] + [f'\"{month}\" = ?' for month in MILESTONE_COLUMNS] + ["updated_at = CURRENT_TIMESTAMP"]
            values = [project_id, project_row['project_name'], data['five_level_department'], data['focus_work'], data['feature_name'], data['service_group'], data['delivery_pm'], *[data[m] for m in MILESTONE_COLUMNS], feature_id]
            conn.execute(f"UPDATE project_features SET {', '.join(set_clause)} WHERE id = ?", values)
            conn.commit()
        return redirect(url_for('roadmap'))
    feature = dict(feature)
    selected_project = next((item for item in project_options if item['project_name'] == feature.get('project_name')), None)
    feature['project_code'] = selected_project['project_code'] if selected_project else ''
    return render_template('feature_form.html', feature=feature, months=MILESTONE_COLUMNS, mode='edit', project_options=project_options, **build_auth_context())


@app.route('/admin/projects/import-csv', methods=['POST'])
@login_required
def admin_projects_import_csv():
    denied = require_admin()
    if denied:
        return denied
    file = request.files.get('csv_file')
    if file and file.filename:
        import_project_csv_file(file, replace=True)
    return redirect(url_for('roadmap'))


@app.route('/admin/projects/template-csv')
@login_required
def admin_projects_template_csv():
    if PROJECT_CSV_PATH.exists():
        content = PROJECT_CSV_PATH.read_text(encoding='utf-8')
    else:
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(PROJECT_ALL_COLUMNS)
        content = output.getvalue()
    response = Response('\ufeff' + content, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('关键特性描述_导出模板.csv')}"
    return response


@app.route('/admin/projects/export-csv')
@login_required
def admin_projects_export_csv():
    rows = load_projects()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(PROJECT_ALL_COLUMNS)
    for row in rows:
        writer.writerow([
            row.get('project_status', ''),
            row.get('control_gate', ''),
            row.get('investment_subject', ''),
            row.get('project_code', ''),
            row.get('project_name', ''),
            row.get('project_description', ''),
            row.get('project_category', ''),
            row.get('project_subcategory', ''),
            row.get('project_complexity', ''),
            row.get('project_manager', ''),
            row.get('planned_start_date', ''),
            row.get('planned_end_date', ''),
            row.get('workload_person_month', ''),
            row.get('rd_budget_w', ''),
            row.get('headcount_budget_self_owned', ''),
            row.get('headcount_budget_od', ''),
            row.get('headcount_budget_tm', ''),
        ])
    response = Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('关键特性描述_导出数据.csv')}"
    return response


@app.route('/admin/service-resources')
@login_required
def admin_service_resources():
    seed_service_resources_if_empty()
    rows = load_service_resources()
    return render_template('service_resource_list.html', records=rows, **build_auth_context())


@app.route('/admin/service-resources/new', methods=['GET', 'POST'])
@login_required
def admin_service_resource_new():
    denied = require_admin()
    if denied:
        return denied
    if request.method == 'POST':
        data = form_to_service_resource_data(request.form)
        with get_conn() as conn:
            conn.execute(
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
                (
                    data['five_level_department'], data['l4_cloud_service'], data['function_description'],
                    data['summary_self_owned'], data['summary_od'], data['summary_tm'],
                    data['hc_self_owned'], data['hc_od'], data['hc_tm'],
                    data['hcs_self_owned'], data['hcs_od'], data['hcs_tm'],
                ),
            )
            conn.commit()
        return redirect(url_for('admin_service_resources'))
    return render_template('service_resource_form.html', record={}, mode='new', **build_auth_context())


@app.route('/admin/service-resources/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_service_resource_edit(record_id):
    denied = require_admin()
    if denied:
        return denied
    record = load_service_resource(record_id)
    return_to = request.args.get('return_to') or '/views/cloud-service-view'
    if not record:
        return redirect(return_to)
    if request.method == 'POST':
        data = form_to_service_resource_data(request.form)
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE service_resource_investment
                SET five_level_department = ?,
                    l4_cloud_service = ?,
                    function_description = ?,
                    summary_self_owned = ?,
                    summary_od = ?,
                    summary_tm = ?,
                    hc_self_owned = ?,
                    hc_od = ?,
                    hc_tm = ?,
                    hcs_self_owned = ?,
                    hcs_od = ?,
                    hcs_tm = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    data['five_level_department'], data['l4_cloud_service'], data['function_description'],
                    data['summary_self_owned'], data['summary_od'], data['summary_tm'],
                    data['hc_self_owned'], data['hc_od'], data['hc_tm'],
                    data['hcs_self_owned'], data['hcs_od'], data['hcs_tm'], record_id,
                ),
            )
            conn.commit()
        return redirect(return_to)
    return render_template('service_resource_form.html', record=record, mode='edit', return_to=return_to, **build_auth_context())


@app.route('/admin/service-resources/<int:record_id>/delete', methods=['POST'])
@login_required
def admin_service_resource_delete(record_id):
    denied = require_admin()
    if denied:
        return denied
    with get_conn() as conn:
        conn.execute("DELETE FROM service_resource_investment WHERE id = ?", (record_id,))
        conn.commit()
    return redirect(url_for('admin_service_resources'))


@app.route('/admin/service-resources/import-csv', methods=['POST'])
@login_required
def admin_service_resources_import_csv():
    denied = require_admin()
    if denied:
        return denied
    file = request.files.get('csv_file')
    if file and file.filename:
        import_service_resource_csv_file(file, replace=True)
    return redirect(url_for('view_placeholder', view_key='cloud-service-view'))


@app.route('/admin/service-resources/template-csv')
@login_required
def admin_service_resources_template_csv():
    content = SERVICE_RESOURCE_CSV_PATH.read_text(encoding='utf-8') if SERVICE_RESOURCE_CSV_PATH.exists() else "五层部门,L4云服务,功能和用途简介,HC（自有）,HC（OD）,HC（TM）,HCS（自有）,HCS（OD）,HCS（TM）\n"
    response = Response('\ufeff' + content, mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('service_resource_investment_template.csv')}"
    return response


@app.route('/admin/service-resources/export-csv')
@login_required
def admin_service_resources_export_csv():
    rows = load_service_resources()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['五层部门', 'L4云服务', '功能和用途简介', 'HC（自有）', 'HC（OD）', 'HC（TM）', 'HCS（自有）', 'HCS（OD）', 'HCS（TM）', '汇总（自有）', '汇总（OD）', '汇总（TM）'])
    for row in rows:
        writer.writerow([
            row.get('five_level_department', ''),
            row.get('l4_cloud_service', ''),
            row.get('function_description', ''),
            row.get('hc_self_owned', ''),
            row.get('hc_od', ''),
            row.get('hc_tm', ''),
            row.get('hcs_self_owned', ''),
            row.get('hcs_od', ''),
            row.get('hcs_tm', ''),
            row.get('summary_self_owned', ''),
            row.get('summary_od', ''),
            row.get('summary_tm', ''),
        ])
    response = Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('service_resource_investment_export.csv')}"
    return response


@app.route('/views/cloud-service-view/<int:record_id>/edit', methods=['POST'])
@login_required
def cloud_service_view_edit(record_id):
    denied = require_admin()
    if denied:
        return denied
    data = form_to_service_resource_data(request.form)
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE service_resource_investment
            SET five_level_department = ?,
                l4_cloud_service = ?,
                function_description = ?,
                summary_self_owned = ?,
                summary_od = ?,
                summary_tm = ?,
                hc_self_owned = ?,
                hc_od = ?,
                hc_tm = ?,
                hcs_self_owned = ?,
                hcs_od = ?,
                hcs_tm = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                data['five_level_department'], data['l4_cloud_service'], data['function_description'],
                data['summary_self_owned'], data['summary_od'], data['summary_tm'],
                data['hc_self_owned'], data['hc_od'], data['hc_tm'],
                data['hcs_self_owned'], data['hcs_od'], data['hcs_tm'], record_id,
            ),
        )
        conn.commit()
    return redirect(url_for('view_placeholder', view_key='cloud-service-view'))


if __name__ == '__main__':
    import sys

    if '--backup-now' in sys.argv:
        backup_type = 'auto' if '--backup-type' in sys.argv and 'auto' in sys.argv else 'manual'
        archive_path = build_backup_archive(backup_type=backup_type)
        print(archive_path)
        raise SystemExit(0)

    app.run(host='0.0.0.0', port=5010, debug=False)
