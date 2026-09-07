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
事件日志: data/events.log（5MB 轮转，保留 .1）
worker 日志: data/logs/<job>-<ts>.log（14 天清理）
调度状态: job_runs 表（契约 §1）— “今天是否已跑”以数据库为准，重启不补跑成功任务。

守护模式下任务以 detached 子进程运行（start_new_session），长 crawl 不阻塞
调度循环；worker pid/心跳落 job_runs，进程消失自动标记 failed，下次触发
以 --resume 幂等补跑。运行锁（daily_ingestion fcntl flock）是并发终极防线。
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "schedule.json"
DATA_DIR = BASE_DIR / "data"
EVENTS_LOG = DATA_DIR / "events.log"
LOGS_DIR = DATA_DIR / "logs"
# TASTEGRAPH_DB 仅用于 /tmp 副本演练；生产默认 data/taste_graph.db。
DB_PATH = Path(os.environ.get("TASTEGRAPH_DB", str(DATA_DIR / "taste_graph.db")))

CHECK_INTERVAL = 300  # 5 分钟
MAX_RETRIES = 3
RETRY_BASE_DELAY = 10  # 指数退避基数（秒，仅 --run/--run-all 前台模式）
LOG_RETENTION_DAYS = 14          # data/logs/ 旧日志保留天数
EVENTS_LOG_MAX_BYTES = 5 << 20   # events.log 超过 5MB 轮转为 .1
RETRY_BACKOFF_MINUTES = 30       # 失败任务再次触发的最小间隔（任务可覆盖）
TERMINAL_STATUSES = ("succeeded", "partial", "skipped")  # 当天不再补跑的终态


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    elif not parts:
        return None, None
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


# ── job_runs 持久化（契约 §1：今天是否已跑以数据库为准）────────

def open_db() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.execute("PRAGMA busy_timeout=5000")
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    """服务启动前跑幂等迁移（契约 §0.6：采集入口与服务启动前都应迁移）。"""
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    import migrations
    migrations.DB_PATH = DB_PATH
    migrations.REPORT_DIR = DATA_DIR
    report = migrations.apply_migrations(con)
    failed = [e for e in report if e["status"] == "failed"]
    if failed:
        print(f"[scheduler] 迁移失败: {failed}")
        log_event("scheduler.migration_failed", {"entries": failed})


def pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def pid_runs_script(pid: int, script_hint: str) -> bool:
    """pid 存活且命令行仍包含本任务脚本名（防 pid 复用误判）。"""
    if not pid_alive(pid):
        return False
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except OSError:
        return True  # ps 不可用时退回 pid 判断
    return script_hint in out if out else False


def new_job_run_id() -> str:
    return "job-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + os.urandom(2).hex()


def latest_job_row(con: sqlite3.Connection, name: str, today: str, slot: str) -> dict | None:
    """该 (job, 日期, 时点) 最新一行。slot 如 "03:00"，匹配 scheduled_for 的时分。"""
    cur = con.execute(
        "SELECT * FROM job_runs WHERE job_name=? AND scheduled_date=? "
        "AND scheduled_for LIKE ? ORDER BY started_at DESC LIMIT 1",
        (name, today, f"{today}T{slot}:%"),
    )
    row = cur.fetchone()
    if not row:
        return None
    return dict(zip([c[0] for c in cur.description], row))


def mark_dead(con: sqlite3.Connection, job_id: str, pid: int, name: str) -> None:
    con.execute(
        "UPDATE job_runs SET status='failed', finished_at=?, error_summary=? WHERE id=?",
        (now_iso(), f"worker 进程已消失（pid={pid}），中断；下次触发以 --resume 幂等补跑", job_id),
    )
    con.commit()
    log_event("scheduler.reap_dead", {"job": name, "pid": pid, "job_run_id": job_id})


def reap_dead_runs(con: sqlite3.Connection, tasks: list[dict]) -> int:
    """status=running 但 worker 进程已消失 → 标记 failed，允许补跑。"""
    script_by_name = {t["name"]: Path(t.get("script", "")).name for t in tasks}
    rows = con.execute(
        "SELECT id, job_name, pid FROM job_runs WHERE status='running'"
    ).fetchall()
    reaped = 0
    for job_id, name, pid in rows:
        hint = script_by_name.get(name, "")
        dead = (not pid_runs_script(pid, hint)) if hint else (not pid_alive(pid))
        if dead:
            mark_dead(con, job_id, pid, name)
            reaped += 1
    return reaped


def already_done(con: sqlite3.Connection, task: dict, slot: str, today: str) -> bool:
    """今天该时点是否已处理：成功终态/仍在运行→跳过；失败在退避期内→跳过。"""
    row = latest_job_row(con, task["name"], today, slot)
    if row is None:
        return False
    status = row.get("status")
    if status in TERMINAL_STATUSES:
        return True
    if status == "running":
        hint = Path(task.get("script", "")).name
        alive = pid_runs_script(row.get("pid", 0), hint) if hint else pid_alive(row.get("pid", 0))
        if alive:
            return True  # 长 crawl 还在跑，不重复触发
        mark_dead(con, row["id"], row.get("pid", 0), task["name"])
        return False
    if status == "failed":
        backoff = int(task.get("retry_backoff_minutes", RETRY_BACKOFF_MINUTES))
        ts = row.get("finished_at") or row.get("started_at")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - dt < timedelta(minutes=backoff):
                    return True
            except ValueError:
                pass
        return False
    return False  # pending/未知 → 允许触发


# ── detached worker ─────────────────────────────────────────

def tail_log(path: Path, max_chars: int = 400) -> str:
    try:
        data = path.read_bytes()[-max_chars:].decode("utf-8", errors="ignore")
        return " ".join(data.split())[:max_chars]
    except OSError:
        return ""


def spawn_worker(con: sqlite3.Connection, task: dict, slot: str, today: str,
                 target: datetime) -> dict | None:
    """detached 子进程执行任务，完全脱离调度循环（长任务不阻塞）。

    job_runs 行先建（running + log_path），pid 在 Popen 后回写；
    TASTEGRAPH_JOB_RUN_ID 传给 worker，daily_ingestion 会自行回写终态。
    """
    script_path = BASE_DIR / task["script"]
    if not script_path.exists():
        print(f"[scheduler] 脚本不存在: {script_path}")
        log_event("scheduler.task_error", {"task": task["name"], "error": "script not found"})
        return None
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = LOGS_DIR / f"{task['name']}-{ts}.log"
    job_id = new_job_run_id()
    con.execute(
        "INSERT INTO job_runs (id, job_name, scheduled_for, scheduled_date, started_at, "
        "status, summary_json, run_id, error_summary, pid, heartbeat_at, log_path) "
        "VALUES (?,?,?,?,?, 'running', '{}', '', '', 0, ?, ?)",
        (job_id, task["name"], target.isoformat(), today, now_iso(), now_iso(), str(log_path)),
    )
    con.commit()

    env = os.environ.copy()
    env["TASTEGRAPH_JOB_RUN_ID"] = job_id
    env["TASTEGRAPH_JOB_NAME"] = task["name"]
    env["TASTEGRAPH_JOB_LOG_PATH"] = str(log_path)
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [sys.executable, "-u", str(script_path)] + task.get("args", [])
    log_f = open(log_path, "ab")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL,
            stdout=log_f, stderr=subprocess.STDOUT,
            start_new_session=True, env=env,
        )
    except OSError as exc:
        log_f.close()
        con.execute(
            "UPDATE job_runs SET status='failed', finished_at=?, error_summary=? WHERE id=?",
            (now_iso(), f"spawn 失败: {exc}"[:200], job_id),
        )
        con.commit()
        print(f"[scheduler] [{task['name']}] spawn 失败: {exc}")
        return None
    con.execute("UPDATE job_runs SET pid=? WHERE id=?", (proc.pid, job_id))
    con.commit()
    print(f"[scheduler] [{task['name']}] detached worker pid={proc.pid} 日志={log_path.name}")
    log_event("scheduler.spawn", {
        "task": task["name"], "slot": slot, "pid": proc.pid,
        "job_run_id": job_id, "log": str(log_path),
    })
    return {"proc": proc, "job_id": job_id, "log": log_path, "log_f": log_f, "task": task}


def poll_workers(con: sqlite3.Connection, active: dict) -> None:
    """收集本调度进程拉起的 worker 终态；daily_ingestion 自回写终态则尊重之。"""
    for name, w in list(active.items()):
        rc = w["proc"].poll()
        if rc is None:
            continue
        try:
            w["log_f"].close()
        except OSError:
            pass
        cur = con.execute("SELECT status, error_summary FROM job_runs WHERE id=?",
                          (w["job_id"],)).fetchone()
        db_status = cur[0] if cur else None
        if db_status in TERMINAL_STATUSES:
            status, err = db_status, (cur[1] if cur else "")
        elif rc == 0:
            status, err = "succeeded", ""
        elif rc == 2:  # daily_ingestion 锁竞争：已有实例在跑
            status, err = "skipped", "已有实例持锁运行，跳过"
        else:
            status = "failed"
            err = f"exit={rc}; " + tail_log(w["log"])
        if db_status == "running" or db_status is None:
            con.execute(
                "UPDATE job_runs SET status=?, finished_at=?, error_summary=? "
                "WHERE id=? AND status='running'",
                (status, now_iso(), err[:400], w["job_id"]),
            )
            con.commit()
        print(f"[scheduler] [{name}] worker 退出 rc={rc} → {status}")
        log_event("scheduler.worker_exit", {"task": name, "rc": rc, "status": status})
        del active[name]


# ── 日志轮转 ────────────────────────────────────────────────

def rotate_logs() -> None:
    """data/logs/*.log 按 14 天清理；events.log 超 5MB 轮转为 .1。"""
    cutoff = time.time() - LOG_RETENTION_DAYS * 86400
    if LOGS_DIR.is_dir():
        for p in LOGS_DIR.glob("*.log"):
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
                    print(f"[scheduler] 轮转删除旧日志: {p.name}")
            except OSError:
                pass
    try:
        if EVENTS_LOG.exists() and EVENTS_LOG.stat().st_size > EVENTS_LOG_MAX_BYTES:
            EVENTS_LOG.replace(EVENTS_LOG.with_name("events.log.1"))
    except OSError:
        pass


def run_task(task: dict, run_args: list[str] | None = None) -> bool:
    """前台同步执行单个任务（仅 --run/--run-all 手动模式）。

    支持重试（指数退避），最多 MAX_RETRIES 次。守护模式走 spawn_worker。
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
    cmd = [sys.executable, "-u", str(script_path)] + args
    name = task["name"]

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"[scheduler] [{name}] 执行 (尝试 {attempt}/{MAX_RETRIES}): {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                capture_output=False,
                text=True,
                timeout=task.get("timeout", 600),
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
                print(f"[scheduler] [{name}] 失败 (exit={result.returncode})")
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


def due_targets(task: dict, now: datetime) -> list[tuple[str, datetime]]:
    """返回任务今天已到点的调度目标 [(时间字符串, 目标时刻)]。

    允许机器睡眠错过触发窗口后醒来补跑；过旧的目标由宽限期过滤。
    """
    schedule_str = task.get("schedule", "")
    weekday, time_str = parse_schedule(schedule_str)
    if weekday is not None and now.weekday() != WEEKDAY_MAP.get(weekday):
        return []
    if not time_str:
        return []
    targets = []
    for t_str in time_str.split(","):
        t_str = t_str.strip()
        if ":" not in t_str:
            continue
        try:
            hour, minute = map(int, t_str.split(":"))
        except ValueError:
            continue
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= target:
            targets.append((t_str, target))
    return targets


def run_daemon(config: dict) -> None:
    """守护进程主循环：每 5 分钟检查一次任务注册表。

    - “今天是否已跑”查 job_runs 表（重启不补跑成功任务）
    - 任务以 detached worker 运行，长 crawl 不阻塞循环
    - running 但进程已死的行自动 reap 为 failed，下次触发 --resume 补跑
    - 机器睡眠错过触发窗口，醒来后补跑未超宽限期的任务（默认 3h，
      schedule.json 可用 catchup_grace_minutes 覆盖）
    """
    print(f"[scheduler] 调度器已启动 (检查间隔: {CHECK_INTERVAL}s, DB: {DB_PATH})")
    con = open_db()
    ensure_schema(con)
    log_event("scheduler.start", {"check_interval": CHECK_INTERVAL})

    active: dict[str, dict] = {}  # job_name → worker 句柄（本调度进程生命周期内）

    while True:
        try:
            # 每轮重读配置：schedule.json 改动无需重启 daemon 即生效
            config = load_config()
            tasks = get_tasks(config)

            poll_workers(con, active)
            reap_dead_runs(con, tasks)

            for task in tasks:
                name = task["name"]
                if name in active:
                    continue  # 本进程已拉起且在跑
                now = datetime.now()  # 每任务刷新，长任务后不用旧时间判断
                today = now.strftime("%Y-%m-%d")
                for t_str, target in due_targets(task, now):
                    grace = timedelta(minutes=task.get("catchup_grace_minutes", 180))
                    if now - target > grace:
                        continue
                    if already_done(con, task, t_str, today):
                        continue

                    print(f"[scheduler] 触发任务: {name} ({t_str})")
                    log_event("scheduler.trigger", {"task": name, "time": t_str})
                    worker = spawn_worker(con, task, t_str, today, target)
                    if worker:
                        active[name] = worker
                    break

            rotate_logs()
        except sqlite3.Error as exc:
            print(f"[scheduler] 数据库错误: {exc}，5s 后重连")
            log_event("scheduler.db_error", {"error": str(exc)[:200]})
            try:
                con.close()
            except sqlite3.Error:
                pass
            time.sleep(5)
            try:
                con = open_db()
            except sqlite3.Error as exc2:
                print(f"[scheduler] 重连失败: {exc2}")

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
