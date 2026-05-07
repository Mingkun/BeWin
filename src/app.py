from flask import Flask, render_template
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


def import_csv_if_needed():
    init_db()
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        if count > 0 or not CSV_PATH.exists():
            return
        with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = [normalize_row(row) for row in reader]
        if not rows:
            return
        sql_columns = [
            "project_name", "project_manager", "workload_person_month", "focus_work",
            "feature_name", "service_group", "delivery_pm"
        ] + [f'"{month}"' for month in MILESTONE_COLUMNS]
        placeholders = ", ".join(["?"] * len(sql_columns))
        conn.executemany(
            f"INSERT INTO projects ({', '.join(sql_columns)}) VALUES ({placeholders})",
            [
                (
                    row["项目名称"], row["项目经理"], row["工作量（人月）"], row["重点工作"],
                    row["关键特性"], row["L4服务或服务组"], row["服务交付PM"],
                    *[row[month] for month in MILESTONE_COLUMNS],
                )
                for row in rows
            ],
        )
        conn.commit()


def load_projects():
    import_csv_if_needed()
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
                project_name AS "项目名称",
                project_manager AS "项目经理",
                workload_person_month AS "工作量（人月）",
                focus_work AS "重点工作",
                feature_name AS "关键特性",
                service_group AS "L4服务或服务组",
                delivery_pm AS "服务交付PM",
                {', '.join([f'"{month}"' for month in MILESTONE_COLUMNS])}
            FROM projects
            ORDER BY id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def build_feature_roadmap(rows):
    features = []
    stage_colors = {
        "启动开发": "stage-kickoff",
        "实现": "stage-build",
        "集成测试": "stage-test",
        "上线交付": "stage-release",
    }
    for row in rows:
        feature_name = (row.get("关键特性") or "").strip() or "未命名特性"
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
            "project_name": (row.get("项目名称") or "").strip(),
            "project_manager": (row.get("项目经理") or "").strip(),
            "workload_person_month": (row.get("工作量（人月）") or "").strip(),
            "feature_name": feature_name,
            "focus_work": (row.get("重点工作") or "").strip(),
            "service_group": (row.get("L4服务或服务组") or "").strip(),
            "delivery_pm": (row.get("服务交付PM") or "").strip(),
            "stage_rows": stage_rows,
            "start": start,
            "end": end,
        })
    return features


@app.route('/')
def index():
    rows = load_projects()
    features = build_feature_roadmap(rows)
    return render_template('index.html', features=features, months=MILESTONE_COLUMNS)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5010, debug=False)
