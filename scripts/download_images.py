#!/usr/bin/env python3
"""图片下载器 — 把爬虫 output.jsonl 里提取到的 image_urls 落盘并入图谱。

爬虫（crawl_loop_6h）只做页面抓取和 URL 提取，图片下载此前缺失（images 目录
从 2026-08-19 起停涨）。本脚本补上这一步：

    python3 scripts/download_images.py            # 处理最新一个 loop 的 output.jsonl
    python3 scripts/download_images.py --all      # 处理所有 loop
    python3 scripts/download_images.py --max 300  # 单次最多下载数

规则:
- 按 URL 的 md5 去重（DB 里已有或磁盘已存在则跳过）
- 过滤 logo/ogp/icon/favicon 等噪声
- 1.2s 礼貌间隔；下载入 data/images/<md5>.<ext>（webp 转 jpg）
- 写入 images 表（keywords 取 alt_texts，status=pending，final_score 基线 0.3）
"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
IMAGES_DIR = BASE_DIR / "data" / "images"
DB_PATH = BASE_DIR / "data" / "taste_graph.db"
RUNS_DIR = BASE_DIR / "runs"

_BAD = ("logo", "ogp", "icon", "favicon", "avatar", "loader", "sprite", "pixel", "blank")


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def load_urls(all_runs: bool) -> list[dict]:
    """从 runs/loop_*/output.jsonl 收集 {url, alt, page_url} 记录（去重按 url）。"""
    seen: dict[str, dict] = {}
    files = sorted(RUNS_DIR.glob("loop_*/output.jsonl"), reverse=not all_runs)
    files = files[:1] if not all_runs else files
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines[-20000:]:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("status") != "fetched":
                continue
            alts = e.get("alt_texts") or []
            for i, u in enumerate(e.get("image_urls") or []):
                if u in seen or not u.startswith("http"):
                    continue
                if any(b in u.lower() for b in _BAD):
                    continue
                seen[u] = {
                    "url": u,
                    "alt": (alts[i] if i < len(alts) else "") or "",
                    "page_url": e.get("url", ""),
                }
    print(f"候选 URL: {len(seen)}")
    return list(seen.values())


def already_have(con: sqlite3.Connection, url_md5: str) -> bool:
    row = con.execute("SELECT COUNT(*) FROM images WHERE id = ?", (url_md5,)).fetchone()
    return bool(row and row[0])


def download(url: str, dest: Path) -> bool:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Referer": "https://www.google.com/",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        if len(data) < 2000:
            return False
        dest.write_bytes(data)
        return True
    except Exception:
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description="图片下载器")
    ap.add_argument("--all", action="store_true", help="处理所有 loop 而不是最新一个")
    ap.add_argument("--max", type=int, default=300, help="单次最多下载数")
    ap.add_argument("--out", type=str, default="", help="输出目录（默认 data/images）")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else IMAGES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.execute("PRAGMA busy_timeout=5000")

    urls = load_urls(args.all)
    done = 0
    for item in urls:
        if done >= args.max:
            break
        url = item["url"]
        uid = _md5(url)
        if already_have(con, uid):
            continue
        ext = Path(url.split("?", 1)[0]).suffix.lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        dest = out_dir / f"{uid}{ext}"
        if dest.exists():
            continue
        if not download(url, dest):
            continue
        # webp → jpg（打包管线兼容性更好）
        if ext == ".webp":
            jpg = dest.with_suffix(".jpg")
            r = subprocess.run(["sips", "-s", "format", "jpeg", str(dest), "--out", str(jpg)],
                               capture_output=True, timeout=30)
            if r.returncode == 0:
                dest.unlink(missing_ok=True)
                dest = jpg
            else:
                dest.unlink(missing_ok=True)
                continue
        keywords = [a.strip()[:40] for a in (item["alt"] or "").split("|") if a.strip()][:5]
        try:
            con.execute(
                "INSERT OR IGNORE INTO images (id, source_id, url, page_url, local_path, "
                "thumbnail_path, keywords_json, graph_score, visual_score, final_score, status, created_at) "
                "VALUES (?, NULL, ?, ?, ?, '', ?, 0.0, 0.0, 0.3, 'pending', datetime('now'))",
                (uid, url, item["page_url"], str(dest), json.dumps(keywords, ensure_ascii=False)),
            )
            con.commit()
        except sqlite3.Error:
            con.rollback()
            dest.unlink(missing_ok=True)
            continue
        done += 1
        if done % 10 == 0:
            print(f"  已下载 {done}")
        time.sleep(1.2)

    con.close()
    print(f"✅ 本次下载 {done} 张 → {out_dir}")


if __name__ == "__main__":
    main()
