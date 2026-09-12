#!/usr/bin/env python3
"""每日安全采集唯一入口（docs/data-contract.md §5）。

    python3 scripts/daily_ingestion.py               # 全链路
    python3 scripts/daily_ingestion.py --resume      # 中断/失败后按 run_id 恢复（幂等）
    python3 scripts/daily_ingestion.py --stage download --max 50   # 短跑调试：只跑下载

链路（固定顺序，唯一安全入口）:
    preflight → crawl → persist discovered → download backlog
    → normalize/source attach → generate at most one primary pack → run summary

不变量:
- 运行锁（fcntl.flock）：已有实例运行立即退出，不允许并发写同一数据库
- run_id 持久化在 crawl_runs；--resume 复用当天未完结 run，各阶段按 stages_json 幂等跳过
- 下载只消费 ingestion_items 持久 backlog；--max 只限本次处理量，绝不丢剩余项
- item 级 attempt_count/last_error；临时失败可重试（<MAX_ATTEMPTS），永久失败不再重试
- 去重 = 规范化 URL md5 + 内容 checksum（images.content_hash）
- 空候选正常结束（no_candidates），不崩溃
- 输出 data/daily_ingestion_status.json（结构化摘要，供工作台/明早验收）
- 绝不触碰小红书：不登录、不发布、不互动、不调用任何 XHS 脚本
"""
import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
from taste_graph_ai.services.provenance import (
    classify_page, ensure_provenance_schema, is_site_asset,
    link_downloaded_image, save_image_provenance,
)
# TASTEGRAPH_DB 仅用于 /tmp 副本演练；生产默认 data/taste_graph.db。
DB_PATH = Path(os.environ.get("TASTEGRAPH_DB", str(BASE_DIR / "data" / "taste_graph.db")))
IMAGES_DIR = BASE_DIR / "data" / "images"
RUNS_DIR = BASE_DIR / "runs"
LOCK_PATH = BASE_DIR / "data" / "ingestion.lock"
STATUS_PATH = BASE_DIR / "data" / "daily_ingestion_status.json"
MIN_FREE_BYTES = 1 << 30  # preflight 要求至少 1 GiB 空闲

# job_runs 关联：scheduler 拉起时传入 TASTEGRAPH_JOB_RUN_ID（行已建）；
# launchd/手动直跑时无此变量，本进程自建 job_runs 行。
JOB_NAME = os.environ.get("TASTEGRAPH_JOB_NAME", "daily_ingestion")

MAX_ATTEMPTS = 3          # 临时失败最大重试次数（超过视为永久失败）
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    return "run-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + os.urandom(3).hex()


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _norm_url(u: str) -> str:
    return u.split("?", 1)[0].split("#", 1)[0].rstrip("/").lower()


def resolve_source(page_url: str, sources: list[tuple[str, str]]) -> str | None:
    """Match URL scope first; use domain-only fallback only when unambiguous.

    Only www is normalized; unrelated subdomains and domain-prefix lookalikes
    do not acquire a source ID. Unknown domains remain NULL.
    """
    page = urlparse(page_url)
    if page.scheme not in {"http", "https"} or not page.hostname:
        return None
    domain = page.hostname.lower().removeprefix("www.")
    path = page.path.rstrip("/").lower()
    candidates = []
    for sid, surl in sources:
        source = urlparse(surl or "")
        if source.scheme not in {"http", "https"} or not source.hostname:
            continue
        if source.hostname.lower().removeprefix("www.") != domain:
            continue
        source_path = source.path.rstrip("/").lower()
        match = path == source_path or path.startswith(source_path + "/")
        candidates.append((len(source_path) + 1 if match else 0, sid))
    scoped = [candidate for candidate in candidates if candidate[0] > 0]
    if scoped:
        return max(scoped, key=lambda candidate: candidate[0])[1]
    return candidates[0][1] if len(candidates) == 1 else None


# ── run 记录 ────────────────────────────────────────────────

def find_resumable(con: sqlite3.Connection, today: str) -> str | None:
    cur = con.execute(
        "SELECT id FROM crawl_runs WHERE scheduled_for LIKE ? "
        "AND status IN ('pending','running','partial') ORDER BY started_at DESC LIMIT 1",
        (today + "%",),
    )
    row = cur.fetchone()
    return row[0] if row else None


def save_run(con: sqlite3.Connection, run: dict) -> None:
    con.execute(
        """INSERT OR REPLACE INTO crawl_runs
        (id, scheduled_for, started_at, finished_at, status,
         pages_attempted, pages_fetched, pages_failed,
         images_discovered, images_downloaded, backlog_count,
         error_summary, stages_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run["id"], run["scheduled_for"], run["started_at"], run["finished_at"],
            run["status"], run["pages_attempted"], run["pages_fetched"], run["pages_failed"],
            run["images_discovered"], run["images_downloaded"], run["backlog_count"],
            run["error_summary"], json.dumps(run["stages"], ensure_ascii=False),
        ),
    )
    con.commit()


def run_row(con: sqlite3.Connection, run_id: str) -> dict | None:
    cur = con.execute("SELECT * FROM crawl_runs WHERE id = ?", (run_id,))
    row = cur.fetchone()
    if not row:
        return None
    d = dict(zip([c[0] for c in cur.description], row))
    d["stages"] = json.loads(d.get("stages_json") or "{}")
    return d


# ── job_runs（调度态，契约 §1）──────────────────────────────

def new_job_run_id() -> str:
    return "job-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + os.urandom(2).hex()


def job_succeeded_today(con: sqlite3.Connection, today: str) -> bool:
    """当天该 job 是否已有成功终态（重启/重复触发不补跑成功任务）。"""
    try:
        cur = con.execute(
            "SELECT 1 FROM job_runs WHERE job_name = ? AND scheduled_date = ? "
            "AND status = 'succeeded' LIMIT 1",
            (JOB_NAME, today),
        )
        return cur.fetchone() is not None
    except sqlite3.Error:
        return False  # 表/列异常时不阻断（迁移会在 preflight 补齐）


def job_run_attach(con: sqlite3.Connection, run: dict, today: str) -> str:
    """把本次 ingestion 关联到 job_runs 行并置 running。

    scheduler 拉起时传 TASTEGRAPH_JOB_RUN_ID（行由 scheduler 预建）；
    否则自建一行。返回 job_run_id。
    """
    job_run_id = os.environ.get("TASTEGRAPH_JOB_RUN_ID", "") or new_job_run_id()
    ts = now_iso()
    log_path = os.environ.get("TASTEGRAPH_JOB_LOG_PATH", "")
    con.execute(
        """INSERT INTO job_runs
        (id, job_name, scheduled_for, scheduled_date, started_at, finished_at,
         status, summary_json, run_id, error_summary, pid, heartbeat_at, log_path)
        VALUES (?,?,?,?,?,NULL,'running','{}',?, '', ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            run_id=excluded.run_id, status='running', pid=excluded.pid,
            heartbeat_at=excluded.heartbeat_at, started_at=COALESCE(job_runs.started_at, excluded.started_at),
            log_path=COALESCE(NULLIF(excluded.log_path,''), job_runs.log_path)""",
        (job_run_id, JOB_NAME, run["scheduled_for"], today, ts,
         run["id"], os.getpid(), ts, log_path),
    )
    con.commit()
    return job_run_id


def job_run_heartbeat(con: sqlite3.Connection, job_run_id: str, run: dict) -> None:
    try:
        con.execute(
            "UPDATE job_runs SET heartbeat_at=?, run_id=?, pid=? WHERE id=?",
            (now_iso(), run["id"], os.getpid(), job_run_id),
        )
        con.commit()
    except sqlite3.Error:
        pass


def job_run_finish(con: sqlite3.Connection, job_run_id: str, run: dict, summary: dict) -> None:
    """终态回写：succeeded/partial 都是有效终态。"""
    try:
        con.execute(
            "UPDATE job_runs SET status=?, finished_at=?, error_summary=?, "
            "run_id=?, heartbeat_at=?, summary_json=? WHERE id=?",
            (run["status"], now_iso(), run.get("error_summary", ""), run["id"], now_iso(),
             json.dumps(summary, ensure_ascii=False)[:4000], job_run_id),
        )
        con.commit()
    except sqlite3.Error as e:
        print(f"[ingest] job_runs 终态回写失败（不阻断）: {e}")


def write_lock_meta(run_id: str = "") -> None:
    """锁文件内写 pid/心跳（fcntl 锁已持有时调用），供外部识别僵死实例。"""
    try:
        LOCK_PATH.write_text(json.dumps({
            "pid": os.getpid(),
            "run_id": run_id,
            "heartbeat_at": now_iso(),
        }, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ── preflight ───────────────────────────────────────────────

def preflight(con: sqlite3.Connection) -> list[str]:
    """返回错误列表；空列表 = 通过。"""
    errors = []
    usage = __import__("shutil").disk_usage(BASE_DIR)
    if usage.free < MIN_FREE_BYTES:
        errors.append(f"磁盘空间不足: {usage.free / 1e9:.1f} GiB < 1 GiB")
    try:
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("SELECT COUNT(*) FROM images")
    except sqlite3.Error as e:
        errors.append(f"数据库不可读: {e}")
    if not IMAGES_DIR.is_dir():
        try:
            IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            errors.append(f"图片目录不可写: {e}")
    return errors


# ── 阶段实现 ────────────────────────────────────────────────

def stage_crawl(args, run, con) -> dict:
    """crawl：调用 crawl_loop_6h（只做页面抓取与 URL 提取，不碰 XHS）。

    返回 {ok, pages:{attempted,fetched,failed}, new_loop_dirs:[...], error}。
    阶段成功后由 persist 消费新 loop 目录。
    """
    before = {str(p) for p in RUNS_DIR.glob("loop_*")} if RUNS_DIR.is_dir() else set()
    cmd = [sys.executable, "-u", str(BASE_DIR / "scripts" / "crawl_loop_6h.py"),
           "--duration-hours", str(args.duration_hours),
           "--rate-limit", str(args.rate_limit),
           "--max-discovered", str(args.max_discovered)]
    print(f"[ingest] crawl: {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, cwd=str(BASE_DIR), timeout=args.crawl_timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"crawl 超时 ({args.crawl_timeout}s)", "pages": {}}
    after = {str(p) for p in RUNS_DIR.glob("loop_*")} if RUNS_DIR.is_dir() else set()
    new_dirs = sorted(after - before)
    pages = {"attempted": 0, "fetched": 0, "failed": 0}
    for d in new_dirs:
        f = Path(d) / "output.jsonl"
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            pages["attempted"] += 1
            st = e.get("status")
            if st == "fetched":
                pages["fetched"] += 1
            elif st == "fetch_error":
                pages["failed"] += 1
    if r.returncode != 0:
        return {"ok": False, "error": f"crawl exit={r.returncode}", "pages": pages,
                "new_loop_dirs": new_dirs}
    return {"ok": True, "pages": pages, "new_loop_dirs": new_dirs}


def stage_persist(con, sources, run, loop_dirs, ctx) -> dict:
    """persist：把 crawl 产出的 fetched 记录（images:[{url,alt}]）写入 ingestion_items backlog。

    幂等：item id = run_id:md5(url)，INSERT OR IGNORE。
    """
    ensure_provenance_schema(con)
    discovered = 0
    files = []
    for d in loop_dirs:
        f = Path(d) / "output.jsonl"
        if f.exists():
            files.append(f)
    if not files:  # 兜底：按 mtime 找 crawl 开始后写出的 jsonl
        cutoff = ctx.get("crawl_started_ts", 0)
        files = [p for p in RUNS_DIR.glob("loop_*/output.jsonl")
                 if p.stat().st_mtime >= cutoff - 60]
    ts = now_iso()
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("status") != "fetched":
                continue
            imgs = e.get("images") or []
            if not imgs:
                # Historical alt_texts was independently filtered/truncated. Its
                # position cannot establish which image it describes.
                imgs = [{"url": u, "alt": ""} for u in e.get("image_urls") or []]
            fetched_page = e.get("page_url") or e.get("url") or ""
            canonical = e.get("canonical_url") or fetched_page
            # A site's generic canonical homepage must not replace a specific work.
            page_url = canonical if classify_page(canonical) == "detail" else fetched_page
            src = resolve_source(page_url, sources) or resolve_source(fetched_page, sources)
            for im in imgs:
                u = (im.get("url") or im.get("src") or "").strip()
                if urlparse(u).scheme not in {"http", "https"} or is_site_asset(u, im.get("alt") or ""):
                    continue
                uid = _md5(_norm_url(u))
                item_id = f"{run['id']}:{uid}"
                cur = con.execute(
                    "INSERT OR IGNORE INTO ingestion_items "
                    "(id, run_id, source_id, page_url, image_url, alt_text, status, "
                    "attempt_count, last_error, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (item_id, run["id"], src, page_url, u,
                     im.get("alt") or "", "discovered", 0, "", ts, ts),
                )
                if cur.rowcount:
                    discovered += 1
                save_image_provenance(con, uid, item_id, src, e, im, ts)
    con.commit()
    return {"discovered": discovered}


def stage_download(con, run, max_items: int) -> dict:
    """download：消费持久 backlog。--max 只限本次量；item 级失败计数。"""
    ensure_provenance_schema(con)
    sources = con.execute("SELECT id, url FROM sources").fetchall()
    downloaded = inserted = 0
    transient = permanent = 0
    rows = con.execute(
        "SELECT id, source_id, page_url, image_url, alt_text, attempt_count "
        "FROM ingestion_items WHERE status IN ('discovered','failed') "
        "AND attempt_count < ? ORDER BY created_at LIMIT ?",
        (MAX_ATTEMPTS, max_items),
    ).fetchall()
    for row in rows:
        item_id, source_id, page_url, url, alt, attempts = row
        # Backlog may contain stale/orphan IDs from an older producer. Resolve only
        # the item being consumed; never rewrite existing images or global data.
        source_id = resolve_source(page_url, sources)
        uid = _md5(_norm_url(url))
        if con.execute("SELECT COUNT(*) FROM images WHERE id = ?", (uid,)).fetchone()[0]:
            link_downloaded_image(con, uid, uid)
            con.execute("UPDATE ingestion_items SET status='skipped', updated_at=? WHERE id=?",
                        (now_iso(), item_id))
            continue
        ext = Path(url.split("?", 1)[0]).suffix.lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        dest = IMAGES_DIR / f"{uid}{ext}"
        if not dest.exists():
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.google.com/"})
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                if len(data) < 2000:
                    raise OSError("body too small (<2000B)")
                dest.write_bytes(data)
            except Exception as e:
                attempts += 1
                if attempts >= MAX_ATTEMPTS:
                    permanent += 1
                else:
                    transient += 1
                con.execute(
                    "UPDATE ingestion_items SET status='failed', attempt_count=?, "
                    "last_error=?, updated_at=? WHERE id=?",
                    (attempts, str(e)[:200], now_iso(), item_id),
                )
                con.commit()
                continue
        # Preserve downloaded source bytes; any platform conversion belongs in a separate export.
        # 内容 checksum 去重（契约 §1：规范化 URL + 内容 checksum）
        try:
            content_hash = hashlib.sha256(dest.read_bytes()).hexdigest()[:16]
        except OSError:
            content_hash = ""
        duplicate = con.execute("SELECT id FROM images WHERE content_hash = ? LIMIT 1",
                                (content_hash,)).fetchone() if content_hash else None
        if duplicate:
            link_downloaded_image(con, uid, duplicate[0])
            dest.unlink(missing_ok=True)
            con.execute("UPDATE ingestion_items SET status='skipped', updated_at=? WHERE id=?",
                        (now_iso(), item_id))
            con.commit()
            continue
        keywords = [a.strip()[:40] for a in (alt or "").split("|") if a.strip()][:5]
        cur = con.execute(
            "INSERT OR IGNORE INTO images (id, source_id, url, page_url, local_path, "
            "thumbnail_path, keywords_json, graph_score, visual_score, final_score, "
            "status, created_at, content_hash) "
            "VALUES (?,?,?,?,?, '', ?, 0.0, 0.0, 0.3, 'pending', datetime('now'), ?)",
            (uid, source_id, url, page_url, str(dest),
             json.dumps(keywords, ensure_ascii=False), content_hash),
        )
        if cur.rowcount:
            link_downloaded_image(con, uid, uid)
            inserted += 1
            downloaded += 1
            con.execute("UPDATE ingestion_items SET status='downloaded', updated_at=? WHERE id=?",
                        (now_iso(), item_id))
        else:
            con.execute("UPDATE ingestion_items SET status='skipped', updated_at=? WHERE id=?",
                        (now_iso(), item_id))
        con.commit()
        time.sleep(1.2)  # 礼貌间隔
    con.execute(
        "UPDATE ingestion_items SET status='skipped' WHERE status='failed' AND attempt_count >= ?",
        (MAX_ATTEMPTS,),
    )
    con.commit()
    return {"downloaded": downloaded, "inserted": inserted,
            "transient_failed": transient, "permanent_failed": permanent}


def stage_pack(con, args) -> dict:
    """pack：今天已有未完成包则不堆积；无候选正常结束（no_candidates）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    posts_today = BASE_DIR / "posts" / today
    existing = list(posts_today.glob("pack-*")) if posts_today.is_dir() else []
    if existing:
        return {"pack_generated": False, "reason": "today already has packs"}
    candidates = con.execute(
        "SELECT COUNT(*) FROM images WHERE status='pending' AND local_path != ''"
    ).fetchone()[0]
    if candidates == 0:
        return {"pack_generated": False, "reason": "no_candidates"}
    cmd = [sys.executable, "-u", str(BASE_DIR / "scripts" / "generate_publish_packs.py"),
           "--date", today, "--count", "1", "--pack-size", "9"]
    print(f"[ingest] pack: {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, cwd=str(BASE_DIR), timeout=1800)
    except subprocess.TimeoutExpired:
        return {"pack_generated": False, "reason": "pack generation timeout"}
    if r.returncode == 0:
        return {"pack_generated": True, "reason": ""}
    return {"pack_generated": False, "reason": f"pack exit={r.returncode}"}


# ── 主流程 ──────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="每日安全采集唯一入口")
    ap.add_argument("--resume", action="store_true", help="复用当天未完结 run_id 恢复")
    ap.add_argument("--stage", default="all",
                    choices=["all", "crawl", "persist", "download", "pack", "summary"],
                    help="只跑指定阶段（短跑调试）")
    ap.add_argument("--max", type=int, default=400, help="下载阶段单次最多处理 item 数")
    ap.add_argument("--duration-hours", type=int, default=4)
    ap.add_argument("--rate-limit", type=int, default=400)
    ap.add_argument("--max-discovered", type=int, default=200)
    ap.add_argument("--crawl-timeout", type=int, default=21600)
    ap.add_argument("--force", action="store_true",
                    help="当天已成功也强制重跑（默认成功日跳过，重启不补跑）")
    args = ap.parse_args()
    requested_stage = args.stage

    # ── 运行锁：已有实例立即退出 ──
    lock_f = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[ingest] 已有采集实例在运行，立即退出。")
        return 2
    write_lock_meta()

    con = sqlite3.connect(str(DB_PATH))
    con.execute("PRAGMA busy_timeout=5000")

    # ── preflight（含幂等迁移）──
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    import migrations
    migrations.DB_PATH = DB_PATH
    migrations.REPORT_DIR = BASE_DIR / "data"
    m = migrations.apply_migrations(con)
    if any(e["status"] == "failed" for e in m):
        print("[ingest] 迁移失败，中止。")
        return 3
    errors = preflight(con)
    if errors:
        print("[ingest] preflight 失败:")
        for e in errors:
            print(f"  - {e}")
        return 3
    ensure_provenance_schema(con)
    con.commit()

    today = datetime.now().strftime("%Y-%m-%d")
    sources = con.execute("SELECT id, url FROM sources").fetchall()

    # ── 当天已成功 → 幂等跳过（重启/重复触发不补跑成功任务；--force 可覆盖）──
    if args.stage == "all" and not args.force and job_succeeded_today(con, today):
        print(f"[ingest] {JOB_NAME} 今天已成功完成（job_runs 终态 succeeded），跳过。"
              "如需重跑加 --force。")
        return 0

    # ── run 实例：--resume 复用当天未完结 run，否则新建 ──
    run = None
    if args.resume:
        rid = find_resumable(con, today)
        if rid:
            row = run_row(con, rid)
            run = {
                "id": row["id"], "scheduled_for": row["scheduled_for"],
                "started_at": now_iso(), "finished_at": None, "status": "running",
                "pages_attempted": row["pages_attempted"], "pages_fetched": row["pages_fetched"],
                "pages_failed": row["pages_failed"],
                "images_discovered": row["images_discovered"],
                "images_downloaded": row["images_downloaded"],
                "backlog_count": 0, "error_summary": "",
                "stages": row["stages"],
            }
            print(f"[ingest] --resume 复用 run: {run['id']}（已完成阶段: {sorted(run['stages'])}）")
        else:
            print("[ingest] --resume: 当天无未完结 run，新建。")
    if run is None:
        run = {
            "id": new_run_id(),
            "scheduled_for": f"{today}T03:00:00+08:00",
            "started_at": now_iso(), "finished_at": None, "status": "running",
            "pages_attempted": 0, "pages_fetched": 0, "pages_failed": 0,
            "images_discovered": 0, "images_downloaded": 0,
            "backlog_count": 0, "error_summary": "",
            "stages": {},
        }
        print(f"[ingest] 新 run: {run['id']}")
    stages = run["stages"]
    save_run(con, run)

    # ── 关联 job_runs（scheduler 预建行或本进程自建）──
    job_run_id = job_run_attach(con, run, today)
    write_lock_meta(run["id"])
    print(f"[ingest] job_runs 关联: {job_run_id}")

    errors_acc: list[str] = []
    ctx: dict = {}

    def mark_stage(name: str) -> None:
        stages[name] = "done"
        run["stages"] = stages
        save_run(con, run)
        write_lock_meta(run["id"])
        job_run_heartbeat(con, job_run_id, run)

    # ── crawl ──
    if args.stage in ("all", "crawl"):
        if stages.get("crawl") == "done":
            print("[ingest] crawl 阶段已完成，跳过")
        else:
            ctx["crawl_started_ts"] = time.time()
            out = stage_crawl(args, run, con)
            if out["pages"]:
                run["pages_attempted"] += out["pages"].get("attempted", 0)
                run["pages_fetched"] += out["pages"].get("fetched", 0)
                run["pages_failed"] += out["pages"].get("failed", 0)
            if out.get("ok"):
                mark_stage("crawl")
                ctx["loop_dirs"] = out.get("new_loop_dirs", [])
            else:
                errors_acc.append(f"crawl: {out.get('error', 'unknown')}")
                run["status"] = "partial"
                save_run(con, run)
                ctx["loop_dirs"] = out.get("new_loop_dirs", [])
            if out.get("ok") is False and not ctx.get("loop_dirs"):
                print("[ingest] crawl 失败且无新产出，跳过后续阶段。")
                args.stage = "summary"
    else:
        ctx["loop_dirs"] = []

    # ── persist ──
    if args.stage in ("all", "persist") and args.stage != "summary":
        if stages.get("persist") == "done":
            print("[ingest] persist 阶段已完成，跳过")
        else:
            out = stage_persist(con, sources, run, ctx.get("loop_dirs", []), ctx)
            run["images_discovered"] += out["discovered"]
            print(f"[ingest] persist: 新增 backlog {out['discovered']} 项")
            mark_stage("persist")

    # ── download（crawl 成功/partial 且 persist 有产出后消费 backlog）──
    if args.stage in ("all", "download") and args.stage != "summary":
        out = stage_download(con, run, args.max)
        run["images_downloaded"] += out["downloaded"]
        print(f"[ingest] download: 下载 {out['downloaded']}，入库 {out['inserted']}，"
              f"临时失败 {out['transient_failed']}，永久失败 {out['permanent_failed']}")
        mark_stage("download")

    # ── pack（至多一个主包）──
    if args.stage in ("all", "pack"):
        if stages.get("pack") == "done":
            print("[ingest] pack 阶段已完成，跳过")
        else:
            out = stage_pack(con, args)
            ctx["pack"] = out
            if out["reason"] == "no_candidates":
                print("[ingest] pack: no_candidates（正常结束）")
            elif not out["pack_generated"] and out["reason"] != "today already has packs":
                errors_acc.append(f"pack: {out['reason']}")
            mark_stage("pack")

    # ── summary ──
    # Every invoked stage closes its run/job, including --stage download.
    backlog = con.execute(
        "SELECT COUNT(*) FROM ingestion_items WHERE status IN ('discovered','failed')"
    ).fetchone()[0]
    run["backlog_count"] = backlog
    run["finished_at"] = now_iso()
    # A successful isolated stage is a completed partial run. It must not make
    # job_succeeded_today() suppress the full scheduled daily pipeline.
    run["status"] = "succeeded" if not errors_acc and requested_stage == "all" else "partial"
    run["error_summary"] = "; ".join(errors_acc)[:400]
    save_run(con, run)

    summary = {
        "requested_stage": requested_stage,
        "job_run_id": job_run_id,
        "run_id": run["id"],
        "scheduled_for": run["scheduled_for"],
        "status": run["status"],
        "pages_attempted": run["pages_attempted"],
        "pages_fetched": run["pages_fetched"],
        "pages_failed": run["pages_failed"],
        "images_discovered": run["images_discovered"],
        "images_downloaded": run["images_downloaded"],
        "images_inserted": run["images_downloaded"],  # 本入口下载即入库；失败项单独计
        "backlog_count": run["backlog_count"],
        "pack_generated": bool(ctx.get("pack", {}).get("pack_generated")),
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "error_summary": run["error_summary"],
    }
    STATUS_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[ingest] 摘要已写: {STATUS_PATH}")
    job_run_finish(con, job_run_id, run, summary)

    con.close()
    return 0  # succeeded 与 partial 都是有效终态；硬失败已在锁/preflight/迁移处非零返回


if __name__ == "__main__":
    sys.exit(main())
