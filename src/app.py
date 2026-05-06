from flask import Flask, render_template
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
CSV_PATH = BASE_DIR / "docs" / "project_table.csv"
MILESTONE_COLUMNS = [
    "1/31", "2/28", "3/31", "4/30", "5/31", "6/30",
    "7/31", "8/31", "9/30", "10/31", "11/30", "12/31"
]
STAGES = ["启动开发", "实现", "集成测试", "上线交付"]

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))


def load_projects():
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def build_feature_roadmap(rows):
    features = []
    for row in rows:
        feature_name = (row.get("关键特性") or "").strip() or "未命名特性"
        months = []
        active_months = [m for m in MILESTONE_COLUMNS if (row.get(m) or "").strip()]
        for month in MILESTONE_COLUMNS:
            value = (row.get(month) or "").strip()
            months.append({
                "label": month,
                "value": value,
                "active": bool(value),
            })
        if active_months:
            start = active_months[0]
            end = active_months[-1]
        else:
            start = end = ""
        features.append({
            "project_name": (row.get("项目名称") or "").strip(),
            "project_manager": (row.get("项目经理") or "").strip(),
            "feature_name": feature_name,
            "focus_work": (row.get("重点工作") or "").strip(),
            "service_group": (row.get("L4服务或服务组") or "").strip(),
            "delivery_pm": (row.get("服务交付PM") or "").strip(),
            "months": months,
            "stages": STAGES,
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
