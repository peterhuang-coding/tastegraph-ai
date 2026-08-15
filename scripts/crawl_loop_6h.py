#!/usr/bin/env python3
"""
6-Hour Crawler Loop with Deep Discovery
========================================
Budget: 2000 requests / 5 hours = ~9 seconds per request.

Strategy:
  Cycle 1: Process seed URLs (link_sources.json, link_packs, manifests, DB).
  For each successfully fetched page: extract child article links from same domain.
  Queue child links for next cycle. Continue until budget exhausted or deadline.

Stealth: UA rotation, domain cooldown (6s), session-aware pacing, single-threaded.

Usage:
    python scripts/crawl_loop_6h.py --duration-hours 6
    python scripts/crawl_loop_6h.py --duration-hours 5 --rate-limit 9
"""

import argparse
import hashlib
import json
import random
import signal
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RUNS_DIR = PROJECT_ROOT / "runs"
SHARED_DEDUP_FILE = RUNS_DIR / "shared_dedup.json"
DISCOVERY_QUEUE_FILE = RUNS_DIR / "discovery_queue.json"

# ── Source quality control ──────────────────────────────────
# Domains that are noise / off-brand for the editorial/brutalist aesthetic.
# Historical IKEA pollution alone was 53% of all crawled URLs — never let
# that happen again. Hard-skip in fetch_page().
SKIP_DOMAINS = {
    "www.ikea.com", "ikea.com",
    "www.taobao.com", "taobao.com",
    "www.tmall.com", "tmall.com",
    "www.jd.com", "jd.com",
    "www.amazon.com", "amazon.com",
    "www.ebay.com", "ebay.com",
    "www.aliexpress.com", "aliexpress.com",
    "www.pinterest.com", "pinterest.com",  # 80% bot-blocked + low editorial
    "www.facebook.com", "facebook.com",
    "www.instagram.com", "instagram.com",
    "www.twitter.com", "twitter.com", "x.com",
    "www.tiktok.com", "tiktok.com",
    "www.reddit.com", "reddit.com",
}

# Domains that are on-brand but lower priority — only fetch if budget allows.
LOW_PRIORITY_DOMAINS = {
    "www.muji.com.cn", "muji.com.cn",  # OK but not editorial
    "www.zhihu.com", "zhihu.com",  # text-heavy
    "www.bilibili.com", "bilibili.com",  # video, mostly text-only pages
}

# ── User-Agent pool ──────────────────────────────────────────

_UAS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_LANGS = ["zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
          "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
          "en-GB,en;q=0.9,zh-CN;q=0.8,zh;q=0.7,fr;q=0.6"]

_domain_times: dict[str, float] = {}
_DOMAIN_MIN = 6.0

_http = None
def _get_http():
    import httpx
    global _http
    if _http is None:
        _http = httpx.Client(headers={
            "User-Agent": random.choice(_UAS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": random.choice(_LANGS),
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
        }, timeout=20, follow_redirects=True)
    return _http

def _rotate_ua():
    global _http
    if _http:
        _http.headers["User-Agent"] = random.choice(_UAS)
        _http.headers["Accept-Language"] = random.choice(_LANGS)


# ── Rate limiter ─────────────────────────────────────────────

class RateLimiter:
    """Enforce N requests per hour with per-domain cooldown."""
    def __init__(self, per_hour: int = 400):
        self.per_hour = per_hour
        self.min_interval = 3600 / per_hour  # seconds between requests
        self.last_request = 0.0
        self.count_this_hour = 0
        self.hour_start = time.time()

    def wait(self, domain: str = ""):
        # Per-domain cooldown
        now = time.time()
        last = _domain_times.get(domain, 0)
        if now - last < _DOMAIN_MIN:
            time.sleep(_DOMAIN_MIN - (now - last) + random.uniform(0, 1))
        _domain_times[domain] = time.time()

        # Global rate limit
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed + random.uniform(0, 0.5))

        # Hourly counter
        if now - self.hour_start > 3600:
            self.hour_start = now
            self.count_this_hour = 0
        self.count_this_hour += 1
        self.last_request = time.time()

    def stats(self) -> str:
        return f"{self.count_this_hour}/{self.per_hour} this hour"


# ── Seed data loaders ────────────────────────────────────────

def _load_link_sources():
    f = PROJECT_ROOT / "link_sources.json"
    if not f.exists(): return []
    data = json.loads(f.read_text(encoding="utf-8"))
    items = []
    for cat, srcs in data.items():
        if not isinstance(srcs, list): continue
        for s in srcs:
            items.append({"category": cat, "name": s.get("name",""), "url": s.get("url",""),
                          "why": s.get("why",""), "source_type": "link_sources_json"})
    return items

def _load_manifests():
    items = []
    d = PROJECT_ROOT / "manifests"
    if not d.exists(): return items
    for mf in sorted(d.glob("*.json")):
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            for pick in data.get("picks",[]):
                items.append({"manifest_date": mf.stem, "theme": data.get("theme",""),
                              "title": pick.get("title",""), "source_page": pick.get("source_page",""),
                              "why": pick.get("why",""), "source_type": "manifest_pick"})
            for ts in data.get("trend_sources",[]):
                items.append({"manifest_date": mf.stem, "theme": data.get("theme",""),
                              "name": ts.get("name",""), "url": ts.get("url",""),
                              "why": ts.get("why",""), "source_type": "manifest_trend_source"})
        except: continue
    return items

def _load_link_packs():
    items = []
    d = PROJECT_ROOT / "link_packs"
    if not d.exists(): return items
    for lf in sorted(d.glob("*.txt")):
        try:
            text = lf.read_text(encoding="utf-8")
            section = ""; entry = {}
            for line in text.splitlines():
                line = line.strip()
                if not line: continue
                if line.isupper() or "REFERENCES" in line: section = line; continue
                if line.startswith(("Date:","Mode:","Taste","How")): continue
                if line[0].isdigit() and ". " in line[:4]:
                    if entry and entry.get("url"):
                        entry.update({"source_type":"link_pack","pack_date":lf.stem,"section":section})
                        items.append(entry)
                    entry = {"title": line.split(". ",1)[1] if ". " in line else line}; continue
                if line.startswith("http"): entry["url"] = line; continue
                if line.startswith("Why"): entry["why"] = line.split(":",1)[1].strip() if ":" in line else line
            if entry and entry.get("url"):
                entry.update({"source_type":"link_pack","pack_date":lf.stem,"section":section})
                items.append(entry)
        except: continue
    return items

def _load_db():
    import sqlite3
    items = []
    db = DATA_DIR / "taste_graph.db"
    if not db.exists(): return items
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT id,url,name,source_type FROM sources WHERE status IN ('APPROVED','approved')"):
            items.append({"source_id":row["id"],"url":row["url"],"name":row["name"],
                          "source_type":f"db_{row['source_type']}"})
        conn.close()
    except: pass
    return items

def _load_date_folders():
    items = []
    for dd in sorted(PROJECT_ROOT.glob("20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]")):
        if not dd.is_dir(): continue
        for f in sorted(dd.iterdir()):
            try:
                if f.suffix == ".txt":
                    items.append({"date":dd.name,"file":str(f.relative_to(PROJECT_ROOT)),
                                  "source_type":"date_folder"})
                elif f.suffix == ".json":
                    items.append({"date":dd.name,"file":str(f.relative_to(PROJECT_ROOT)),
                                  "source_type":"date_folder"})
            except: continue
    return items

def load_seeds() -> list[dict]:
    items = []
    items.extend(_load_link_sources())
    items.extend(_load_manifests())
    items.extend(_load_link_packs())
    items.extend(_load_db())
    items.extend(_load_date_folders())
    # Mark all seeds so the cycle loop can bypass dedup (seeds always refresh)
    for it in items:
        it["_seed"] = True
    return items

def load_discovery_queue() -> list[dict]:
    if DISCOVERY_QUEUE_FILE.exists():
        try:
            return json.loads(DISCOVERY_QUEUE_FILE.read_text(encoding="utf-8"))
        except: pass
    return []

def save_discovery_queue(queue: list[dict]):
    DISCOVERY_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERY_QUEUE_FILE.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")


# ── Dedup ────────────────────────────────────────────────────

def _dkey(item: dict) -> str:
    parts = []
    for f in ("url","source_id","source_page"):
        v = item.get(f,"")
        if v: parts.append(str(v))
    if not parts:
        parts.append(hashlib.sha256(json.dumps(item,sort_keys=True,default=str).encode()).hexdigest()[:16])
    return "|".join(parts)

def load_dedup() -> set[str]:
    if SHARED_DEDUP_FILE.exists():
        try: return set(json.loads(SHARED_DEDUP_FILE.read_text(encoding="utf-8")).get("keys",[]))
        except: pass
    return set()

def save_dedup(keys: set[str], stats: dict):
    SHARED_DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    SHARED_DEDUP_FILE.write_text(json.dumps({
        "keys": sorted(keys), "stats": stats,
        "updated": datetime.now(timezone.utc).isoformat()
    }, ensure_ascii=False), encoding="utf-8")


# ── Page fetcher ─────────────────────────────────────────────

def _is_skipped_domain(domain: str) -> bool:
    """True if domain (or any parent domain) is in SKIP_DOMAINS."""
    if domain in SKIP_DOMAINS:
        return True
    # Match subdomains: news.ikea.com → ikea.com
    parts = domain.split(".")
    for i in range(len(parts)):
        parent = ".".join(parts[i:])
        if parent in SKIP_DOMAINS:
            return True
    return False


def fetch_page(url: str) -> dict:
    """Fetch page metadata + extract child links for deep discovery."""
    if not url or not url.startswith("http"):
        return {}
    domain = urlparse(url).netloc
    # Hard skip off-brand domains (IKEA, e-commerce, social)
    if _is_skipped_domain(domain):
        return {"_error": f"skip_domain:{domain}"}

    try:
        c = _get_http()
        if random.random() < 0.15:
            _rotate_ua()
        r = c.get(url)
        if r.status_code == 403:
            return {"_error": "403 anti-bot"}
        if r.status_code == 429:
            time.sleep(random.uniform(20, 30))
            _rotate_ua()
            r = c.get(url)
            if r.status_code != 200:
                return {"_error": f"HTTP {r.status_code} after 429"}
        if r.status_code != 200:
            return {"_error": f"HTTP {r.status_code}"}

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        result = {"_status": 200, "_len": len(r.text)}

        # Metadata
        title = ""
        if soup.find("title"): title = soup.find("title").get_text(strip=True)
        ogt = soup.find("meta", property="og:title")
        if ogt and ogt.get("content"): title = ogt["content"] or title
        result["title"] = title[:300]

        desc = ""
        md = soup.find("meta", attrs={"name":"description"})
        if md and md.get("content"): desc = md["content"]
        ogd = soup.find("meta", property="og:description")
        if ogd and ogd.get("content"): desc = ogd["content"] or desc
        result["description"] = desc[:500]

        ogi = soup.find("meta", property="og:image")
        if ogi and ogi.get("content"): result["og_image"] = ogi["content"][:500]

        ma = soup.find("meta", attrs={"name":"author"})
        if ma and ma.get("content"): result["author"] = ma["content"][:200]

        # Alt texts (kept for cheap quality signal — limit 5)
        alts = []
        for img in soup.find_all("img"):
            a = (img.get("alt") or "").strip()
            if a and 2 < len(a) < 100: alts.append(a)
            if len(alts) >= 5: break
        result["alt_texts"] = alts

        # Image URLs (full extraction — capped at 20 per page to avoid bloat)
        # Capture src + alt + width hint so downstream CLIP/select can score.
        images = []
        seen_src = set()
        img_skip_ext = (".svg", ".ico", ".gif", "data:image")
        for img in soup.find_all("img"):
            src = (img.get("src") or img.get("data-src") or img.get("data-lazy-src") or "").strip()
            if not src: continue
            # Normalize relative URLs
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = urljoin(url, src)
            if not src.startswith("http"): continue
            if any(src.lower().endswith(ext) for ext in img_skip_ext): continue
            # Filter tiny icons (1x1 trackers, etc.)
            w = img.get("width") or ""
            try:
                if w and int(str(w).rstrip("px")) < 80: continue
            except: pass
            if src in seen_src: continue
            seen_src.add(src)
            images.append({
                "src": src[:500],
                "alt": (img.get("alt") or "").strip()[:200],
                "width": str(w)[:20],
            })
            if len(images) >= 20: break
        result["images"] = images
        result["image_count"] = len(images)

        # Child links (deep discovery)
        child_links = []
        skip = ["about","contact","login","signup","subscribe","privacy","terms",
                "policy","faq","cart","search","account","wishlist","newsletter",
                "tag/","author/","page/","category/","cdn.","static.","assets",
                "cdn-","images/","upload","wp-content","wp-admin","wp-json",
                ".jpg",".png",".webp",".gif",".mp4","#","javascript:"]
        base_domain = urlparse(url).netloc
        seen_paths = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("/"):
                href = urljoin(url, href)
            elif not href.startswith("http"):
                continue
            if urlparse(href).netloc != base_domain:
                continue
            path = urlparse(href).path.strip("/").lower()
            if not path or len(path) < 4: continue
            if any(s in href.lower() for s in skip): continue
            if path in seen_paths: continue
            seen_paths.add(path)
            child_links.append({"url": href, "parent_url": url, "source_type": "discovered_link",
                                "anchor": a.get_text(strip=True)[:100]})

            if len(child_links) >= 15:  # cap per page to avoid explosion
                break

        result["child_links"] = child_links
        result["child_count"] = len(child_links)

        # Visible text excerpt
        for s in soup(["script","style","nav","footer","header"]):
            s.decompose()
        body = soup.find("body")
        if body:
            import re
            v = re.sub(r'\s+',' ', body.get_text(separator=" ",strip=True)).strip()
            result["visible_text"] = v[:1500]

        return result
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {str(e)[:100]}"}


# ── Signal ──────────────────────────────────────────────────

_shutdown = False
def _sig(signum, frame):
    global _shutdown
    _shutdown = True
    print("\n[signal] Shutdown — finishing current item...")
signal.signal(signal.SIGINT, _sig)
signal.signal(signal.SIGTERM, _sig)


# ── Main Loop ───────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="6-Hour Crawler Loop with Deep Discovery")
    parser.add_argument("--duration-hours", type=float, default=6)
    parser.add_argument("--rate-limit", type=int, default=400,
                        help="Max requests per hour (default: 400 = ~9s/req, 2000/5h)")
    parser.add_argument("--cycle-wait", type=int, default=120,
                        help="Seconds between cycles when nothing new (default: 120)")
    parser.add_argument("--max-discovered", type=int, default=200,
                        help="Max discovered links to queue per run (default: 200)")
    args = parser.parse_args()

    deadline = time.time() + args.duration_hours * 3600
    rate = RateLimiter(per_hour=args.rate_limit)
    processed_keys = load_dedup()
    discovery_queue = load_discovery_queue()

    stats = {"cycles": 0, "total_processed": len(processed_keys),
             "fetched": 0, "fetch_error": 0, "discovered": 0, "skipped": 0}
    start_time = time.time()

    out_dir = RUNS_DIR / f"loop_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "output.jsonl"

    print(f"[loop] {args.duration_hours}h crawl loop with deep discovery")
    print(f"[loop] Rate limit: {args.rate_limit}/h ({3600/args.rate_limit:.0f}s/req)")
    print(f"[loop] Budget: {args.rate_limit * args.duration_hours} requests max")
    print(f"[loop] Processed: {len(processed_keys)} | Queued: {len(discovery_queue)}")
    print(f"[loop] Output: {out_dir}")
    print(f"[loop] Deadline: {time.strftime('%H:%M:%S', time.localtime(deadline))}")
    print()

    cycle = 0
    while time.time() < deadline and not _shutdown:
        cycle += 1
        cycle_start = time.time()
        remaining_h = max(0, (deadline - time.time()) / 3600)
        remaining_req = max(0, args.rate_limit * args.duration_hours - len(processed_keys))

        print(f"[cycle {cycle}] {'='*40}")
        print(f"[cycle {cycle}] {remaining_h:.1f}h left | ~{remaining_req} req remaining | {rate.stats()}")

        # Build work list: seeds + discovery queue
        all_items = load_seeds()
        all_items.extend(discovery_queue)

        # Dedup
        fresh = []
        dups = 0
        for item in all_items:
            # Seeds always refresh — only child links (discovered) get dedup'd
            if item.get("_seed"):
                fresh.append(item)
                continue
            k = _dkey(item)
            if k in processed_keys:
                dups += 1
            else:
                fresh.append(item)

        stats["skipped"] += dups
        # Clear queue — items will be re-added as needed
        discovery_queue = []

        print(f"[cycle {cycle}] {len(all_items)} total, {dups} dupes, {len(fresh)} new ({rate.stats()})")

        if not fresh:
            print(f"[cycle {cycle}] Nothing new. Waiting {args.cycle_wait}s...")
            save_dedup(processed_keys, stats)
            if time.time() >= deadline: break
            time.sleep(min(args.cycle_wait, deadline - time.time()))
            continue

        # Process
        cycle_ok = 0
        cycle_fail = 0
        cycle_skip = 0
        cycle_discovered = 0
        batch = []

        for i, item in enumerate(fresh):
            if _shutdown or time.time() >= deadline:
                break
            # Respect rate limit
            if rate.count_this_hour >= args.rate_limit:
                wait_time = 3600 - (time.time() - rate.hour_start)
                if wait_time > 0:
                    print(f"[cycle {cycle}] Rate limit reached, waiting {wait_time/60:.0f}min...")
                    time.sleep(min(wait_time, 300))  # sleep at most 5 min at a time
                    continue

            url = item.get("url", item.get("source_page", ""))
            domain = urlparse(url).netloc if url else ""
            k = _dkey(item)

            # Rate-limit wait
            rate.wait(domain)

            record = {
                "source_type": item.get("source_type", "?"),
                "url": url, "title": item.get("title", item.get("name", "")),
                "name": item.get("name", ""), "why": item.get("why", ""),
                "theme": item.get("theme", ""), "category": item.get("category", ""),
                "section": item.get("section", ""), "manifest_date": item.get("manifest_date", ""),
                "pack_date": item.get("pack_date", ""), "parent_url": item.get("parent_url", ""),
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "status": "consolidated", "error": "",
                "page_title": "", "page_description": "", "og_image": "",
                "page_author": "", "page_image_count": 0, "page_text_length": 0,
                "image_urls": [], "alt_texts": [],
            }

            if url and url.startswith("http"):
                meta = fetch_page(url)
                if meta.get("_error"):
                    record["status"] = "fetch_error"
                    record["error"] = meta["_error"]
                    # skip_domain errors are intentional, not failures
                    if meta["_error"].startswith("skip_domain:"):
                        record["status"] = "skipped"
                        cycle_skip += 1
                    else:
                        cycle_fail += 1
                else:
                    record["page_title"] = meta.get("title", "")
                    record["page_description"] = meta.get("description", "")
                    record["og_image"] = meta.get("og_image", "")
                    record["page_author"] = meta.get("author", "")
                    record["page_image_count"] = meta.get("image_count", 0)
                    record["page_text_length"] = len(meta.get("visible_text", ""))
                    # New: full image URL array (was: only alt_texts)
                    record["image_urls"] = [im["src"] for im in meta.get("images", [])]
                    record["alt_texts"] = meta.get("alt_texts", [])
                    if meta.get("visible_text") and not record.get("why"):
                        record["why"] = meta["visible_text"][:300]
                    if meta.get("title") and not record["title"]:
                        record["title"] = meta["title"]
                    record["status"] = "fetched"
                    cycle_ok += 1

                    # Deep discovery: queue child links
                    for child in meta.get("child_links", []):
                        ck = _dkey(child)
                        if ck not in processed_keys and len(discovery_queue) < args.max_discovered:
                            discovery_queue.append(child)
                            cycle_discovered += 1

            batch.append(record)
            processed_keys.add(k)

            # Flush periodically
            if len(batch) >= 10:
                with open(out_file, "a", encoding="utf-8") as f:
                    for r in batch:
                        f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
                batch.clear()
                save_dedup(processed_keys, stats)

            # Status
            if (cycle_ok + cycle_fail + cycle_skip) % 15 == 0 and (cycle_ok + cycle_fail + cycle_skip) > 0:
                elapsed = time.time() - cycle_start
                rate_val = (cycle_ok + cycle_fail) / elapsed if elapsed > 0 else 0
                eta = (len(fresh) - cycle_ok - cycle_fail - cycle_skip) / rate_val / 60 if rate_val > 0 else 0
                print(f"[cycle {cycle}] {cycle_ok+cycle_fail+cycle_skip}/{len(fresh)} | "
                      f"ok:{cycle_ok} err:{cycle_fail} skip:{cycle_skip} discovered:{cycle_discovered} | "
                      f"{rate_val:.1f}/s ETA {eta:.0f}min | {rate.stats()}")

        # Flush final batch
        if batch:
            with open(out_file, "a", encoding="utf-8") as f:
                for r in batch:
                    f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

        stats["fetched"] = stats.get("fetched", 0) + cycle_ok
        stats["fetch_error"] = stats.get("fetch_error", 0) + cycle_fail
        stats["skipped"] = stats.get("skipped", 0) + cycle_skip
        stats["discovered"] = stats.get("discovered", 0) + cycle_discovered
        stats["total_processed"] = len(processed_keys)
        stats["cycles"] = cycle

        save_dedup(processed_keys, stats)
        save_discovery_queue(discovery_queue)

        elapsed = time.time() - cycle_start
        print(f"[cycle {cycle}] Done {elapsed:.0f}s — {cycle_ok} ok, {cycle_fail} fail, {cycle_skip} skip, "
              f"{cycle_discovered} new links queued | Total: {stats['fetched']} fetched, "
              f"{stats['discovered']} discovered | {rate.stats()}")

        if time.time() >= deadline:
            break

    # ── Summary ──────────────────────────────────────────────
    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print(f"  Loop Complete — {elapsed/3600:.1f}h")
    print(f"  Cycles:      {cycle}")
    print(f"  Processed:   {len(processed_keys)}")
    print(f"  Fetched:     {stats.get('fetched', 0)}")
    print(f"  Fetch err:   {stats.get('fetch_error', 0)}")
    print(f"  Discovered:  {stats.get('discovered', 0)}")
    print(f"  Skipped:     {stats.get('skipped', 0)}")
    print(f"  Output:      {out_file}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
