"""
migrate_v2.py — 数据库迁移脚本（PRD v2.0）

变更内容：
  1. reports.doctor_report  TEXT           新增，存储面向医生的专业版内容
  2. reports.report_type    VARCHAR(16)    新增，'standard' 或 'monthly'
  3. reports.created_at     加索引         加速日期查询

执行方式：
  python migrate_v2.py

安全性：
  - 使用 IF NOT EXISTS / 忽略重复索引，幂等可重复执行
  - 不删除任何已有字段或数据
"""

import sys

from sqlalchemy import inspect, text

from database import engine


def column_exists(conn, table: str, column: str) -> bool:
    insp = inspect(conn)
    return any(c["name"] == column for c in insp.get_columns(table))


def index_exists(conn, table: str, index_name: str) -> bool:
    insp = inspect(conn)
    return any(idx["name"] == index_name for idx in insp.get_indexes(table))


def run_migration():
    with engine.begin() as conn:
        # 1. 新增 doctor_report 列
        if not column_exists(conn, "reports", "doctor_report"):
            conn.execute(text(
                "ALTER TABLE reports ADD COLUMN doctor_report MEDIUMTEXT NULL"
            ))
            print("✅ 新增列: reports.doctor_report")
        else:
            print("⏭  跳过: reports.doctor_report 已存在")

        # 2. 新增 report_type 列
        if not column_exists(conn, "reports", "report_type"):
            conn.execute(text(
                "ALTER TABLE reports ADD COLUMN report_type VARCHAR(16) NOT NULL DEFAULT 'standard'"
            ))
            print("✅ 新增列: reports.report_type")
        else:
            print("⏭  跳过: reports.report_type 已存在")

        # 3. 给 created_at 加索引（已有则跳过）
        idx_name = "ix_reports_created_at"
        if not index_exists(conn, "reports", idx_name):
            conn.execute(text(
                f"CREATE INDEX {idx_name} ON reports (created_at)"
            ))
            print(f"✅ 新增索引: {idx_name}")
        else:
            print(f"⏭  跳过: 索引 {idx_name} 已存在")

    print("\n🎉 迁移完成，现有数据未受影响。")


if __name__ == "__main__":
    try:
        run_migration()
    except Exception as exc:
        print(f"\n❌ 迁移失败: {exc}", file=sys.stderr)
        sys.exit(1)
