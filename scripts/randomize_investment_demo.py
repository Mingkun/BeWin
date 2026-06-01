#!/usr/bin/env python3
import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "releaseplan.db"

DEMO_PROFILES = [
    {
        "project_name": "模拟项目01",
        "investment_subject": "客户经营投资池",
        "control_gate": "增长经营管控灶",
        "rd_budget_w": "286",
        "workload_person_month": "96",
        "self": "9",
        "od": "6",
        "tm": "3",
    },
    {
        "project_name": "模拟项目02",
        "investment_subject": "客户经营投资池",
        "control_gate": "增长经营管控灶",
        "rd_budget_w": "214",
        "workload_person_month": "72",
        "self": "7",
        "od": "4",
        "tm": "2",
    },
    {
        "project_name": "模拟项目03",
        "investment_subject": "平台能力投资池",
        "control_gate": "平台能力管控灶",
        "rd_budget_w": "342",
        "workload_person_month": "118",
        "self": "12",
        "od": "7",
        "tm": "3",
    },
    {
        "project_name": "模拟项目04",
        "investment_subject": "平台能力投资池",
        "control_gate": "平台能力管控灶",
        "rd_budget_w": "178",
        "workload_person_month": "61",
        "self": "6",
        "od": "5",
        "tm": "2",
    },
    {
        "project_name": "模拟项目05",
        "investment_subject": "业务连续性投资池",
        "control_gate": "风险合规管控灶",
        "rd_budget_w": "96",
        "workload_person_month": "34",
        "self": "4",
        "od": "2",
        "tm": "1",
    },
    {
        "project_name": "模拟项目06",
        "investment_subject": "数据智能投资池",
        "control_gate": "数据智能管控灶",
        "rd_budget_w": "398",
        "workload_person_month": "132",
        "self": "11",
        "od": "8",
        "tm": "4",
    },
    {
        "project_name": "模拟项目07",
        "investment_subject": "数据智能投资池",
        "control_gate": "数据智能管控灶",
        "rd_budget_w": "246",
        "workload_person_month": "88",
        "self": "8",
        "od": "5",
        "tm": "2",
    },
    {
        "project_name": "模拟项目08",
        "investment_subject": "体验增长投资池",
        "control_gate": "体验增长管控灶",
        "rd_budget_w": "162",
        "workload_person_month": "57",
        "self": "5",
        "od": "3",
        "tm": "2",
    },
    {
        "project_name": "模拟项目09",
        "investment_subject": "基础设施投资池",
        "control_gate": "基础设施管控灶",
        "rd_budget_w": "430",
        "workload_person_month": "126",
        "self": "10",
        "od": "9",
        "tm": "5",
    },
    {
        "project_name": "模拟项目10",
        "investment_subject": "客户经营投资池",
        "control_gate": "体验增长管控灶",
        "rd_budget_w": "124",
        "workload_person_month": "45",
        "self": "5",
        "od": "2",
        "tm": "1",
    },
]


def backup_database(db_path):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.bak-before-investment-demo-randomize-{timestamp}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def sync_investment_records(conn):
    rows = conn.execute(
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
        WHERE project_name LIKE '模拟项目%'
        """
    ).fetchall()
    for row in rows:
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
                row["id"],
                row["investment_subject"] or "",
                row["control_gate"] or "",
                row["project_name"] or "",
                row["rd_budget_w"] or "",
                row["workload_person_month"] or "",
                row["headcount_budget_self_owned"] or "",
                row["headcount_budget_od"] or "",
                row["headcount_budget_tm"] or "",
            ),
        )


def main():
    parser = argparse.ArgumentParser(description="Make BeWin investment demo data less uniform.")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database path")
    parser.add_argument("--no-backup", action="store_true", help="Skip database backup")
    args = parser.parse_args()

    db_path = Path(args.db)
    backup_path = None if args.no_backup else backup_database(db_path)
    updated_rows = 0

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for profile in DEMO_PROFILES:
            cursor = conn.execute(
                """
                UPDATE projects
                SET investment_subject = ?,
                    control_gate = ?,
                    rd_budget_w = ?,
                    workload_person_month = ?,
                    headcount_budget_self_owned = ?,
                    headcount_budget_od = ?,
                    headcount_budget_tm = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE project_name = ?
                  AND project_name LIKE '模拟项目%'
                """,
                (
                    profile["investment_subject"],
                    profile["control_gate"],
                    profile["rd_budget_w"],
                    profile["workload_person_month"],
                    profile["self"],
                    profile["od"],
                    profile["tm"],
                    profile["project_name"],
                ),
            )
            updated_rows += cursor.rowcount
        sync_investment_records(conn)
        conn.commit()

    if backup_path:
        print(f"backup={backup_path}")
    print(f"updated_rows={updated_rows}")


if __name__ == "__main__":
    main()
