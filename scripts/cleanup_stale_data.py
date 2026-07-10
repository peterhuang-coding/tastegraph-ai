#!/usr/bin/env python3
"""
tape — 数据清理脚本
========================
清理过期图片、知识图谱节点去重、日志轮转。

用法:
  python3 scripts/cleanup_stale_data.py            # 执行清理
  python3 scripts/cleanup_stale_data.py --dry-run  # 预览不删除
  python3 scripts/cleanup_stale_data.py --days 60  # 60天未用算过期
"""

import argparse
import gzip
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "taste_graph.db"
EVENTS_LOG = DATA_DIR / "events.log"
BACKUPS_DIR = DATA_DIR / "backups"

DEFAULT_STALE_DAYS = 30


def get_db_connection() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH))


def cleanup_stale_images(dry_run: bool = False, stale_days: int = DEFAULT_STALE_DAYS) -> int:
    """Delete images not used in the last N days. Returns number of deleted files."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
    deleted = 0
    skipped = 0

    for img_path in sorted(IMAGES_DIR.glob("*")):
        if not img_path.is_file():
            continue
        mtime = datetime.fromtimestamp(img_path.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            if dry_run:
                print(f"  [dry-run] 删除: {img_path.name} (最后使用 {mtime.strftime('%Y-%m-%d')})")
            else:
                img_path.unlink()
                print(f"  ✅ 删除: {img_path.name}")
            deleted += 1
        else:
            skipped += 1

    print(f"  图片清理: {deleted} 张删除, {skipped} 张保留")
    return deleted


def rotate_logs(dry_run: bool = False) -> int:
    """Compress and rotate events.log if over 1MB. Returns bytes saved."""
    if not EVENTS_LOG.exists():
        return 0

    size = EVENTS_LOG.stat().st_size
    if size < 1_000_000:
        return 0

    date_str = datetime.now().strftime("%Y-%m-%d")
    gz_path = EVENTS_LOG.with_name(f"events-{date_str}.log.gz")

    if dry_run:
        print(f"  [dry-run] 压缩: {EVENTS_LOG.name} ({size/1024:.0f}KB → {gz_path.name})")
        return size

    with open(EVENTS_LOG, "rb") as f_in:
        with gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

    # 清空原日志（不删除文件）
    with open(EVENTS_LOG, "w") as f:
        f.write("")

    saved = size - gz_path.stat().st_size
    print(f"  ✅ 日志轮转: {EVENTS_LOG.name} → {gz_path.name} (节省 {saved/1024:.0f}KB)")
    return saved


def main():
    parser = argparse.ArgumentParser(description="tape 数据清理工具")
    parser.add_argument("--dry-run", action="store_true", help="预览不删除")
    parser.add_argument("--days", type=int, default=DEFAULT_STALE_DAYS, help="过期天数 (默认: 30)")
    parser.add_argument("--skip-images", action="store_true", help="跳过图片清理")
    parser.add_argument("--skip-logs", action="store_true", help="跳过日志轮转")
    args = parser.parse_args()

    mode = "预览模式" if args.dry_run else "执行模式"
    print(f"🔍 数据清理 ({mode})")

    if not args.skip_images:
        print(f"\n📸 清理过期图片 (>{args.days}天未使用)...")
        cleanup_stale_images(dry_run=args.dry_run, stale_days=args.days)

    if not args.skip_logs:
        print(f"\n📝 日志轮转...")
        rotate_logs(dry_run=args.dry_run)

    print(f"\n✅ 清理完成")


if __name__ == "__main__":
    main()
