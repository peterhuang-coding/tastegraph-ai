#!/usr/bin/env python3
"""
TasteGraph AI — 一键健康检查
用法: python3 scripts/health_check.py [--json]
输出到 stdout，退出码 0=一切正常 1=有问题
"""
import json, os, subprocess, sys, time
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).resolve().parent.parent
EVENTS_LOG = BASE_DIR / "data" / "events.log"

REQUIRED_PROCS = [
    ("taste_graph_ai.server", "主服务器"),
]
SCHEDULED_PROCS = [
    ("daemon_scheduler.py", "调度器"),
    ("queue_server.py", "审稿台"),
]

def check_process(name: str) -> dict:
    try:
        r = subprocess.run(["pgrep", "-f", name], capture_output=True, text=True)
        pids = [p for p in r.stdout.strip().split("\n") if p]
        return {"ok": len(pids) > 0, "pids": pids, "name": name}
    except Exception:
        return {"ok": False, "pids": [], "name": name}

def check_port(port: int) -> dict:
    try:
        r = subprocess.run(["lsof", "-i", f":{port}"], capture_output=True, text=True)
        listening = "LISTEN" in r.stdout
        return {"ok": listening, "port": port}
    except Exception:
        return {"ok": False, "port": port}

def check_last_event(hours: int = 6) -> dict:
    if not EVENTS_LOG.exists():
        return {"ok": False, "error": "events.log 不存在"}
    try:
        lines = EVENTS_LOG.read_text().strip().split("\n")
        if not lines:
            return {"ok": False, "error": "events.log 为空"}
        last = json.loads(lines[-1])
        ts = datetime.fromisoformat(last["ts"])
        age = datetime.now(timezone.utc) - ts
        recent = age.total_seconds() < hours * 3600
        return {"ok": recent, "last_event": last, "age_minutes": round(age.total_seconds()/60)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def check_git() -> dict:
    try:
        r = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, cwd=BASE_DIR)
        dirty = bool(r.stdout.strip())
        r2 = subprocess.run(["git", "log", "--oneline", "-1"], capture_output=True, text=True, cwd=BASE_DIR)
        return {"ok": not dirty, "dirty": dirty, "last_commit": r2.stdout.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def main():
    results = {}
    issues = []

    # 1. 核心进程
    for name, label in REQUIRED_PROCS:
        r = check_process(name)
        results[f"process:{label}"] = r
        if not r["ok"]:
            issues.append(f"❌ {label} 未运行")

    # 2. 调度进程 (至少一个)
    sched_ok = False
    for name, label in SCHEDULED_PROCS:
        r = check_process(name)
        results[f"process:{label}"] = r
        if r["ok"]:
            sched_ok = True
    if not sched_ok:
        issues.append("❌ 调度器未运行")

    # 3. 端口
    ports = {8765: "审稿台", 8787: "API 服务器", 9222: "Chrome CDP"}
    for port, label in ports.items():
        r = check_port(port)
        results[f"port:{label}"] = r
        if not r["ok"]:
            issues.append(f"⚠️  端口 {port} ({label}) 无 LISTEN")

    # 4. 最近事件
    r = check_last_event(hours=24)
    results["events"] = r
    if not r["ok"]:
        issues.append(f"❌ 事件日志异常: {r.get('error','?')}")
    elif r.get("age_minutes", 0) > 720:
        issues.append(f"⚠️  最近事件 {r['age_minutes']} 分钟前（>12h）")

    # 5. Git
    r = check_git()
    results["git"] = r
    if r.get("dirty"):
        issues.append("⚠️  有未提交改动")

    # Output
    if "--json" in sys.argv:
        print(json.dumps({"healthy": len(issues)==0, "issues": issues, "details": results}, ensure_ascii=False, indent=2))
    else:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"TasteGraph AI 健康检查 — {ts}")
        print("=" * 50)
        for key, val in results.items():
            if "process" in key:
                status = "✅" if val["ok"] else "❌"
                pid_str = ",".join(val.get("pids", [])) or "无"
                print(f"  {status} {key.split(':')[1]:12s} PID={pid_str}")
        for key, val in results.items():
            if "port" in key:
                status = "✅" if val["ok"] else "⚠️"
                print(f"  {status} {key.split(':')[1]:12s} port={val['port']}")
        if "events" in results:
            e = results["events"]
            if e["ok"]:
                print(f"  ✅ 事件日志       最近 {e.get('age_minutes',0)} 分钟前")
            else:
                print(f"  ❌ 事件日志       {e.get('error','异常')}")
        if "git" in results:
            g = results["git"]
            if g["ok"]:
                print(f"  ✅ Git            {g['last_commit'][:50]}")
            else:
                print(f"  ⚠️  Git            有未提交改动")
        print()
        if issues:
            print("问题:")
            for i in issues:
                print(f"  {i}")
        else:
            print("🟢 全部正常")
        print(f"\n审稿台: http://127.0.0.1:8765")

    sys.exit(0 if len(issues) == 0 else 1)

if __name__ == "__main__":
    main()
