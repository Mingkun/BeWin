from flask import Flask, redirect, render_template, request, session, url_for, Response, flash
from io import StringIO
from urllib.parse import quote
from werkzeug.middleware.proxy_fix import ProxyFix
import csv
import json
import os
import sqlite3
from functools import wraps
from pathlib import Path

try:
    from onelogin.saml2.auth import OneLogin_Saml2_Auth
    from onelogin.saml2.settings import OneLogin_Saml2_Settings
except Exception:
    OneLogin_Saml2_Auth = None
    OneLogin_Saml2_Settings = None

BASE_DIR = Path(__file__).resolve().parents[1]
PROJECT_CSV_PATH = BASE_DIR / "docs" / "project_table.csv"
FEATURE_CSV_PATH = BASE_DIR / "docs" / "feature_table.csv"
DB_PATH = BASE_DIR / "data" / "releaseplan.db"
SAML_SETTINGS_PATH = Path(os.getenv("RELEASEPLAN_SAML_SETTINGS", BASE_DIR / "saml_settings.json"))
SERVICE_RESOURCE_CSV_PATH = BASE_DIR / "docs" / "service_resource_investment.csv"
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
            "key": "roadmap",
            "title": os.getenv("RELEASEPLAN_CARD_1_TITLE", "关键特性视图"),
            "desc": "查看按项目切换的关键特性 roadmap 视图。",
            "href": url_for('roadmap'),
        },
        {
            "key": "department-budget-resource",
            "title": os.getenv("RELEASEPLAN_CARD_2_TITLE", "投资视图"),
            "desc": "查看部门视角的预算与资源统计信息。",
            "href": url_for('view_placeholder', view_key='department-budget-resource'),
        },
        {
            "key": "project-budget-resource",
            "title": os.getenv("RELEASEPLAN_CARD_3_TITLE", "资源视图"),
            "desc": "查看项目维度的预算与资源分布信息。",
            "href": url_for('view_placeholder', view_key='project-budget-resource'),
        },
        {
            "key": "department-pipeline-load",
            "title": os.getenv("RELEASEPLAN_CARD_4_TITLE", "项目视图"),
            "desc": "查看部门管道容量、排期与负载情况。",
            "href": url_for('view_placeholder', view_key='department-pipeline-load'),
        },
        {
            "key": "cloud-service-view",
            "title": os.getenv("RELEASEPLAN_CARD_5_TITLE", "云服务视图"),
            "desc": "查看云服务相关项目与规划信息。",
            "href": url_for('view_placeholder', view_key='cloud-service-view'),
        },
    ]
    preferred_order = [
        os.getenv("RELEASEPLAN_CARD_1_KEY", "roadmap"),
        os.getenv("RELEASEPLAN_CARD_2_KEY", "department-budget-resource"),
        os.getenv("RELEASEPLAN_CARD_3_KEY", "project-budget-resource"),
        os.getenv("RELEASEPLAN_CARD_4_KEY", "department-pipeline-load"),
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
        "RELEASEPLAN_SAML_ENABLED",
        "RELEASEPLAN_SAML_SETTINGS",
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


def saml_enabled():
    return os.getenv("RELEASEPLAN_SAML_ENABLED", "false").lower() == "true"


def load_saml_settings():
    if not SAML_SETTINGS_PATH.exists():
        return None
    with SAML_SETTINGS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def prepare_flask_request(req):
    return {
        'https': 'on' if req.headers.get('X-Forwarded-Proto', req.scheme) == 'https' else 'off',
        'http_host': req.headers.get('X-Forwarded-Host', req.host),
        'server_port': req.headers.get('X-Forwarded-Port', req.host.split(':')[-1] if ':' in req.host else ('443' if req.scheme == 'https' else '80')),
        'script_name': req.path,
        'get_data': req.args.copy(),
        'post_data': req.form.copy(),
        'query_string': req.query_string,
    }


def get_saml_auth(req):
    settings = load_saml_settings()
    if not settings or OneLogin_Saml2_Auth is None:
        return None
    return OneLogin_Saml2_Auth(prepare_flask_request(req), old_settings=settings)


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not saml_enabled():
            return view_func(*args, **kwargs)
        if session.get('saml_user'):
            return view_func(*args, **kwargs)
        return redirect(url_for('saml_login', next=request.path))
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


@app.route('/saml/login')
def saml_login():
    if not saml_enabled():
        return redirect(url_for('index'))
    auth = get_saml_auth(request)
    if auth is None:
        return Response('SAML 未正确配置', status=500)
    next_url = request.args.get('next') or '/'
    return redirect(auth.login(return_to=next_url))


@app.route('/saml/acs', methods=['POST'])
def saml_acs():
    if not saml_enabled():
        return redirect(url_for('index'))
    auth = get_saml_auth(request)
    if auth is None:
        return Response('SAML 未正确配置', status=500)
    auth.process_response()
    errors = auth.get_errors()
    if errors:
        return Response('SAML 登录失败: ' + '; '.join(errors), status=400)
    if not auth.is_authenticated():
        return Response('SAML 登录失败: 用户未认证', status=401)

    session['saml_user'] = {
        'name_id': auth.get_nameid(),
        'attributes': auth.get_attributes(),
    }
    relay_state = request.form.get('RelayState') or '/'
    return redirect(relay_state)


@app.route('/saml/logout')
def saml_logout():
    session.pop('saml_user', None)
    return redirect(url_for('index'))


@app.route('/saml/metadata')
def saml_metadata():
    if not saml_enabled():
        return Response('SAML 未启用', status=404)
    settings = load_saml_settings()
    if not settings or OneLogin_Saml2_Settings is None:
        return Response('SAML 未正确配置', status=500)
    saml_settings = OneLogin_Saml2_Settings(settings=settings)
    metadata = saml_settings.get_sp_metadata()
    errors = saml_settings.validate_metadata(metadata)
    if errors:
        return Response('metadata 生成失败: ' + '; '.join(errors), status=500)
    return Response(metadata, mimetype='text/xml')


@app.route('/')
@login_required
def index():
    return render_template('home.html', saml_enabled=saml_enabled(), saml_user=session.get('saml_user'), branding=get_branding(), home_cards=get_home_cards())


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
        saml_enabled=saml_enabled(),
        saml_user=session.get('saml_user'),
        branding=get_branding(),
    )


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings_page():
    if request.method == 'POST':
        updates = {
            "RELEASEPLAN_HOME_TITLE": (request.form.get('home_title') or '').strip() or 'ReleasePlan',
            "RELEASEPLAN_BROWSER_TITLE": (request.form.get('browser_title') or '').strip() or 'ReleasePlan 入口',
            "RELEASEPLAN_THEME": (request.form.get('theme') or 'ios-light').strip() or 'ios-light',
            "RELEASEPLAN_CARD_1_TITLE": (request.form.get('card_1_title') or '').strip() or '关键特性视图',
            "RELEASEPLAN_CARD_2_TITLE": (request.form.get('card_2_title') or '').strip() or '投资视图',
            "RELEASEPLAN_CARD_3_TITLE": (request.form.get('card_3_title') or '').strip() or '资源视图',
            "RELEASEPLAN_CARD_4_TITLE": (request.form.get('card_4_title') or '').strip() or '项目视图',
            "RELEASEPLAN_CARD_5_TITLE": (request.form.get('card_5_title') or '').strip() or '云服务视图',
            "RELEASEPLAN_CARD_1_KEY": (request.form.get('card_1_key') or 'roadmap').strip() or 'roadmap',
            "RELEASEPLAN_CARD_2_KEY": (request.form.get('card_2_key') or 'department-budget-resource').strip() or 'department-budget-resource',
            "RELEASEPLAN_CARD_3_KEY": (request.form.get('card_3_key') or 'project-budget-resource').strip() or 'project-budget-resource',
            "RELEASEPLAN_CARD_4_KEY": (request.form.get('card_4_key') or 'department-pipeline-load').strip() or 'department-pipeline-load',
            "RELEASEPLAN_CARD_5_KEY": (request.form.get('card_5_key') or 'cloud-service-view').strip() or 'cloud-service-view',
        }
        save_env_settings(updates)
        os.environ.update(updates)
        flash('设置已保存并立即生效')
        return redirect(url_for('settings_page'))
    return render_template('settings.html', branding=get_branding(), home_cards=get_home_cards(), saml_enabled=saml_enabled(), saml_user=session.get('saml_user'))


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
            saml_enabled=saml_enabled(),
            saml_user=session.get('saml_user'),
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
            'description': '查看资源维度的整体情况、投入分布与统计信息。',
        },
    }
    view_config = view_map.get(view_key)
    if not view_config:
        return redirect(url_for('index'))
    return render_template('view_placeholder.html', saml_enabled=saml_enabled(), saml_user=session.get('saml_user'), **view_config)


@app.route('/admin/projects')
@login_required
def admin_projects():
    rows = load_projects()
    return render_template('admin_projects.html', projects=rows, months=MILESTONE_COLUMNS, saml_enabled=saml_enabled(), saml_user=session.get('saml_user'))


@app.route('/admin/projects/new', methods=['GET', 'POST'])
@login_required
def admin_project_new():
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
        return redirect(url_for('admin_projects'))
    return render_template('project_form.html', project={}, mode='new', saml_enabled=saml_enabled(), saml_user=session.get('saml_user'))


@app.route('/admin/projects/<int:project_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_project_edit(project_id):
    project = load_project(project_id)
    if not project:
        return redirect(url_for('admin_projects'))
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
        return redirect(url_for('admin_projects'))
    return render_template('project_form.html', project=project, mode='edit', saml_enabled=saml_enabled(), saml_user=session.get('saml_user'))


@app.route('/admin/projects/<int:project_id>/delete', methods=['POST'])
@login_required
def admin_project_delete(project_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
    return redirect(url_for('admin_projects'))


@app.route('/admin/features/new', methods=['GET', 'POST'])
@login_required
def admin_feature_new():
    project_options = get_project_options()
    if request.method == 'POST':
        data = form_to_feature_data(request.form)
        with get_conn() as conn:
            project_row = conn.execute("SELECT id, project_name, project_code FROM projects WHERE project_name = ? ORDER BY id LIMIT 1", (data['project_name'],)).fetchone()
            if not project_row:
                flash('请选择项目表中已有的项目名称')
                return render_template('feature_form.html', feature=data, months=MILESTONE_COLUMNS, mode='new', project_options=project_options, saml_enabled=saml_enabled(), saml_user=session.get('saml_user'))
            project_id = project_row['id']
            feature_month_columns = ', '.join([f'"{m}"' for m in MILESTONE_COLUMNS])
            feature_month_placeholders = ', '.join(['?'] * len(MILESTONE_COLUMNS))
            conn.execute(
                f"INSERT INTO project_features (project_id, project_name, five_level_department, focus_work, feature_name, service_group, delivery_pm, {feature_month_columns}) VALUES (?, ?, ?, ?, ?, ?, ?, {feature_month_placeholders})",
                [project_id, project_row['project_name'], data['five_level_department'], data['focus_work'], data['feature_name'], data['service_group'], data['delivery_pm'], *[data[m] for m in MILESTONE_COLUMNS]],
            )
            conn.commit()
        return redirect(url_for('roadmap'))
    return render_template('feature_form.html', feature={}, months=MILESTONE_COLUMNS, mode='new', project_options=project_options, saml_enabled=saml_enabled(), saml_user=session.get('saml_user'))


@app.route('/admin/features/<int:feature_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_feature_edit(feature_id):
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
                return render_template('feature_form.html', feature=data, months=MILESTONE_COLUMNS, mode='edit', project_options=project_options, saml_enabled=saml_enabled(), saml_user=session.get('saml_user'))
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
    return render_template('feature_form.html', feature=feature, months=MILESTONE_COLUMNS, mode='edit', project_options=project_options, saml_enabled=saml_enabled(), saml_user=session.get('saml_user'))


@app.route('/admin/projects/import-csv', methods=['POST'])
@login_required
def admin_projects_import_csv():
    file = request.files.get('csv_file')
    if file and file.filename:
        import_project_csv_file(file, replace=True)
    return redirect(url_for('admin_projects'))


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
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('project_table_template.csv')}"
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
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote('project_table_export.csv')}"
    return response


@app.route('/admin/service-resources')
@login_required
def admin_service_resources():
    seed_service_resources_if_empty()
    rows = load_service_resources()
    return render_template('service_resource_list.html', records=rows, saml_enabled=saml_enabled(), saml_user=session.get('saml_user'))


@app.route('/admin/service-resources/new', methods=['GET', 'POST'])
@login_required
def admin_service_resource_new():
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
    return render_template('service_resource_form.html', record={}, mode='new', saml_enabled=saml_enabled(), saml_user=session.get('saml_user'))


@app.route('/admin/service-resources/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_service_resource_edit(record_id):
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
    return render_template('service_resource_form.html', record=record, mode='edit', return_to=return_to, saml_enabled=saml_enabled(), saml_user=session.get('saml_user'))


@app.route('/admin/service-resources/<int:record_id>/delete', methods=['POST'])
@login_required
def admin_service_resource_delete(record_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM service_resource_investment WHERE id = ?", (record_id,))
        conn.commit()
    return redirect(url_for('admin_service_resources'))


@app.route('/admin/service-resources/import-csv', methods=['POST'])
@login_required
def admin_service_resources_import_csv():
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
    app.run(host='0.0.0.0', port=5010, debug=False)
