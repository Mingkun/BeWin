from flask import Flask, redirect, render_template, request, url_for
import csv
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
CSV_PATH = BASE_DIR / "docs" / "project_table.csv"
DB_PATH = BASE_DIR / "data" / "releaseplan.db"
MILESTONE_COLUMNS = [
    "1/31", "2/28", "3/31", "4/30", "5/31", "6/30",
    "7/31", "8/31", "9/30", "10/31", "11/30", "12/31"
]
STAGES = ["启动开发", "实现", "集成测试", "上线交付"]
TEXT_COLUMNS = ["项目名称", "项目经理", "工作量（人月）", "重点工作", "关键特性", "L4服务或服务组", "服务交付PM"]
ALL_COLUMNS = TEXT_COLUMNS + MILESTONE_COLUMNS
DB_TO_LABEL = {
    "project_name": "项目名称",
    "project_manager": "项目经理",
    "workload_person_month": "工作量（人月）",
    "focus_work": "重点工作",
    "feature_name": "关键特性",
    "service_group": "L4服务或服务组",
    "delivery_pm": "服务交付PM",
}
LABEL_TO_DB = {v: k for k, v in DB_TO_LABEL.items()}

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))


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
                project_name TEXT,
                project_manager TEXT,
                workload_person_month TEXT,
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
        conn.commit()


def normalize_row(row):
    normalized = {
        "项目名称": (row.get("项目名称") or "").strip(),
        "项目经理": (row.get("项目经理") or "").strip(),
        "工作量（人月）": (row.get("工作量（人月）") or row.get("工作量(人月)") or row.get("工作量") or "").strip(),
        "重点工作": (row.get("重点工作") or "").strip(),
        "关键特性": (row.get("关键特性") or "").strip(),
        "L4服务或服务组": (row.get("L4服务或服务组") or "").strip(),
        "服务交付PM": (row.get("服务交付PM") or "").strip(),
    }
    for month in MILESTONE_COLUMNS:
        normalized[month] = (row.get(month) or "").strip()
    return normalized


def row_to_db_tuple(row):
    return (
        row["项目名称"], row["项目经理"], row["工作量（人月）"], row["重点工作"],
        row["关键特性"], row["L4服务或服务组"], row["服务交付PM"],
        *[row[month] for month in MILESTONE_COLUMNS],
    )


def import_csv(replace=False):
    init_db()
    if not CSV_PATH.exists():
        return 0
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [normalize_row(row) for row in reader]
    if not rows:
        return 0
    sql_columns = [
        "project_name", "project_manager", "workload_person_month", "focus_work",
        "feature_name", "service_group", "delivery_pm"
    ] + [f'"{month}"' for month in MILESTONE_COLUMNS]
    placeholders = ", ".join(["?"] * len(sql_columns))
    with get_conn() as conn:
        if replace:
            conn.execute("DELETE FROM projects")
        conn.executemany(
            f"INSERT INTO projects ({', '.join(sql_columns)}) VALUES ({placeholders})",
            [row_to_db_tuple(row) for row in rows],
        )
        conn.commit()
    return len(rows)


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
            f"""
            SELECT
                id,
                project_name,
                project_manager,
                workload_person_month,
                focus_work,
                feature_name,
                service_group,
                delivery_pm,
                {', '.join([f'"{month}"' for month in MILESTONE_COLUMNS])}
            FROM projects
            ORDER BY id ASC
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
                project_name,
                project_manager,
                workload_person_month,
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


def build_feature_roadmap(rows):
    features = []
    stage_colors = {
        "启动开发": "stage-kickoff",
        "实现": "stage-build",
        "集成测试": "stage-test",
        "上线交付": "stage-release",
    }
    for row in rows:
        feature_name = (row.get("feature_name") or row.get("关键特性") or "").strip() or "未命名特性"
        active_month_indexes = [i for i, m in enumerate(MILESTONE_COLUMNS) if (row.get(m) or "").strip()]
        months = []
        for i, month in enumerate(MILESTONE_COLUMNS):
            value = (row.get(month) or "").strip()
            months.append({
                "label": month,
                "value": value,
                "active": bool(value),
                "index": i,
            })

        if active_month_indexes:
            total = len(active_month_indexes)
            stage_ranges = {}
            for idx, stage in enumerate(STAGES):
                start_pos = round(idx * total / len(STAGES))
                end_pos = round((idx + 1) * total / len(STAGES))
                segment = active_month_indexes[start_pos:end_pos]
                if not segment and active_month_indexes:
                    fallback_index = active_month_indexes[min(start_pos, total - 1)]
                    segment = [fallback_index]
                stage_ranges[stage] = set(segment)
            start = MILESTONE_COLUMNS[active_month_indexes[0]]
            end = MILESTONE_COLUMNS[active_month_indexes[-1]]
        else:
            stage_ranges = {stage: set() for stage in STAGES}
            start = end = ""

        stage_rows = []
        for stage in STAGES:
            row_months = []
            for month in months:
                active = month["index"] in stage_ranges[stage]
                row_months.append({
                    "label": month["label"],
                    "value": month["value"],
                    "active": active,
                    "class_name": stage_colors.get(stage, ""),
                })
            stage_rows.append({
                "name": stage,
                "months": row_months,
            })

        features.append({
            "id": row.get("id"),
            "project_name": (row.get("project_name") or row.get("项目名称") or "").strip(),
            "project_manager": (row.get("project_manager") or row.get("项目经理") or "").strip(),
            "workload_person_month": (row.get("workload_person_month") or row.get("工作量（人月）") or "").strip(),
            "feature_name": feature_name,
            "focus_work": (row.get("focus_work") or row.get("重点工作") or "").strip(),
            "service_group": (row.get("service_group") or row.get("L4服务或服务组") or "").strip(),
            "delivery_pm": (row.get("delivery_pm") or row.get("服务交付PM") or "").strip(),
            "stage_rows": stage_rows,
            "start": start,
            "end": end,
        })
    return features


def form_to_project_data(form):
    data = {
        "project_name": (form.get("project_name") or "").strip(),
        "project_manager": (form.get("project_manager") or "").strip(),
        "workload_person_month": (form.get("workload_person_month") or "").strip(),
        "focus_work": (form.get("focus_work") or "").strip(),
        "feature_name": (form.get("feature_name") or "").strip(),
        "service_group": (form.get("service_group") or "").strip(),
        "delivery_pm": (form.get("delivery_pm") or "").strip(),
    }
    for month in MILESTONE_COLUMNS:
        data[month] = (form.get(month) or "").strip()
    return data


@app.route('/')
def index():
    rows = load_projects()
    features = build_feature_roadmap(rows)
    return render_template('index.html', features=features, months=MILESTONE_COLUMNS)


@app.route('/admin/projects')
def admin_projects():
    rows = load_projects()
    return render_template('admin_projects.html', projects=rows, months=MILESTONE_COLUMNS)


@app.route('/admin/projects/new', methods=['GET', 'POST'])
def admin_project_new():
    if request.method == 'POST':
        data = form_to_project_data(request.form)
        sql_columns = [
            "project_name", "project_manager", "workload_person_month", "focus_work",
            "feature_name", "service_group", "delivery_pm"
        ] + [f'"{month}"' for month in MILESTONE_COLUMNS]
        values = [data[key] for key in [
            "project_name", "project_manager", "workload_person_month", "focus_work",
            "feature_name", "service_group", "delivery_pm"
        ]] + [data[month] for month in MILESTONE_COLUMNS]
        placeholders = ", ".join(["?"] * len(values))
        with get_conn() as conn:
            conn.execute(
                f"INSERT INTO projects ({', '.join(sql_columns)}) VALUES ({placeholders})",
                values,
            )
            conn.commit()
        return redirect(url_for('admin_projects'))
    return render_template('project_form.html', project={}, months=MILESTONE_COLUMNS, mode='new')


@app.route('/admin/projects/<int:project_id>/edit', methods=['GET', 'POST'])
def admin_project_edit(project_id):
    project = load_project(project_id)
    if not project:
        return redirect(url_for('admin_projects'))
    if request.method == 'POST':
        data = form_to_project_data(request.form)
        set_clause = [
            "project_name = ?",
            "project_manager = ?",
            "workload_person_month = ?",
            "focus_work = ?",
            "feature_name = ?",
            "service_group = ?",
            "delivery_pm = ?",
        ] + [f'"{month}" = ?' for month in MILESTONE_COLUMNS] + ["updated_at = CURRENT_TIMESTAMP"]
        values = [data[key] for key in [
            "project_name", "project_manager", "workload_person_month", "focus_work",
            "feature_name", "service_group", "delivery_pm"
        ]] + [data[month] for month in MILESTONE_COLUMNS] + [project_id]
        with get_conn() as conn:
            conn.execute(
                f"UPDATE projects SET {', '.join(set_clause)} WHERE id = ?",
                values,
            )
            conn.commit()
        return redirect(url_for('admin_projects'))
    return render_template('project_form.html', project=project, months=MILESTONE_COLUMNS, mode='edit')


@app.route('/admin/projects/<int:project_id>/delete', methods=['POST'])
def admin_project_delete(project_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
    return redirect(url_for('admin_projects'))


@app.route('/admin/projects/import-csv', methods=['POST'])
def admin_projects_import_csv():
    import_csv(replace=True)
    return redirect(url_for('admin_projects'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5010, debug=False)
