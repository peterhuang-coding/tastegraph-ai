#!/usr/bin/env python3
"""幂等数据库迁移 — docs/data-contract.md 的落地点。

    python3 scripts/migrations.py

原则（契约 §0.6）:
- 每个迁移以版本号登记在 schema_migrations 表，已应用则跳过
- 全部 CREATE TABLE IF NOT EXISTS / PRAGMA 字段检查，重复运行安全
- 旧数据一律保留，禁止静默丢字段
- 输出迁移报告 data/migration_report-<timestamp>.json

采集入口（daily_ingestion.py preflight）与服务启动前都应调用本脚本。
"""
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# TASTEGRAPH_DB / TASTEGRAPH_MIGRATION_REPORT_DIR 仅用于 /tmp 副本演练；生产默认库在 data/ 下。
DB_PATH = Path(os.environ.get("TASTEGRAPH_DB", str(BASE_DIR / "data" / "taste_graph.db")))
REPORT_DIR = Path(os.environ.get("TASTEGRAPH_MIGRATION_REPORT_DIR", str(BASE_DIR / "data")))

MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "create_schema_migrations", "迁移登记表"),
    (2, "create_crawl_runs", "CrawlRun 运行实例表（契约 §1）"),
    (3, "create_ingestion_items", "IngestionItem 持久化下载 backlog（契约 §1）"),
    (4, "create_metrics_snapshots", "MetricsSnapshot 窗口快照（契约 §1）"),
    (5, "create_job_runs", "JobRun 调度器运行态（契约 §1）"),
    (6, "add_daily_packs_dir_path", "daily_packs 补 dir_path 列（目录路径与 id 分离）"),
    (7, "add_crawl_runs_stages_json", "crawl_runs 补 stages_json（阶段幂等标记，--resume 依据）"),
    (8, "add_images_content_hash", "images 补 content_hash（内容 checksum 去重，契约 §1）"),
    (9, "extend_job_runs_persistence", "job_runs 补 run_id/scheduled_date/error_summary/pid/heartbeat_at/log_path（调度状态持久化，契约 §1）"),
]

# 值为 (表, 列, 声明) 或其列表（一个迁移补多列）。全部 PRAGMA 检查后 ADD COLUMN，幂等。
ADD_COLUMNS: dict[str, object] = {
    "add_daily_packs_dir_path": ("daily_packs", "dir_path", "TEXT DEFAULT ''"),
    "add_crawl_runs_stages_json": ("crawl_runs", "stages_json", "TEXT DEFAULT '{}'"),
    "add_images_content_hash": ("images", "content_hash", "TEXT DEFAULT ''"),
    "extend_job_runs_persistence": [
        ("job_runs", "run_id", "TEXT DEFAULT ''"),
        ("job_runs", "scheduled_date", "TEXT DEFAULT ''"),
        ("job_runs", "error_summary", "TEXT DEFAULT ''"),
        ("job_runs", "pid", "INTEGER DEFAULT 0"),
        ("job_runs", "heartbeat_at", "TEXT DEFAULT ''"),
        ("job_runs", "log_path", "TEXT DEFAULT ''"),
    ],
}

# 列补完后执行的附加 DDL（全部 IF NOT EXISTS，幂等）。
EXTRA_SQL = {
    "extend_job_runs_persistence": (
        "CREATE INDEX IF NOT EXISTS idx_job_runs_date "
        "ON job_runs(job_name, scheduled_date, status)"
    ),
}

SQL = {
    "create_schema_migrations": """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            applied_at TEXT NOT NULL
        )
    """,
    "create_crawl_runs": """
        CREATE TABLE IF NOT EXISTS crawl_runs (
            id TEXT PRIMARY KEY,
            scheduled_for TEXT DEFAULT '',
            started_at TEXT,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            pages_attempted INTEGER DEFAULT 0,
            pages_fetched INTEGER DEFAULT 0,
            pages_failed INTEGER DEFAULT 0,
            images_discovered INTEGER DEFAULT 0,
            images_downloaded INTEGER DEFAULT 0,
            backlog_count INTEGER DEFAULT 0,
            error_summary TEXT DEFAULT ''
        )
    """,
    "create_ingestion_items": """
        CREATE TABLE IF NOT EXISTS ingestion_items (
            id TEXT PRIMARY KEY,
            run_id TEXT DEFAULT '',
            source_id TEXT,
            page_url TEXT DEFAULT '',
            image_url TEXT NOT NULL,
            alt_text TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'discovered',
            attempt_count INTEGER DEFAULT 0,
            last_error TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ingestion_status ON ingestion_items(status);
        CREATE INDEX IF NOT EXISTS idx_ingestion_run ON ingestion_items(run_id);
        CREATE INDEX IF NOT EXISTS idx_ingestion_source ON ingestion_items(source_id)
    """,
    "create_metrics_snapshots": """
        CREATE TABLE IF NOT EXISTS metrics_snapshots (
            id TEXT PRIMARY KEY,
            publish_record_id TEXT,
            window TEXT NOT NULL,
            likes INTEGER DEFAULT 0,
            saves INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            recorded_at TEXT NOT NULL,
            UNIQUE (publish_record_id, window)
        )
    """,
    "create_job_runs": """
        CREATE TABLE IF NOT EXISTS job_runs (
            id TEXT PRIMARY KEY,
            job_name TEXT NOT NULL,
            scheduled_for TEXT DEFAULT '',
            started_at TEXT,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            summary_json TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_job_runs_name ON job_runs(job_name, scheduled_for)
    """,
}


def table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def apply_migrations(con: sqlite3.Connection) -> list[dict]:
    """按版本号顺序应用未执行的迁移，返回本轮报告条目。"""
    # registry 自身先无条件建表（幂等），再读取已应用版本
    con.execute(SQL["create_schema_migrations"])
    con.commit()
    applied_versions = {
        r[0] for r in con.execute("SELECT version FROM schema_migrations").fetchall()
    }
    report = []
    for version, name, description in MIGRATIONS:
        if version in applied_versions:
            report.append({"version": version, "name": name, "status": "skipped"})
            continue
        try:
            if name in ADD_COLUMNS:
                cols_spec = ADD_COLUMNS[name]
                if isinstance(cols_spec, tuple):
                    cols_spec = [cols_spec]
                for table, col, decl in cols_spec:
                    cols = table_columns(con, table)
                    if col not in cols:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                status = "applied"
            elif name in SQL:
                con.executescript(SQL[name])
                status = "applied"
            else:
                raise sqlite3.Error(f"迁移 {name} 无对应 SQL 定义")
            if name in EXTRA_SQL:
                con.execute(EXTRA_SQL[name])
            con.execute(
                "INSERT INTO schema_migrations (version, name, description, applied_at) "
                "VALUES (?, ?, ?, ?)",
                (version, name, description, datetime.now().isoformat()),
            )
            con.commit()
        except sqlite3.Error as e:
            con.rollback()
            report.append({"version": version, "name": name, "status": "failed", "error": str(e)})
            continue
        report.append({"version": version, "name": name, "status": status})
    return report


def main() -> int:
    if not DB_PATH.exists():
        print(f"[migrations] DB 不存在: {DB_PATH}")
        return 1
    con = sqlite3.connect(str(DB_PATH))
    con.execute("PRAGMA busy_timeout=5000")
    try:
        report = apply_migrations(con)
    finally:
        con.close()

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"migration_report-{ts}.json"
    payload = {
        "run_at": datetime.now().isoformat(),
        "db": str(DB_PATH),
        "entries": report,
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    applied = [e for e in report if e["status"] == "applied"]
    failed = [e for e in report if e["status"] == "failed"]
    print(f"[migrations] 本轮新增 {len(applied)} 项，跳过 {len(report) - len(applied) - len(failed)} 项"
          + (f"，失败 {len(failed)} 项" if failed else ""))
    for e in failed:
        print(f"  ✗ v{e['version']} {e['name']}: {e['error']}")
    print(f"[migrations] 报告: {report_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
