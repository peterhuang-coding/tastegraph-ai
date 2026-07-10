#!/usr/bin/env python3
"""
tape — 定时发布调度器
====================
每天在固定时间自动发布小红书帖子。

用法:
  python3 scripts/publish_scheduler.py                    # 启动守护进程
  python3 scripts/publish_scheduler.py --run-now          # 立即执行一次
  python3 scripts/publish_scheduler.py --dry-run          # 预览但不发布
  python3 scripts/publish_scheduler.py --once             # 只执行下一次，然后退出
"""

import json
import os
import sys
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "schedule.json"
POSTS_DIR = BASE_DIR / "posts"

DEFAULT_SCHEDULE = {
    "daily": {
        "times": ["08:00", "20:00"],
        "max_posts_per_run": 2,
        "enabled": True,
    }
}


def load_schedule() -> dict:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            print(f"⚠️ 配置文件格式错误: {CONFIG_FILE}，使用默认配置")
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_SCHEDULE, f, ensure_ascii=False, indent=2)
    print(f"📝 已创建默认配置文件: {CONFIG_FILE}")
    return DEFAULT_SCHEDULE


def find_next_scheduled_time(schedule: dict, now: datetime) -> datetime | None:
    daily = schedule.get("daily", {})
    times = daily.get("times", [])
    enabled = daily.get("enabled", True)
    if not enabled or not times:
        return None
    today = now.date()
    for t_str in times:
        hour, minute = map(int, t_str.split(":"))
        t = datetime(today.year, today.month, today.day, hour, minute)
        if t > now:
            return t
    tomorrow = today + timedelta(days=1)
    first = times[0]
    hour, minute = map(int, first.split(":"))
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, hour, minute)


def find_undistributed_posts() -> list[Path]:
    posts = []
    date_dirs = sorted(POSTS_DIR.glob("20*"))
    for date_dir in date_dirs:
        post_dirs = sorted(date_dir.glob("post-*"))
        for post_dir in post_dirs:
            checklist = post_dir / "publish-checklist.md"
            title_file = post_dir / "title.txt"
            if checklist.exists() and title_file.exists():
                content = checklist.read_text(encoding="utf-8")
                if "publish_date:" not in content:
                    posts.append(post_dir)
    return posts


def publish_post(post_dir: Path) -> bool:
    import subprocess
    title_file = post_dir / "title.txt"
    title = title_file.read_text(encoding="utf-8").strip() if title_file.exists() else "untitled"
    print(f"  发布: {title}")
    cmd = [
        sys.executable,
        str(BASE_DIR / "scripts" / "auto_publish.py"),
        "--post-dir", str(post_dir),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode == 0:
            print(f"  ✅ 发布成功: {title}")
            return True
        else:
            print(f"  ❌ 发布失败: {title}")
            print(f"     {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"  ⚠️ 发布超时: {title}")
        return False


def run_once(schedule: dict, dry_run: bool = False):
    posts = find_undistributed_posts()
    if not posts:
        print("📭 没有待发布的帖子")
        return
    max_posts = schedule.get("daily", {}).get("max_posts_per_run", 2)
    to_publish = posts[:max_posts]
    print(f"📤 准备发布 {len(to_publish)} 篇（还有 {len(posts) - len(to_publish)} 篇待发）")
    if dry_run:
        for post_dir in to_publish:
            title = (post_dir / "title.txt").read_text(encoding="utf-8").strip()
            print(f"  📋 [预览] {title} ({post_dir})")
        return
    success_count = 0
    for i, post_dir in enumerate(to_publish):
        if i > 0:
            import random
            delay = random.randint(180, 300)
            print(f"  等待 {delay} 秒后发布下一篇...")
            time.sleep(delay)
        if publish_post(post_dir):
            success_count += 1
    print(f"📊 本次发布完成: {success_count}/{len(to_publish)} 篇成功")


def run_daemon(schedule: dict):
    print("⏰ 调度器已启动，等待预定时间...")
    while True:
        now = datetime.now()
        next_time = find_next_scheduled_time(schedule, now)
        if next_time is None:
            print("❌ 调度未启用或没有配置时间")
            return
        wait_seconds = (next_time - now).total_seconds()
        if wait_seconds > 0:
            check_interval = 300
            while wait_seconds > 0:
                sleep_for = min(check_interval, wait_seconds)
                time.sleep(sleep_for)
                wait_seconds -= check_interval
        print(f"\n⏰ 预定时间 {next_time.strftime('%H:%M')}，开始发布...")
        run_once(schedule)
        print(f"📅 下次发布时间: {find_next_scheduled_time(schedule, datetime.now())}")


def main():
    parser = argparse.ArgumentParser(description="tape 定时发布调度器")
    parser.add_argument("--run-now", action="store_true", help="立即执行一次发布")
    parser.add_argument("--dry-run", action="store_true", help="预览但不发布")
    parser.add_argument("--once", action="store_true", help="只执行下一次，然后退出")
    args = parser.parse_args()
    schedule = load_schedule()
    print(f"📅 调度配置: {schedule.get('daily', {}).get('times', [])}")
    if args.dry_run:
        run_once(schedule, dry_run=True)
    elif args.run_now:
        run_once(schedule)
    elif args.once:
        now = datetime.now()
        next_time = find_next_scheduled_time(schedule, now)
        if next_time:
            wait = (next_time - now).total_seconds()
            if wait > 0:
                print(f"⏳ 等待 {int(wait)} 秒到 {next_time.strftime('%H:%M')}...")
                time.sleep(min(wait, 86400))
            run_once(schedule)
        else:
            print("❌ 没有可用的调度时间")
    else:
        run_daemon(schedule)


if __name__ == "__main__":
    main()
