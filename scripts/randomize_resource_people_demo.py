#!/usr/bin/env python3
import argparse
import random
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "releaseplan.db"

DEPARTMENT_NAMES = {
    1: ("数字化产品中心", "产品规划组"),
    2: ("数字化产品中心", "交易平台组"),
    3: ("数字化产品中心", "数据智能组"),
    4: ("数字化产品中心", "体验增长组"),
    5: ("数字化产品中心", "基础能力组"),
    6: ("部门一", "平台研发部"),
    7: ("研发中心", "交付支持组"),
}

DEPARTMENT_WEIGHTS = {
    1: 44,
    2: 63,
    3: 51,
    4: 38,
    5: 58,
    6: 27,
    7: 19,
}

PERSON_TYPE_WEIGHTS = {
    "自有": 154,
    "OD": 93,
    "TM": 53,
}

PROJECT_WEIGHTS = {
    1: 42,
    2: 36,
    3: 31,
    4: 34,
    5: 27,
    6: 29,
    7: 24,
    8: 32,
    9: 21,
    10: 24,
}

ALLOCATION_WEIGHTS = {
    "100%": 56,
    "90%": 61,
    "80%": 49,
    "70%": 43,
    "60%": 33,
    "50%": 25,
    "40%": 18,
    "30%": 9,
    "20%": 6,
}

ROLE_WEIGHTS = {
    "后端开发": 54,
    "前端开发": 35,
    "测试工程师": 32,
    "产品经理": 24,
    "项目管理": 18,
    "运维工程师": 21,
    "架构师": 13,
    "数据工程师": 28,
    "算法工程师": 17,
    "交互设计": 12,
    "交付经理": 16,
    "安全工程师": 10,
    "业务分析": 20,
}

STATUS_WEIGHTS = {
    "在岗": 238,
    "预入项": 21,
    "流动中": 18,
    "休假": 12,
    "待释放": 8,
    "支撑中": 3,
}


def expanded_choices(weight_map):
    values = []
    for value, weight in weight_map.items():
        values.extend([value] * weight)
    return values


def backup_database(db_path):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.bak-before-resource-demo-randomize-{timestamp}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def main():
    parser = argparse.ArgumentParser(description="Make BeWin resource demo data less uniform.")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path")
    parser.add_argument("--seed", type=int, default=20260601, help="Deterministic random seed")
    parser.add_argument("--no-backup", action="store_true", help="Skip database backup")
    args = parser.parse_args()

    db_path = Path(args.db)
    rng = random.Random(args.seed)
    backup_path = None if args.no_backup else backup_database(db_path)

    departments = expanded_choices(DEPARTMENT_WEIGHTS)
    person_types = expanded_choices(PERSON_TYPE_WEIGHTS)
    projects = expanded_choices(PROJECT_WEIGHTS)
    allocations = expanded_choices(ALLOCATION_WEIGHTS)
    roles = expanded_choices(ROLE_WEIGHTS)
    statuses = expanded_choices(STATUS_WEIGHTS)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for department_id, (level_1, level_2) in DEPARTMENT_NAMES.items():
            conn.execute(
                """
                UPDATE departments
                SET level_1_department = ?, level_2_department = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (level_1, level_2, department_id),
            )

        rows = conn.execute(
            """
            SELECT id
            FROM resource_people
            WHERE employee_id LIKE 'MOCK-E%'
            ORDER BY id ASC
            """
        ).fetchall()
        if not rows:
            raise SystemExit("No MOCK-E demo resource rows found.")

        for row in rows:
            person_type = rng.choice(person_types)
            status = rng.choice(statuses)
            allocation = rng.choice(allocations)
            department_id = rng.choice(departments)
            project_id = rng.choice(projects)
            role = rng.choice(roles)
            if status in {"休假", "待释放"} and rng.random() < 0.55:
                project_id = None
                allocation = rng.choice(["0%", "20%", "30%"])
            remarks = rng.choice([
                "",
                "",
                "",
                "核心成员",
                "跨项目支撑",
                "阶段性投入",
                "交付高峰支撑",
                "待下月排期确认",
            ])
            conn.execute(
                """
                UPDATE resource_people
                SET person_type = ?,
                    department_id = ?,
                    project_id = ?,
                    allocation_ratio = ?,
                    role_name = ?,
                    status = ?,
                    remarks = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (person_type, department_id, project_id, allocation, role, status, remarks, row["id"]),
            )
        conn.commit()

    if backup_path:
        print(f"backup={backup_path}")
    print(f"updated_rows={len(rows)}")


if __name__ == "__main__":
    main()
