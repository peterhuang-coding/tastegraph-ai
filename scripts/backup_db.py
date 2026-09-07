#!/usr/bin/env python3
"""每日 SQLite 在线备份（docs/operations.md §6）。

    python3 scripts/backup_db.py                # 备份 → 校验 → 清理旧备份
    python3 scripts/backup_db.py --dry-run      # 只打印计划
    python3 scripts/backup_db.py --keep-days 14 --keep-count 30

环境变量（/tmp 演练用，生产不用设）:
    TASTEGRAPH_DB           源库路径（默认 data/taste_graph.db）
    TASTEGRAPH_BACKUP_DIR   备份目录（默认 data/backups/，已 gitignore）

一致性: sqlite3 Online Backup API — 源库正被写入也能拿到一致快照
（旧 scripts/backup.py 直接拷贝 .db 文件，WAL 未 checkpoint 时可能丢最新写入）。
校验: 备份库 PRAGMA integrity_check + 关键表行数与源库比对。
保留: 默认删 14 天前的备份，且最多留 30 份（双条件，先到先删）。
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("TASTEGRAPH_DB", str(BASE_DIR / "data" / "taste_graph.db")))
BACKUPS_DIR = Path(os.environ.get(
    "TASTEGRAPH_BACKUP_DIR", str(BASE_DIR / "data" / "backups")))

# 行数比对的关键表（不存在则跳过，不报错）
VERIFY_TABLES = ["images", "ingestion_items", "crawl_runs", "job_runs",
                 "sources", "daily_packs", "publish_history"]
BACKUP_PREFIX = "taste_graph-"
BACKUP_SUFFIX = ".db"


def table_counts(con: sqlite3.Connection) -> dict[str, int]:
    counts = {}
    for table in VERIFY_TABLES:
        try:
            counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error:
            continue
    return counts


def online_backup(src: Path, dst: Path) -> None:
    """sqlite3 Online Backup API：逐页拷贝，源库可并发使用。"""
    src_con = sqlite3.connect(str(src))
    try:
        dst_con = sqlite3.connect(str(dst))
        try:
            src_con.backup(dst_con)
        finally:
            dst_con.close()
    finally:
        src_con.close()


def verify_backup(src: Path, dst: Path) -> dict:
    """校验备份：integrity_check + 关键表行数比对。返回校验明细。"""
    result = {"integrity": None, "counts_match": None, "source_counts": {}, "backup_counts": {}}
    with sqlite3.connect(str(src)) as sc:
        result["source_counts"] = table_counts(sc)
    with sqlite3.connect(str(dst)) as bc:
        integrity = bc.execute("PRAGMA integrity_check").fetchone()[0]
        result["integrity"] = integrity
        result["backup_counts"] = table_counts(bc)
    mismatches = {
        t: (result["source_counts"].get(t), result["backup_counts"].get(t))
        for t in result["source_counts"]
        if result["source_counts"].get(t) != result["backup_counts"].get(t)
    }
    result["counts_match"] = not mismatches
    result["mismatches"] = mismatches
    return result


def prune_old_backups(keep_days: int, keep_count: int, dry_run: bool) -> list[str]:
    """删 14 天前旧备份；总数超 keep_count 时再按时间从旧到新删。返回删除文件名。"""
    if not BACKUPS_DIR.is_dir():
        return []
    files = sorted(
        (p for p in BACKUPS_DIR.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}") if p.is_file()),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    cutoff = time.time() - keep_days * 86400
    deleted = []
    for i, p in enumerate(files):
        reason = None
        if p.stat().st_mtime < cutoff:
            reason = "age"
        elif i >= keep_count:
            reason = "count"
        if reason:
            if dry_run:
                deleted.append(f"{p.name} ({reason})")
            else:
                try:
                    p.unlink()
                    deleted.append(f"{p.name} ({reason})")
                except OSError:
                    pass
    return deleted


def main() -> int:
    ap = argparse.ArgumentParser(description="TasteGraph SQLite 每日在线备份")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写文件")
    ap.add_argument("--keep-days", type=int, default=14, help="保留天数（默认 14）")
    ap.add_argument("--keep-count", type=int, default=30, help="最多保留份数（默认 30）")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"[backup] 源库不存在: {DB_PATH}")
        return 1
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = BACKUPS_DIR / f"{BACKUP_PREFIX}{ts}{BACKUP_SUFFIX}"
    src_size = DB_PATH.stat().st_size
    print(f"[backup] 源库: {DB_PATH} ({src_size / 1e6:.1f} MB)")
    print(f"[backup] 目标: {dst}")

    if args.dry_run:
        print("[backup] dry-run：不执行备份与删除")
        return 0

    try:
        online_backup(DB_PATH, dst)
    except sqlite3.Error as e:
        print(f"[backup] 备份失败: {e}")
        dst.unlink(missing_ok=True)
        return 1

    check = verify_backup(DB_PATH, dst)
    ok = check["integrity"] == "ok" and check["counts_match"]
    dst_size = dst.stat().st_size
    print(f"[backup] integrity_check: {check['integrity']}")
    print(f"[backup] 行数比对: {'一致' if check['counts_match'] else '不一致 ' + json.dumps(check['mismatches'], ensure_ascii=False)}")
    print(f"[backup] 备份大小: {dst_size / 1e6:.1f} MB")
    for t, c in sorted(check["backup_counts"].items()):
        print(f"           {t}: {c} 行")

    deleted = prune_old_backups(args.keep_days, args.keep_count, args.dry_run)
    for name in deleted:
        print(f"[backup] 清理旧备份: {name}")

    summary = {
        "ok": ok,
        "source": str(DB_PATH),
        "backup": str(dst),
        "source_bytes": src_size,
        "backup_bytes": dst_size,
        "integrity": check["integrity"],
        "counts_match": check["counts_match"],
        "tables": check["backup_counts"],
        "pruned": deleted,
        "finished_at": datetime.now().isoformat(),
    }
    (BACKUPS_DIR / "latest_backup.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if not ok:
        print("[backup] 校验未通过，保留备份供排查，退出码 1")
        return 1
    print("[backup] 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
