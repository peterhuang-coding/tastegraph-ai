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

    # 6. Stealth crawl last run
    r = check_stealth_crawl()
    results["crawl_stealth"] = r
    if not r["ok"]:
        issues.append(f"⚠️  私有爬虫: {r.get('note', '未找到记录')}")

    # 7. Graph enrichment lag
    r = check_graph_enrichment()
    results["graph_enrichment"] = r
    if not r["ok"]:
        issues.append(f"⚠️  图谱丰富: {r.get('note', '滞后')}")

    # 8. Scrape success rate (24h)
    r = check_scrape_success_rate()
    results["scrape_rate_24h"] = r
    if not r["ok"]:
        issues.append(f"⚠️  抓取成功率: {r.get('note', '偏低')}")

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
        # Phase 6: new checks
        _print_result_section(results, issues)
        print()
        if issues:
            print("问题:")
            for i in issues:
                print(f"  {i}")
        else:
            print("🟢 全部正常")
        print(f"\n审稿台: http://127.0.0.1:8765")

# ── New checks (Phase 6) ──────────────────────────────────────

def check_stealth_crawl(hours: int = 30) -> dict:
    """Check when the stealth crawler last ran successfully."""
    stealth_dir = BASE_DIR / "runs"
    if not stealth_dir.exists():
        return {"ok": False, "note": "runs/ 目录不存在"}
    try:
        latest = None
        for d in sorted(stealth_dir.glob("stealth_*"), reverse=True):
            latest = d
            break
        if not latest:
            return {"ok": False, "note": "无 stealth crawl 运行记录"}
        # Check if output file exists
        out = latest / "output.jsonl"
        if not out.exists():
            return {"ok": False, "note": f"最近运行 {latest.name} 无产出文件"}
        # Check age
        mtime = datetime.fromtimestamp(out.stat().st_mtime, tz=timezone.utc)
        age_h = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
        if age_h > hours:
            return {"ok": False, "note": f"最近产出 {age_h:.0f}h 前（>{hours}h）"}
        return {"ok": True, "last_run": latest.name, "age_hours": round(age_h, 1)}
    except Exception as e:
        return {"ok": False, "note": str(e)}


def check_graph_enrichment(hours: int = 48) -> dict:
    """Check when the taste graph was last enriched."""
    graph_file = BASE_DIR / "data" / "taste_graph.json"
    if not graph_file.exists():
        return {"ok": False, "note": "taste_graph.json 不存在"}
    try:
        mtime = datetime.fromtimestamp(graph_file.stat().st_mtime, tz=timezone.utc)
        age_h = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
        if age_h > hours:
            return {"ok": False, "note": f"图谱 {age_h:.0f}h 未更新（>{hours}h）"}
        return {"ok": True, "age_hours": round(age_h, 1)}
    except Exception as e:
        return {"ok": False, "note": str(e)}


def check_scrape_success_rate(hours: int = 24) -> dict:
    """Check scrape success rate from DB failures in the last N hours."""
    db_path = BASE_DIR / "data" / "taste_graph.db"
    if not db_path.exists():
        return {"ok": True, "note": "DB 不存在，跳过"}
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cutoff = (datetime.now(timezone.utc) - __import__('datetime').timedelta(hours=hours)).isoformat()
        fail_count = conn.execute(
            "SELECT COUNT(*) FROM scrape_failures WHERE created_at >= ?", (cutoff,)
        ).fetchone()[0]
        # Count images added in the same period as a proxy for success
        img_count = conn.execute(
            "SELECT COUNT(*) FROM images WHERE created_at >= ?", (cutoff,)
        ).fetchone()[0]
        conn.close()

        if img_count == 0 and fail_count == 0:
            return {"ok": True, "note": "24h 内无抓取活动"}
        total = img_count + fail_count
        rate = img_count / total * 100 if total > 0 else 0
        if rate < 30 and total > 10:
            return {"ok": False, "rate_pct": round(rate, 1), "total": total,
                    "note": f"成功率 {rate:.0f}%（{img_count}/{total}）低于 30%"}
        return {"ok": True, "rate_pct": round(rate, 1), "total": total}
    except Exception as e:
        return {"ok": True, "note": f"无法检查: {e}"}


# ── Output helpers update ─────────────────────────────────────

def _print_result_section(results, issues):
    """Print the new Phase 6 checks."""
    for key, label in [
        ("crawl_stealth", "私有爬虫"),
        ("graph_enrichment", "图谱丰富"),
        ("scrape_rate_24h", "抓取成功率"),
    ]:
        if key in results:
            r = results[key]
            if r["ok"]:
                detail = r.get("age_hours", r.get("last_run", ""))
                rate = r.get("rate_pct", "")
                if rate:
                    print(f"  ✅ {label:12s} {rate}% ({r.get('total',0)} 次)")
                elif detail:
                    print(f"  ✅ {label:12s} {detail}h 前")
                else:
                    print(f"  ✅ {label:12s} OK")
            else:
                print(f"  ⚠️  {label:12s} {r.get('note', '?')}")


if __name__ == "__main__":
    main()
