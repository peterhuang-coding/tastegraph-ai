#!/usr/bin/env python3
"""
tape — 数据备份脚本
====================
备份核心数据文件（taste_graph.json, taste_graph.db）到 data/backups/。

用法:
  python3 scripts/backup.py                    # 执行备份
  python3 scripts/backup.py --dry-run          # 预览不备份
  python3 scripts/backup.py --keep 14          # 保留最近14个版本
"""

import argparse
import gzip
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BACKUPS_DIR = DATA_DIR / "backups"

# 要备份的文件列表
BACKUP_FILES = [
    "taste_graph.json",
    "taste_graph.db",
]

# 图片目录（增量备份）
IMAGES_DIR = DATA_DIR / "images"


def get_backup_path(file_name: str) -> Path:
    """生成备份路径: data/backups/taste_graph-2026-07-11.json.gz"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    stem = file_name.rsplit(".", 1)[0]
    ext = file_name.rsplit(".", 1)[1]
    return BACKUPS_DIR / f"{stem}-{date_str}.{ext}.gz"


def backup_file(file_name: str, dry_run: bool = False) -> int:
    """备份单个文件，返回字节数。"""
    src = DATA_DIR / file_name
    if not src.exists():
        print(f"  ⚠️ 跳过: {file_name} (不存在)")
        return 0

    dst = get_backup_path(file_name)
    size = src.stat().st_size

    if dry_run:
        print(f"  [dry-run] 备份: {file_name} ({size/1024:.0f}KB → {dst.name})")
        return size

    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    with open(src, "rb") as f_in:
        with gzip.open(dst, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

    saved = size - dst.stat().st_size
    print(f"  ✅ 备份: {file_name} ({size/1024:.0f}KB → {dst.name}, 节省 {saved/1024:.0f}KB)")
    return size


def cleanup_old_backups(keep: int = 7, dry_run: bool = False):
    """删除超过 keep 个版本的旧备份。"""
    if not BACKUPS_DIR.exists():
        return

    # 按文件名分组
    backups = {}
    for f in sorted(BACKUPS_DIR.iterdir()):
        if not f.is_file() or not f.name.endswith(".gz"):
            continue
        stem = f.name.rsplit("-", 1)[0]  # taste_graph
        backups.setdefault(stem, []).append(f)

    for stem, files in backups.items():
        # 按日期排序，保留最新的 keep 个
        files.sort(reverse=True)
        for old in files[keep:]:
            if dry_run:
                print(f"  [dry-run] 删除旧备份: {old.name}")
            else:
                old.unlink()
                print(f"  🗑 删除旧备份: {old.name}")


def main():
    parser = argparse.ArgumentParser(description="tape 数据备份工具")
    parser.add_argument("--dry-run", action="store_true", help="预览不备份")
    parser.add_argument("--keep", type=int, default=7, help="保留最近几个版本 (默认: 7)")
    args = parser.parse_args()

    mode = "预览模式" if args.dry_run else "执行模式"
    print(f"💾 数据备份 ({mode})")

    total = 0
    for file_name in BACKUP_FILES:
        total += backup_file(file_name, dry_run=args.dry_run)

    if total > 0:
        print(f"\n  本次备份: {total/1024:.0f}KB")
    else:
        print(f"\n  ⚠️ 没有文件需要备份")

    cleanup_old_backups(keep=args.keep, dry_run=args.dry_run)
    print(f"✅ 备份完成")


if __name__ == "__main__":
    main()
