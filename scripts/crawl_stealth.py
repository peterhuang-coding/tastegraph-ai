#!/usr/bin/env python3
"""
Private Stealth Crawler Harness
===============================
Standalone crawler that operates independently of the Xiaohongshu publish pipeline.
Designed for long-running, stealthy data accumulation to enrich the knowledge graph.

Key features:
- Proxy pool rotation (HTTP/SOCKS5, from config/proxies.txt)
- Playwright-primary mode for JS-heavy sites
- Checkpoint/resume via SQLite state table
- Selective depth: --depth 1 (seed pages only) or --depth 2 (follow child links)
- Domain allow/block lists
- JSONL output, compatible with crawl_loop_6h.py format
- Auto graph enrichment after each crawl batch

Usage:
    python scripts/crawl_stealth.py --duration-hours 6 --rate-limit 200 --depth 2
    python scripts/crawl_stealth.py --depth 1 --dry-run
    python scripts/crawl_stealth.py --allow-domains "vogue.com,ssense.com"
    python scripts/crawl_stealth.py --block-domains "pinterest.com,instagram.com"
"""

import argparse
import asyncio
import hashlib
import json
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RUNS_DIR = PROJECT_ROOT / "runs"
PROXIES_FILE = PROJECT_ROOT / "config" / "proxies.txt"

# Ensure project root on sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Stealth imports ───────────────────────────────────────────

from taste_graph_ai.infrastructure.crawlers.stealth import (
    StealthSession,
    jittered_delay,
)
from taste_graph_ai.infrastructure.crawlers.utils import (
    SKIP_PAGE_PATTERNS,
    is_bad_url,
    normalize_url,
)

# ── Proxy pool ────────────────────────────────────────────────


def load_proxies() -> list[str]:
    """Load proxy URLs from config/proxies.txt (one per line).

    Format: http://user:pass@host:port or socks5://host:port
    """
    if not PROXIES_FILE.exists():
        return []
    proxies = []
    for line in PROXIES_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            proxies.append(line)
    return proxies


# ── Checkpoint DB ─────────────────────────────────────────────


def get_checkpoint_db() -> Path:
    return DATA_DIR / "crawl_stealth_state.db"


def init_checkpoint_db(db_path: Path) -> None:
    import sqlite3
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS crawl_state (
            url TEXT PRIMARY KEY,
            status TEXT DEFAULT 'pending',
            fetched_at TEXT,
            error TEXT,
            page_title TEXT,
            depth INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_crawl_status ON crawl_state(status)
    """)
    conn.commit()
    conn.close()


def load_checkpoint(db_path: Path) -> set[str]:
    """Return set of already-fetched URLs."""
    import sqlite3
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT url FROM crawl_state WHERE status = 'fetched'"
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


def save_checkpoint(
    db_path: Path,
    url: str,
    status: str,
    page_title: str = "",
    error: str = "",
    depth: int = 0,
) -> None:
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT OR REPLACE INTO crawl_state (url, status, fetched_at, error, page_title, depth)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (url, status, datetime.now(timezone.utc).isoformat(), error, page_title, depth),
    )
    conn.commit()
    conn.close()


# ── Seed loaders ──────────────────────────────────────────────


def load_seed_urls() -> list[dict]:
    """Load seed URLs from link_sources.json and link_packs."""
    items = []

    # link_sources.json
    f = PROJECT_ROOT / "link_sources.json"
    if f.exists():
        data = json.loads(f.read_text(encoding="utf-8"))
        for cat, srcs in data.items():
            if not isinstance(srcs, list):
                continue
            for s in srcs:
                url = s.get("url", "")
                if url and url.startswith("http"):
                    items.append({
                        "url": url,
                        "name": s.get("name", ""),
                        "category": cat,
                        "why": s.get("why", ""),
                    })

    # link_packs
    d = PROJECT_ROOT / "link_packs"
    if d.exists():
        for lf in sorted(d.glob("*.txt")):
            try:
                text = lf.read_text(encoding="utf-8")
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("http"):
                        items.append({
                            "url": line,
                            "name": "",
                            "category": "link_pack",
                            "why": "",
                        })
            except Exception:
                pass

    # DB sources
    db_path = DATA_DIR / "taste_graph.db"
    if db_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            for row in conn.execute(
                "SELECT url, name, source_type FROM sources WHERE status = 'approved'"
            ):
                if row["url"] and row["url"].startswith("http"):
                    items.append({
                        "url": row["url"],
                        "name": row["name"] or "",
                        "category": row["source_type"] or "",
                        "why": "",
                    })
            conn.close()
        except Exception:
            pass

    return items


# ── Page fetcher ──────────────────────────────────────────────


async def fetch_page(
    url: str,
    session: StealthSession,
    proxy: str = "",
    use_playwright: bool = False,
) -> dict:
    """Fetch a single page and extract metadata + child links.

    Returns dict with: title, description, visible_text, child_links, error
    """
    domain = urlparse(url).netloc
    result: dict = {
        "url": url,
        "title": "",
        "description": "",
        "visible_text": "",
        "child_links": [],
        "error": "",
    }

    try:
        if use_playwright:
            return await _fetch_playwright(url, proxy)

        # httpx mode
        client = session.get_client(domain, referer_url="https://www.google.com/")
        r = await client.get(url)
        if r.status_code != 200:
            result["error"] = f"HTTP {r.status_code}"
            return result

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")

        # Title
        title = ""
        if soup.find("title"):
            title = soup.find("title").get_text(strip=True)
        ogt = soup.find("meta", property="og:title")
        if ogt and ogt.get("content"):
            title = ogt["content"] or title
        result["title"] = title[:300]

        # Description
        desc = ""
        md = soup.find("meta", attrs={"name": "description"})
        if md and md.get("content"):
            desc = md["content"]
        ogd = soup.find("meta", property="og:description")
        if ogd and ogd.get("content"):
            desc = ogd["content"] or desc
        result["description"] = desc[:500]

        # Visible text
        for s in soup(["script", "style", "nav", "footer", "header"]):
            s.decompose()
        body = soup.find("body")
        if body:
            import re
            v = re.sub(r'\s+', ' ', body.get_text(separator=" ", strip=True)).strip()
            result["visible_text"] = v[:1500]

        # Child links (for depth=2)
        child_links = []
        seen_paths = set()
        base_domain = urlparse(url).netloc

        for a in soup.find_all("a", href=True):
            href = normalize_url(a["href"], url)
            if not href or not href.startswith("http"):
                continue
            if urlparse(href).netloc != base_domain:
                continue
            path = urlparse(href).path.strip("/").lower()
            if not path or len(path) < 4:
                continue
            if any(skp in path for skp in SKIP_PAGE_PATTERNS):
                continue
            if path in seen_paths:
                continue
            seen_paths.add(path)
            child_links.append({
                "url": href,
                "anchor": a.get_text(strip=True)[:100],
            })
            if len(child_links) >= 15:
                break

        result["child_links"] = child_links

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"

    return result


async def _fetch_playwright(url: str, proxy: str = "") -> dict:
    """Fetch a page using Playwright for JS rendering."""
    result: dict = {
        "url": url, "title": "", "description": "", "visible_text": "",
        "child_links": [], "error": "",
    }
    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        launch_args: dict = {"headless": True, "args": ["--no-sandbox"]}
        if proxy:
            launch_args["proxy"] = {"server": proxy}

        browser = await pw.chromium.launch(**launch_args)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except Exception as exc:
                result["error"] = f"Playwright goto: {exc}"
                await context.close()
                await browser.close()
                await pw.stop()
                return result

        # Extract content
        page_content = await page.evaluate("""() => {
            const title = document.title || '';
            const metaDesc = document.querySelector('meta[name="description"]');
            const description = metaDesc ? metaDesc.getAttribute('content') || '' : '';

            // Visible text (exclude scripts/styles)
            const body = document.body;
            if (!body) return { title, description, visibleText: '', links: [] };
            const clone = body.cloneNode(true);
            clone.querySelectorAll('script, style, nav, footer, header').forEach(e => e.remove());
            const visibleText = (clone.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 1500);

            // Child links
            const links = [];
            const seen = new Set();
            const skipPatterns = ['about','contact','login','signup','privacy','terms','faq','cart','search'];
            const baseUrl = window.location.origin;
            for (const a of document.querySelectorAll('a[href]')) {
                let href = a.getAttribute('href') || '';
                if (href.startsWith('/')) href = baseUrl + href;
                if (!href.startsWith(baseUrl)) continue;
                const path = new URL(href).pathname.replace(/\\/$/, '').toLowerCase();
                if (!path || path.length < 4) continue;
                if (skipPatterns.some(p => path.includes(p))) continue;
                if (seen.has(path)) continue;
                seen.add(path);
                links.push({ url: href, anchor: (a.textContent || '').trim().slice(0, 100) });
                if (links.length >= 15) break;
            }
            return { title, description, visibleText, links };
        }""")

        result["title"] = page_content.get("title", "")[:300]
        result["description"] = page_content.get("description", "")[:500]
        result["visible_text"] = page_content.get("visibleText", "")
        result["child_links"] = page_content.get("links", [])

        await context.close()
        await browser.close()
        await pw.stop()

    except Exception as exc:
        result["error"] = f"Playwright: {type(exc).__name__}: {str(exc)[:200]}"

    return result


# ── Signal handling ───────────────────────────────────────────

_shutdown = False


def _sig(signum, frame):
    global _shutdown
    _shutdown = True
    print("\n[stealth] Shutdown signal received — finishing current item...")


signal.signal(signal.SIGINT, _sig)
signal.signal(signal.SIGTERM, _sig)


# ── Main loop ─────────────────────────────────────────────────


async def run(args: argparse.Namespace) -> int:
    global _shutdown

    deadline = time.time() + args.duration_hours * 3600
    min_interval = 3600 / args.rate_limit  # seconds between requests

    # Setup
    proxies = load_proxies()
    if args.use_proxy and proxies:
        print(f"[stealth] Loaded {len(proxies)} proxies")
    elif args.use_proxy:
        print("[stealth] WARNING: --use-proxy set but no proxies found in config/proxies.txt")

    db_path = get_checkpoint_db()
    init_checkpoint_db(db_path)
    fetched = load_checkpoint(db_path)
    print(f"[stealth] Checkpoint: {len(fetched)} URLs already fetched")

    session = StealthSession()

    # Load seeds
    seeds = load_seed_urls()
    # Filter by domain
    if args.allow_domains:
        allowed = set(d.strip() for d in args.allow_domains.split(","))
        seeds = [s for s in seeds if urlparse(s["url"]).netloc in allowed]
    if args.block_domains:
        blocked = set(d.strip() for d in args.block_domains.split(","))
        seeds = [s for s in seeds if urlparse(s["url"]).netloc not in blocked]

    print(f"[stealth] {len(seeds)} seed URLs loaded after domain filtering")

    # Output dir
    out_dir = RUNS_DIR / f"stealth_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "output.jsonl"
    print(f"[stealth] Output: {out_dir}")

    # Statistics
    stats = {"fetched": 0, "errors": 0, "discovered": 0, "skipped": 0}

    # Work queue: (url, depth, source_info)
    work_queue: list[tuple[str, int, dict]] = [
        (s["url"], 0, s) for s in seeds if s["url"] not in fetched
    ]
    stats["skipped"] = len(seeds) - len(work_queue)

    batch: list[dict] = []
    last_request = 0.0
    proxy_idx = 0

    while work_queue and time.time() < deadline and not _shutdown:
        url, depth, source_info = work_queue.pop(0)

        # Rate limit
        elapsed = time.time() - last_request
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed + random.uniform(0, 0.5))

        # Pick proxy
        proxy = ""
        if args.use_proxy and proxies:
            proxy = proxies[proxy_idx % len(proxies)]
            proxy_idx += 1

        # Fetch
        use_pw = args.playwright or (args.depth >= 2 and random.random() < 0.3)
        result = await fetch_page(url, session, proxy=proxy, use_playwright=use_pw)
        last_request = time.time()

        record = {
            "url": url,
            "name": source_info.get("name", ""),
            "category": source_info.get("category", ""),
            "why": source_info.get("why", ""),
            "depth": depth,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "page_title": result["title"],
            "page_description": result["description"],
            "visible_text": result["visible_text"],
            "status": "error" if result["error"] else "fetched",
            "error": result["error"],
        }

        if result["error"]:
            stats["errors"] += 1
            save_checkpoint(db_path, url, "error", error=result["error"], depth=depth)
        else:
            stats["fetched"] += 1
            save_checkpoint(
                db_path, url, "fetched",
                page_title=result["title"], depth=depth,
            )

            # Depth 2: queue child links
            if args.depth >= 2 and depth < 1:
                for child in result["child_links"]:
                    child_url = child["url"]
                    if child_url not in fetched:
                        work_queue.append((child_url, depth + 1, {
                            "url": child_url,
                            "name": child.get("anchor", ""),
                            "category": "discovered",
                            "why": "",
                        }))
                        stats["discovered"] += 1

        batch.append(record)

        # Flush after every item for live visibility
        _write_batch(out_file, batch)
        batch.clear()
        _print_progress(stats, deadline)
        sys.stdout.flush()

    # Final flush
    if batch:
        _write_batch(out_file, batch)

    # ── Auto graph enrichment ──────────────────────────────────
    if not args.dry_run and stats["fetched"] > 0:
        await _enrich_graph(out_file, stats)

    # ── Cleanup ─────────────────────────────────────────────────
    await session.close()

    # ── Summary ─────────────────────────────────────────────────
    _print_summary(stats, out_file, deadline)
    return 0


def _write_batch(out_file: Path, batch: list[dict]) -> None:
    with open(out_file, "a", encoding="utf-8") as f:
        for r in batch:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def _print_progress(stats: dict, deadline: float) -> None:
    remaining_h = max(0, (deadline - time.time()) / 3600)
    print(
        f"[stealth] {stats['fetched']} ok, {stats['errors']} err, "
        f"{stats['discovered']} discovered, {stats['skipped']} skipped | "
        f"{remaining_h:.1f}h remaining"
    )


def _print_summary(stats: dict, out_file: Path, deadline: float) -> None:
    print()
    print("=" * 60)
    print(f"  Stealth Crawl Complete")
    print(f"  Fetched:    {stats['fetched']}")
    print(f"  Errors:     {stats['errors']}")
    print(f"  Discovered: {stats['discovered']}")
    print(f"  Skipped:    {stats['skipped']}")
    print(f"  Output:     {out_file}")
    print("=" * 60)


async def _enrich_graph(out_file: Path, stats: dict) -> None:
    """Auto-enrich the taste graph from crawl output."""
    try:
        from taste_graph_ai.container import get_container
        print("\n[stealth] Enriching taste graph from crawl output...")

        graph = get_container().taste_graph
        enriched = 0
        with open(out_file, encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if record.get("status") != "fetched":
                        continue
                    new_nodes = graph.enrich_from_crawl(
                        source_name=record.get("name") or record.get("url", ""),
                        source_url=record.get("url", ""),
                        visible_text=record.get("visible_text", ""),
                        page_title=record.get("page_title", ""),
                    )
                    enriched += new_nodes
                except Exception:
                    continue

        if enriched > 0:
            graph.save()
            print(f"[stealth] Graph enriched: {enriched} new nodes added")
    except Exception as exc:
        print(f"[stealth] Graph enrichment skipped: {exc}")


# ── CLI ───────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Private Stealth Crawler Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/crawl_stealth.py --duration-hours 6 --rate-limit 200 --depth 2
  python scripts/crawl_stealth.py --depth 1 --dry-run
  python scripts/crawl_stealth.py --allow-domains "vogue.com,ssense.com"
  python scripts/crawl_stealth.py --use-proxy --playwright
""",
    )
    parser.add_argument(
        "--duration-hours", type=float, default=6,
        help="Max crawl duration in hours (default: 6)",
    )
    parser.add_argument(
        "--rate-limit", type=int, default=200,
        help="Max requests per hour (default: 200)",
    )
    parser.add_argument(
        "--depth", type=int, default=1,
        help="Crawl depth: 1=seed pages only, 2=follow child links (default: 1)",
    )
    parser.add_argument(
        "--use-proxy", action="store_true",
        help="Enable proxy rotation from config/proxies.txt",
    )
    parser.add_argument(
        "--playwright", action="store_true",
        help="Use Playwright as primary fetcher (not just fallback)",
    )
    parser.add_argument(
        "--allow-domains", type=str, default="",
        help="Comma-separated list of allowed domains",
    )
    parser.add_argument(
        "--block-domains", type=str, default="",
        help="Comma-separated list of blocked domains",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview mode: crawl but don't enrich graph",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
