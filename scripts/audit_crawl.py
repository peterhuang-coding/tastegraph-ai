#!/usr/bin/env python3
"""
Crawl Quality Audit — run by AI agent during 24h crawl to monitor quality.

Reads the active loop's output.jsonl and prints a structured report covering:
  - Source domain distribution (catches IKEA-style pollution)
  - Fetch health (success/error/skip counts)
  - Image extraction yield (URLs captured per page)
  - Top error signatures
  - Red flags (anti-bot, dead domains, suspiciously high low-priority share)

Usage:
  python3 scripts/audit_crawl.py              # audit most recent loop
  python3 scripts/audit_crawl.py <loop_dir>   # audit specific loop
  python3 scripts/audit_crawl.py --json       # machine-readable output
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path("/Volumes/SanDisk2TB/自媒体作品/小红书起号/moodboard-hidden-ny-jjjjound").resolve()

# Same SKIP_DOMAINS as crawl_loop_6h.py — keep in sync.
SKIP_DOMAINS = {
    "www.ikea.com", "ikea.com",
    "www.taobao.com", "taobao.com",
    "www.tmall.com", "tmall.com",
    "www.jd.com", "jd.com",
    "www.amazon.com", "amazon.com",
    "www.ebay.com", "ebay.com",
    "www.aliexpress.com", "aliexpress.com",
    "www.pinterest.com", "pinterest.com",
    "www.facebook.com", "facebook.com",
    "www.instagram.com", "instagram.com",
    "www.twitter.com", "twitter.com", "x.com",
    "www.tiktok.com", "tiktok.com",
    "www.reddit.com", "reddit.com",
}

RED_FLAG_THRESHOLDS = {
    "skip_share": 0.20,
    "error_rate": 0.30,
    "top_domain_share": 0.25,
    "low_image_yield": 0.5,
}


def find_latest_loop() -> Path | None:
    runs = PROJECT_ROOT / "runs"
    if not runs.exists():
        return None
    candidates = sorted(runs.glob("loop_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for c in candidates:
        if (c / "output.jsonl").exists():
            return c
    return None


def audit(loop_dir: Path) -> dict:
    out_file = loop_dir / "output.jsonl"
    if not out_file.exists():
        return {"error": f"No output.jsonl in {loop_dir}"}

    records = []
    for line in out_file.read_text().splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            pass

    if not records:
        return {"error": "Empty output.jsonl"}

    n_total = len(records)
    status_counts = Counter(r.get("status", "?") for r in records)

    domain_counts = Counter()
    for r in records:
        url = r.get("url") or ""
        if url:
            d = urlparse(url).netloc
            domain_counts[d] += 1

    error_sigs = Counter()
    for r in records:
        err = r.get("error", "")
        if err:
            sig = err.split(":")[0][:40]
            error_sigs[sig] += 1

    n_with_imgs = 0
    n_total_imgs = 0
    img_yield_dist = Counter()
    for r in records:
        urls = r.get("image_urls", [])
        if urls:
            n_with_imgs += 1
            n_total_imgs += len(urls)
            if len(urls) <= 3: img_yield_dist["1-3"] += 1
            elif len(urls) <= 10: img_yield_dist["4-10"] += 1
            else: img_yield_dist["11-20"] += 1
        else:
            img_yield_dist["0"] += 1

    n_skipped = sum(1 for r in records if (r.get("error") or "").startswith("skip_domain:"))
    skip_share = n_skipped / n_total if n_total else 0

    n_ok = status_counts.get("fetched", 0)
    n_err = status_counts.get("fetch_error", 0)
    error_rate = n_err / n_total if n_total else 0
    img_yield_avg = n_total_imgs / n_total if n_total else 0

    top_domain, top_domain_count = domain_counts.most_common(1)[0] if domain_counts else ("?", 0)
    top_domain_share = top_domain_count / n_total if n_total else 0

    flags = []
    if skip_share > RED_FLAG_THRESHOLDS["skip_share"]:
        flags.append(f"skip_domain 占 {skip_share:.0%} (>20%) — seed 池可能还在喂 skip 列表里的源")
    if error_rate > RED_FLAG_THRESHOLDS["error_rate"]:
        flags.append(f"fetch_error 率 {error_rate:.0%} (>30%) — 可能被 anti-bot 拦或种子池失效")
    if top_domain_share > RED_FLAG_THRESHOLDS["top_domain_share"]:
        flags.append(f"单一域名 {top_domain} 占 {top_domain_share:.0%} (>25%) — 类似 IKEA 污染")
    if img_yield_avg < RED_FLAG_THRESHOLDS["low_image_yield"]:
        flags.append(f"平均每页图引用 {img_yield_avg:.2f} (<0.5) — 图片提取可能坏了")

    return {
        "loop": str(loop_dir),
        "n_records": n_total,
        "status_counts": dict(status_counts),
        "n_ok": n_ok,
        "n_err": n_err,
        "n_skipped": n_skipped,
        "skip_share": round(skip_share, 3),
        "error_rate": round(error_rate, 3),
        "img_yield_avg": round(img_yield_avg, 2),
        "img_yield_dist": dict(img_yield_dist),
        "n_total_imgs": n_total_imgs,
        "top_domains": domain_counts.most_common(10),
        "top_errors": error_sigs.most_common(5),
        "red_flags": flags,
    }


def format_report(r: dict) -> str:
    lines = []
    lines.append(f"=== Crawl Audit · {r['loop']} ===")
    lines.append(f"  Records:    {r['n_records']}")
    lines.append(f"  Status:     {r['status_counts']}")
    lines.append(f"  ok/err/skip: {r['n_ok']} / {r['n_err']} / {r['n_skipped']}")
    lines.append(f"  Skip share: {r['skip_share']:.1%}    Error rate: {r['error_rate']:.1%}")
    lines.append(f"  Image yield: {r['img_yield_avg']:.2f} imgs/page (total {r['n_total_imgs']} refs)")
    lines.append(f"  Yield dist:  {r['img_yield_dist']}")
    lines.append("")
    lines.append("Top domains:")
    for d, c in r["top_domains"]:
        lines.append(f"  {c:>5}  {d}")
    if r["top_errors"]:
        lines.append("")
        lines.append("Top error signatures:")
        for sig, c in r["top_errors"]:
            lines.append(f"  {c:>3}  {sig}")
    lines.append("")
    if r["red_flags"]:
        lines.append("[RED FLAGS]")
        for f in r["red_flags"]:
            lines.append(f"  - {f}")
    else:
        lines.append("[OK] no red flags")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("loop_dir", nargs="?", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    loop_dir = Path(args.loop_dir) if args.loop_dir else find_latest_loop()
    if not loop_dir or not loop_dir.exists():
        print("No loop directory found", file=sys.stderr)
        sys.exit(1)

    r = audit(loop_dir)
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    else:
        print(format_report(r))


if __name__ == "__main__":
    main()