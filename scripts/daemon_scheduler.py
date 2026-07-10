#!/usr/bin/env python3
"""
tape — 统一定时调度器
======================
集中管理所有定时任务，替代每个任务单独配置 launchd/cron。

用法:
  python3 scripts/daemon_scheduler.py              # 启动守护进程
  python3 scripts/daemon_scheduler.py --run-all    # 立即执行所有任务
  python3 scripts/daemon_scheduler.py --run backup # 立即执行指定任务

配置: config/schedule.json
日志: data/events.log
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "schedule.json"
EVENTS_LOG = BASE_DIR / "data" / "events.log"

CHECK_INTERVAL = 300  # 5 分钟
MAX_RETRIES = 3
RETRY_BASE_DELAY = 10  # 指数退避基数（秒）


def load_config() -> dict:
    """加载任务调度配置。"""
    if not CONFIG_FILE.exists():
        print(f"[scheduler] 配置文件不存在: {CONFIG_FILE}")
        sys.exit(1)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as exc:
        print(f"[scheduler] 配置文件解析失败: {exc}")
        sys.exit(1)


def get_tasks(config: dict) -> list[dict]:
    """获取启用的任务列表。"""
    tasks = config.get("tasks", [])
    return [t for t in tasks if t.get("enabled", True)]


def parse_schedule(schedule_str: str) -> tuple[str | None, str | None]:
    """解析调度时间字符串。

    支持格式:
      - "08:00"         -> 每天 08:00
      - "08:00,20:00"   -> 每天 08:00 和 20:00
      - "sun 03:00"     -> 每周日 03:00
      - "mon 10:00"     -> 每周一 10:00

    返回 (weekday, time_str)，weekday 为 None 表示每天。
    """
    parts = schedule_str.strip().split()
    if len(parts) == 1:
        return None, parts[0]
    elif len(parts) == 2:
        weekday = parts[0].lower()
        return weekday, parts[1]
    else:
        return None, parts[0]


WEEKDAY_MAP = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}


def should_run_now(task: dict, now: datetime) -> bool:
    """判断任务是否应该在此刻执行。

    检查任务的 schedule 是否匹配当前时间。
    每个任务在调度时间窗口内的 5 分钟检查周期内只触发一次。
    """
    schedule_str = task.get("schedule", "")
    weekday, time_str = parse_schedule(schedule_str)

    # 检查星期匹配
    if weekday is not None:
        target_wday = WEEKDAY_MAP.get(weekday)
        if target_wday is None or now.weekday() != target_wday:
            return False

    # 检查时间匹配：解析每个时间点，看当前是否在触发窗口内
    times = time_str.split(",")
    for t_str in times:
        t_str = t_str.strip()
        if ":" not in t_str:
            continue
        try:
            hour, minute = map(int, t_str.split(":"))
        except ValueError:
            continue

        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # 触发窗口：目标时间到目标时间 + CHECK_INTERVAL 秒之间
        window_end = target + timedelta(seconds=CHECK_INTERVAL)
        if target <= now < window_end:
            return True

    return False


def should_run_on_day(task: dict, today: datetime.date) -> bool:
    """判断任务在今天是否应该运行（用于 --run-all 的过滤）。"""
    schedule_str = task.get("schedule", "")
    weekday, _ = parse_schedule(schedule_str)
    if weekday is not None:
        target_wday = WEEKDAY_MAP.get(weekday)
        if target_wday is None or today.weekday() != target_wday:
            return False
    return True


def log_event(event_type: str, data: dict) -> None:
    """记录事件到 events.log。"""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "data": data,
    }
    EVENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(EVENTS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except IOError as exc:
        print(f"[scheduler] 写入日志失败: {exc}")


def run_task(task: dict, run_args: list[str] | None = None) -> bool:
    """通过 subprocess 执行单个任务。

    支持重试（指数退避），最多 MAX_RETRIES 次。
    返回 True 表示成功，False 表示所有重试均失败。
    """
    script = task["script"]
    script_path = BASE_DIR / script
    if not script_path.exists():
        print(f"[scheduler] 脚本不存在: {script_path}")
        log_event("scheduler.task_error", {
            "task": task["name"],
            "error": f"Script not found: {script_path}",
        })
        return False

    args = run_args if run_args is not None else task.get("args", [])
    cmd = [sys.executable, str(script_path)] + args
    name = task["name"]

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"[scheduler] [{name}] 执行 (尝试 {attempt}/{MAX_RETRIES}): {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode == 0:
                print(f"[scheduler] [{name}] 成功")
                log_event("scheduler.task_success", {
                    "task": name,
                    "attempt": attempt,
                    "script": script,
                })
                return True
            else:
                stderr_trunc = result.stderr[:300] if result.stderr else "(no stderr)"
                stdout_trunc = result.stdout[:200] if result.stdout else "(no stdout)"
                print(f"[scheduler] [{name}] 失败 (exit={result.returncode}): {stderr_trunc}")
                print(f"[scheduler] [{name}] stdout: {stdout_trunc}")
        except subprocess.TimeoutExpired:
            print(f"[scheduler] [{name}] 超时 (尝试 {attempt})")
        except OSError as exc:
            print(f"[scheduler] [{name}] 执行错误: {exc}")

        if attempt < MAX_RETRIES:
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            print(f"[scheduler] [{name}] 等待 {delay}s 后重试...")
            time.sleep(delay)

    print(f"[scheduler] [{name}] 重试 {MAX_RETRIES} 次均失败")
    log_event("scheduler.task_failed", {
        "task": name,
        "max_retries": MAX_RETRIES,
        "script": script,
    })
    return False


def run_all_tasks(config: dict) -> None:
    """立即执行所有启用的任务。"""
    tasks = get_tasks(config)
    print(f"[scheduler] 开始执行所有任务 ({len(tasks)} 个)")
    log_event("scheduler.run_all_start", {"task_count": len(tasks)})

    results = {}
    for task in tasks:
        success = run_task(task)
        results[task["name"]] = "success" if success else "failed"
        time.sleep(2)

    success_count = sum(1 for v in results.values() if v == "success")
    print(f"[scheduler] 所有任务执行完毕: {success_count}/{len(tasks)} 成功")
    log_event("scheduler.run_all_complete", {
        "results": results,
        "success_count": success_count,
        "total": len(tasks),
    })


def run_single_task(config: dict, task_name: str) -> None:
    """立即执行指定名称的任务。"""
    tasks = get_tasks(config)
    task = next((t for t in tasks if t["name"] == task_name), None)
    if task is None:
        print(f"[scheduler] 未找到任务: {task_name}")
        print(f"[scheduler] 可用任务: {[t['name'] for t in tasks]}")
        sys.exit(1)

    print(f"[scheduler] 开始执行任务: {task_name}")
    success = run_task(task)
    if success:
        print(f"[scheduler] [{task_name}] 执行完成")
    else:
        print(f"[scheduler] [{task_name}] 执行失败")
        sys.exit(1)


def run_daemon(config: dict) -> None:
    """守护进程主循环：每 5 分钟检查一次任务注册表。"""
    print(f"[scheduler] 调度器已启动 (检查间隔: {CHECK_INTERVAL}s)")
    log_event("scheduler.start", {"check_interval": CHECK_INTERVAL})

    # last_run 记录每个任务上次执行的时间点，防止重复触发
    last_run: dict[str, datetime] = {}

    while True:
        now = datetime.now()
        tasks = get_tasks(config)
        triggered = False

        for task in tasks:
            name = task["name"]
            if should_run_now(task, now):
                last = last_run.get(name)
                if last is not None and (now - last).total_seconds() < CHECK_INTERVAL:
                    continue

                print(f"[scheduler] 触发任务: {name}")
                last_run[name] = now
                triggered = True
                run_task(task)

        if not triggered:
            pass

        time.sleep(CHECK_INTERVAL)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="tape 统一定时调度器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 scripts/daemon_scheduler.py              # 启动守护进程\n"
            "  python3 scripts/daemon_scheduler.py --run-all    # 立即执行所有任务\n"
            "  python3 scripts/daemon_scheduler.py --run backup # 立即执行备份任务\n"
        ),
    )
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="立即执行所有启用的任务",
    )
    parser.add_argument(
        "--run",
        type=str,
        default=None,
        metavar="TASK_NAME",
        help="立即执行指定名称的任务",
    )
    return parser.parse_args(argv)


def main() -> None:
    """CLI 入口。"""
    args = parse_args()
    config = load_config()

    if args.run_all:
        run_all_tasks(config)
    elif args.run:
        run_single_task(config, args.run)
    else:
        run_daemon(config)


if __name__ == "__main__":
    main()
