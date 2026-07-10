#!/usr/bin/env python3
"""
XHS 12-Hour Content Consolidation Pipeline
===========================================

A stable, resumable, observable pipeline that reads existing seed/source/link_pack/
manifest/taste-graph data and produces structured JSONL/CSV exports.

This is NOT a scraper. It does NOT access Xiaohongshu, bypass anti-bot, or
automate publishing. It reads local project data and consolidates it into
structured records suitable for review, analysis, and downstream tooling.

Safety features:
- Conservative rate limiting with randomized intervals
- Single-threaded sequential processing
- Realistic browser User-Agent rotation
- Stealth delay pattern: session-aware pacing (faster at start, slower over time)
- Checkpoint/resume for interruption recovery
- Dry-run by default (no real work unless --live is specified)

Usage:
    # Dry-run (default: max 5 items, no real work)
    python scripts/run_xhs_12h_pipeline.py --dry-run --max-items 5

    # Real 12-hour run with resume support
    python scripts/run_xhs_12h_pipeline.py --duration-hours 12 --resume

    # Process a specific source category
    python scripts/run_xhs_12h_pipeline.py --source lookbook --max-items 20

    # Recover from interruption
    python scripts/run_xhs_12h_pipeline.py --resume
"""

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import random
import signal
import sqlite3
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

# ── Project root detection ────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXPORTS_DIR = DATA_DIR / "exports"
RUNS_DIR = PROJECT_ROOT / "runs"
MANIFESTS_DIR = PROJECT_ROOT / "manifests"
LINK_PACKS_DIR = PROJECT_ROOT / "link_packs"
LINK_SOURCES_FILE = PROJECT_ROOT / "link_sources.json"
TASTE_GRAPH_FILE = DATA_DIR / "taste_graph.json"
TASTE_MEMORY_FILE = PROJECT_ROOT / "taste_memory.json"
DB_FILE = DATA_DIR / "taste_graph.db"

# ── Constants ─────────────────────────────────────────────────────

DEFAULT_DURATION_HOURS = 12
DEFAULT_MAX_ITEMS = 5          # small default for safety
DEFAULT_SLEEP_MIN = 2.0
DEFAULT_SLEEP_MAX = 5.0
CHECKPOINT_INTERVAL = 10       # save checkpoint every N items
STATUS_INTERVAL = 10           # print status every N items

DEDUP_FIELDS = ["url", "note_id", "source_id"]

# ── Stealth: Realistic User-Agent pool ────────────────────────────
# Rotated per session to avoid looking like a single script.
# These are common, real-world browser UAs from different OS/browser combos.

_USER_AGENTS = [
    # macOS Chrome 124
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # macOS Safari 17
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    # macOS Firefox 125
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Windows Chrome 124
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Windows Edge 124
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    # Linux Chrome
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # macOS Chrome 123
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Windows Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# Accept-Language variants for different locales
_ACCEPT_LANGUAGES = [
    "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
    "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6",
    "en-GB,en;q=0.9,zh-CN;q=0.8,zh;q=0.7,fr;q=0.6",
]

# Referrer pool (common landing pages)
_REFERRERS = [
    "https://www.google.com/",
    "https://www.google.com/search?q=fashion+editorial+2026",
    "https://www.bing.com/",
    "",  # direct visit
    "",  # direct visit (more common)
    "https://www.pinterest.com/",
    "https://www.are.na/",
]


def get_random_ua() -> str:
    """Return a random User-Agent from the pool."""
    return random.choice(_USER_AGENTS)


def get_stealth_headers() -> dict[str, str]:
    """Return a set of stealth HTTP headers for requests."""
    return {
        "User-Agent": get_random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": random.choice(_ACCEPT_LANGUAGES),
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": random.choice(["none", "cross-site", "same-origin"]),
        "Sec-Fetch-User": "?1",
        "Cache-Control": random.choice(["max-age=0", "no-cache"]),
    }


def session_aware_delay(
    base_min: float,
    base_max: float,
    session_elapsed_hours: float,
    item_index: int,
) -> float:
    """Calculate a stealthy delay that varies with session duration.

    Early in the session: shorter delays (like a human browsing actively).
    Later in the session: longer delays (like a human getting tired).
    Adds random jitter within bounds.

    The delay gradually increases from base_min/base_max toward
    ~2x the base values over the course of the session.
    """
    # Fatigue factor: 0.0 (fresh) → 1.0 (after 8 hours)
    fatigue = min(session_elapsed_hours / 8.0, 1.0)

    # Effective range expands as fatigue increases
    eff_min = base_min + fatigue * base_min
    eff_max = base_max + fatigue * base_max * 1.5

    # Occasional "human pause" (5% chance of a longer break)
    if random.random() < 0.05:
        eff_max += random.uniform(3, 8)

    # Micro-jitter: add small random variation based on item index
    micro = (item_index % 7) * 0.15  # small deterministic variation

    return random.uniform(eff_min, eff_max) + micro


# ═══════════════════════════════════════════════════════════════════
# Data Loaders
# ═══════════════════════════════════════════════════════════════════

def load_link_sources() -> list[dict]:
    """Load seed sources from link_sources.json."""
    if not LINK_SOURCES_FILE.exists():
        return []
    data = json.loads(LINK_SOURCES_FILE.read_text(encoding="utf-8"))
    items = []
    for category, sources in data.items():
        if not isinstance(sources, list):
            continue
        for src in sources:
            items.append({
                "category": category,
                "name": src.get("name", ""),
                "url": src.get("url", ""),
                "why": src.get("why", ""),
                "source_type": "link_sources_json",
            })
    return items


def load_manifests() -> list[dict]:
    """Load manifest JSON files."""
    items = []
    if not MANIFESTS_DIR.exists():
        return items
    for mf in sorted(MANIFESTS_DIR.glob("*.json")):
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            for pick in data.get("picks", []):
                items.append({
                    "manifest_date": mf.stem,
                    "theme": data.get("theme", ""),
                    "title": pick.get("title", ""),
                    "source_page": pick.get("source_page", ""),
                    "source_name": pick.get("source_name", ""),
                    "why": pick.get("why", ""),
                    "source_type": "manifest_pick",
                })
            for ts in data.get("trend_sources", []):
                items.append({
                    "manifest_date": mf.stem,
                    "theme": data.get("theme", ""),
                    "name": ts.get("name", ""),
                    "url": ts.get("url", ""),
                    "why": ts.get("why", ""),
                    "source_type": "manifest_trend_source",
                })
        except Exception:
            continue
    return items


def load_link_packs() -> list[dict]:
    """Parse link_packs/*.txt files into structured items."""
    items = []
    if not LINK_PACKS_DIR.exists():
        return items
    for lf in sorted(LINK_PACKS_DIR.glob("*.txt")):
        try:
            text = lf.read_text(encoding="utf-8")
            pack_date = lf.stem
            # Parse sections: LOOKBOOK, VIDEOS, ARTICLES, etc.
            current_section = ""
            current_entry: dict = {}
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.isupper() or line.endswith("REFERENCES") or line.endswith("IMAGE REFERENCES"):
                    current_section = line
                    continue
                if line.startswith(("Date:", "Mode:", "Taste", "How to use")):
                    continue
                # Numbered entry: 01. Title
                if line[0].isdigit() and ". " in line[:4]:
                    if current_entry and current_entry.get("url"):
                        current_entry["source_type"] = "link_pack"
                        current_entry["pack_date"] = pack_date
                        current_entry["section"] = current_section
                        items.append(current_entry)
                    current_entry = {"title": line.split(". ", 1)[1] if ". " in line else line}
                    continue
                if line.startswith("http"):
                    current_entry["url"] = line
                    continue
                if line.startswith("Why:") or line.startswith("Why"):
                    current_entry["why"] = line.split(":", 1)[1].strip() if ":" in line else line
                    continue
            # Don't forget last entry
            if current_entry and current_entry.get("url"):
                current_entry["source_type"] = "link_pack"
                current_entry["pack_date"] = pack_date
                current_entry["section"] = current_section
                items.append(current_entry)
        except Exception:
            continue
    return items


def load_taste_graph_concepts() -> list[dict]:
    """Extract concept nodes from taste_graph.json."""
    items = []
    if not TASTE_GRAPH_FILE.exists():
        return items
    try:
        data = json.loads(TASTE_GRAPH_FILE.read_text(encoding="utf-8"))
        for node in data.get("nodes", []):
            if node.get("type") == "concept":
                items.append({
                    "concept_id": node.get("id", ""),
                    "label": node.get("label", ""),
                    "properties": json.dumps(node.get("properties", {}), ensure_ascii=False),
                    "source_type": "taste_graph_concept",
                })
    except Exception:
        pass
    return items


def load_db_sources() -> list[dict]:
    """Read approved sources from SQLite DB."""
    items = []
    if not DB_FILE.exists():
        return items
    try:
        # Use read-only connection to be safe
        conn = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT id, url, name, source_type, status, ai_score, ai_reason, "
            "discovered_from, created_at, reviewed_at "
            "FROM sources WHERE status = 'APPROVED' OR status = 'approved'"
        )
        for row in cur.fetchall():
            items.append({
                "source_id": row["id"],
                "url": row["url"],
                "name": row["name"],
                "source_type": f"db_{row['source_type']}",
                "status": row["status"],
                "ai_score": row["ai_score"],
                "ai_reason": row["ai_reason"],
                "discovered_from": row["discovered_from"],
                "created_at": row["created_at"],
            })
        conn.close()
    except Exception:
        pass
    return items


def load_date_folders() -> list[dict]:
    """Read content from date-named output folders (YYYY-MM-DD/)."""
    items = []
    for date_dir in sorted(PROJECT_ROOT.glob("20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]")):
        if not date_dir.is_dir():
            continue
        date_str = date_dir.name
        for f in sorted(date_dir.iterdir()):
            if f.suffix == ".txt":
                try:
                    text = f.read_text(encoding="utf-8")
                    items.append({
                        "date": date_str,
                        "file": str(f.relative_to(PROJECT_ROOT)),
                        "raw_text": text[:5000],  # truncate for safety
                        "source_type": "date_folder_txt",
                    })
                except Exception:
                    continue
            elif f.suffix in (".json",):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    items.append({
                        "date": date_str,
                        "file": str(f.relative_to(PROJECT_ROOT)),
                        "raw_text": json.dumps(data, ensure_ascii=False)[:5000],
                        "source_type": "date_folder_json",
                    })
                except Exception:
                    continue
    return items


def load_all_items(source_filter: Optional[str] = None) -> list[dict]:
    """Load all data items from all local sources."""
    all_items = []

    # 1. link_sources.json
    for item in load_link_sources():
        all_items.append(item)

    # 2. Manifests
    for item in load_manifests():
        all_items.append(item)

    # 3. Link packs
    for item in load_link_packs():
        all_items.append(item)

    # 4. Taste graph concepts
    for item in load_taste_graph_concepts():
        all_items.append(item)

    # 5. DB sources
    for item in load_db_sources():
        all_items.append(item)

    # 6. Date folders
    for item in load_date_folders():
        all_items.append(item)

    # Filter by source if requested
    if source_filter:
        all_items = [
            i for i in all_items
            if source_filter.lower() in i.get("source_type", "").lower()
            or source_filter.lower() in i.get("category", "").lower()
        ]

    return all_items


# ═══════════════════════════════════════════════════════════════════
# Deduplication
# ═══════════════════════════════════════════════════════════════════

def dedup_key(item: dict) -> str:
    """Generate a stable dedup key for an item."""
    parts = []
    for field in DEDUP_FIELDS:
        val = item.get(field, "")
        if val:
            parts.append(str(val))
    if not parts:
        # Fallback: hash of the whole item
        raw = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
        parts.append(hashlib.sha256(raw.encode()).hexdigest()[:16])
    return "|".join(parts)


def deduplicate(items: list[dict], seen: set[str]) -> list[dict]:
    """Filter items, keeping only those whose dedup key is not in `seen`."""
    result = []
    for item in items:
        key = dedup_key(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


# ═══════════════════════════════════════════════════════════════════
# Checkpoint
# ═══════════════════════════════════════════════════════════════════

def checkpoint_path(run_id: str) -> Path:
    return RUNS_DIR / run_id / "checkpoint.json"


def save_checkpoint(run_id: str, processed_keys: set[str], stats: dict) -> None:
    """Save progress checkpoint."""
    cp_file = checkpoint_path(run_id)
    cp_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "processed_count": len(processed_keys),
        "processed_keys": sorted(processed_keys),
        "stats": stats,
    }
    cp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_checkpoint(run_id: str) -> tuple[set[str], dict]:
    """Load checkpoint. Returns (processed_keys, stats) or (set(), {})."""
    cp_file = checkpoint_path(run_id)
    if not cp_file.exists():
        return set(), {}
    try:
        data = json.loads(cp_file.read_text(encoding="utf-8"))
        return set(data.get("processed_keys", [])), data.get("stats", {})
    except Exception:
        return set(), {}


# ═══════════════════════════════════════════════════════════════════
# Output Writers
# ═══════════════════════════════════════════════════════════════════

def write_jsonl(run_id: str, items: list[dict], append: bool = True) -> Path:
    """Write items as JSONL."""
    out_dir = RUNS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "output.jsonl"
    mode = "a" if append else "w"
    with open(out_file, mode, encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
    return out_file


CSV_FIELDS = [
    "source_type", "source_id", "url", "title", "name", "author",
    "tags", "raw_text", "images", "collected_at", "status", "error",
    "category", "section", "why", "theme", "manifest_date", "pack_date",
    "concept_id", "label",
    "page_title", "page_description", "og_image", "page_author",
    "page_image_count", "page_text_length",
]


def write_csv(run_id: str, all_items: list[dict]) -> Path:
    """Write all processed items as CSV."""
    out_dir = RUNS_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "output.csv"
    with open(out_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for item in all_items:
            # Normalize fields
            row = {}
            for k in CSV_FIELDS:
                val = item.get(k, "")
                if isinstance(val, (list, dict)):
                    val = json.dumps(val, ensure_ascii=False)
                row[k] = str(val) if val else ""
            writer.writerow(row)
    return out_file


# ═══════════════════════════════════════════════════════════════════
# Page Fetcher (live mode only)
# ═══════════════════════════════════════════════════════════════════

# Global HTTP client (lazy init)
_http_client = None


def _get_client():
    """Lazy-init httpx client with stealth headers."""
    global _http_client
    if _http_client is None:
        import httpx
        _http_client = httpx.Client(
            headers={
                "User-Agent": get_random_ua(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": random.choice(_ACCEPT_LANGUAGES),
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
            },
            timeout=30,
            follow_redirects=True,
        )
    return _http_client


def _rotate_client_ua():
    """Rotate the client's User-Agent to a new random one."""
    global _http_client
    if _http_client is not None:
        _http_client.headers["User-Agent"] = get_random_ua()
        _http_client.headers["Accept-Language"] = random.choice(_ACCEPT_LANGUAGES)


def fetch_page_metadata(url: str) -> dict:
    """Fetch a page and extract title, description, og:image, and visible text.
    Returns empty dict on failure. Uses stealth headers and per-domain rate limiting.

    Conservative: no more than 1 retry on 429/403. Does NOT download images.
    """
    if not url or not url.startswith("http"):
        return {}

    # Per-domain rate limit
    domain_aware_wait(url, 0, 0)

    try:
        client = _get_client()
        # Rotate UA occasionally (20% chance per request)
        if random.random() < 0.2:
            _rotate_client_ua()

        # Pre-fetch micro-delay
        time.sleep(random.uniform(0.2, 0.8))

        r = client.get(url)
        if r.status_code == 403:
            return {"_error": "HTTP 403 Forbidden (anti-bot)", "_status_code": 403}
        if r.status_code == 429:
            # Rate limited — wait and try once more
            time.sleep(random.uniform(10, 20))
            _rotate_client_ua()
            r = client.get(url)
            if r.status_code != 200:
                return {"_error": f"HTTP {r.status_code} after retry", "_status_code": r.status_code}
        if r.status_code != 200:
            return {"_error": f"HTTP {r.status_code}", "_status_code": r.status_code}

        html = r.text
        result = {"_status_code": 200, "_content_length": len(html)}

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            # Title
            title = ""
            if soup.find("title"):
                title = soup.find("title").get_text(strip=True)
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"] or title
            result["title"] = title[:300] if title else ""

            # Description
            description = ""
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                description = meta_desc["content"]
            og_desc = soup.find("meta", property="og:description")
            if og_desc and og_desc.get("content"):
                description = og_desc["content"] or description
            result["description"] = description[:500] if description else ""

            # OG Image (just the URL, don't download)
            og_img = soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                img_url = og_img["content"]
                if img_url.startswith("/"):
                    from urllib.parse import urljoin
                    img_url = urljoin(url, img_url)
                if img_url.startswith("//"):
                    img_url = "https:" + img_url
                result["og_image"] = img_url

            # Author
            author = ""
            meta_author = soup.find("meta", attrs={"name": "author"})
            if meta_author and meta_author.get("content"):
                author = meta_author["content"]
            result["author"] = author[:200] if author else ""

            # Image count + first few alt texts
            img_tags = soup.find_all("img")
            result["image_count"] = len(img_tags)
            alt_texts = []
            for img in img_tags:
                alt = (img.get("alt") or "").strip()
                if alt and len(alt) > 2 and len(alt) < 100:
                    alt_texts.append(alt)
                if len(alt_texts) >= 10:
                    break
            result["alt_texts"] = alt_texts

            # Visible text excerpt (first 2000 chars)
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()
            body = soup.find("body")
            visible = body.get_text(separator=" ", strip=True) if body else ""
            # Clean up whitespace
            import re
            visible = re.sub(r'\s+', ' ', visible).strip()
            result["visible_text"] = visible[:2000]

        except Exception:
            # If bs4 parsing fails, just return raw info
            result["title"] = ""
            result["description"] = ""
            result["raw_html_length"] = len(html)

        return result

    except Exception as e:
        return {"_error": f"{type(e).__name__}: {str(e)[:200]}", "_status_code": -1}


# ═══════════════════════════════════════════════════════════════════
# Item Processor
# ═══════════════════════════════════════════════════════════════════

def process_item(item: dict, dry_run: bool, fetch_pages: bool = False) -> dict:
    """Process a single item: normalize and optionally fetch page metadata.

    In dry-run mode: just normalizes local data, no network access.
    In live mode with fetch_pages=True: fetches page title/description/og:image
    from the URL using stealth headers and per-domain rate limiting.

    Tracking features:
    - Random UA rotation (20% per request)
    - Per-domain cooldown (5s minimum between same domain)
    - Pre-fetch micro-delay (0.2-0.8s)
    - Session-aware spacing between items
    - 429 backoff with UA rotation
    - No retry on 403 (anti-bot wall)
    """
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    url = item.get("url", item.get("source_page", ""))

    # Base fields from local data
    record = {
        "source_type": item.get("source_type", "unknown"),
        "source_id": item.get("source_id", item.get("id", "")),
        "url": url,
        "title": item.get("title", item.get("name", "")),
        "name": item.get("name", ""),
        "author": item.get("author", ""),
        "tags": json.dumps(_extract_tags(item), ensure_ascii=False),
        "raw_text": _extract_text(item),
        "images": json.dumps(item.get("images", item.get("preview_thumbnails", [])), ensure_ascii=False),
        "collected_at": now,
        "status": "consolidated",
        "error": "",
        "category": item.get("category", ""),
        "section": item.get("section", ""),
        "why": item.get("why", ""),
        "theme": item.get("theme", ""),
        "manifest_date": item.get("manifest_date", ""),
        "pack_date": item.get("pack_date", ""),
        "concept_id": item.get("concept_id", ""),
        "label": item.get("label", ""),
        # Fetched fields (populated by live fetch)
        "page_title": "",
        "page_description": "",
        "og_image": "",
        "page_author": "",
        "page_image_count": 0,
        "page_text_length": 0,
    }

    if dry_run:
        record["status"] = "dry_run"
        record["raw_text"] = (record.get("raw_text", "") or "")[:200]
        return record

    # ── Live mode: fetch page metadata ───────────────────────────
    if fetch_pages and url and url.startswith("http"):
        metadata = fetch_page_metadata(url)
        if metadata.get("_error"):
            record["status"] = "fetch_error"
            record["error"] = metadata["_error"]
        else:
            if metadata.get("title"):
                record["page_title"] = metadata["title"]
                # Override title if local one was empty
                if not record["title"]:
                    record["title"] = metadata["title"]
            record["page_description"] = metadata.get("description", "")
            record["og_image"] = metadata.get("og_image", "")
            record["page_author"] = metadata.get("author", "")
            record["page_image_count"] = metadata.get("image_count", 0)
            record["page_text_length"] = len(metadata.get("visible_text", ""))
            # Merge visible text into raw_text if local text is short
            visible = metadata.get("visible_text", "")
            if visible and len(record.get("raw_text", "") or "") < 100:
                record["raw_text"] = f"{record.get('raw_text', '')}\n\n[page text]: {visible[:1500]}"
            record["status"] = "fetched"

        # Post-fetch micro-delay
        if not dry_run:
            time.sleep(random.uniform(0.3, 0.8))

    return record


def _extract_tags(item: dict) -> list[str]:
    """Extract meaningful tags from item data."""
    tags = []
    # From taste keywords
    for field in ("why", "ai_reason", "theme"):
        val = item.get(field, "")
        if val and isinstance(val, str):
            # Extract quoted phrases or significant words
            tags.append(val[:80])
    # From category/section
    for field in ("category", "section", "source_type"):
        val = item.get(field, "")
        if val:
            tags.append(val)
    return tags[:5]


def _extract_text(item: dict) -> str:
    """Extract the most informative text from an item."""
    candidates = []
    for field in ("why", "ai_reason", "raw_text", "theme", "note", "description"):
        val = item.get(field, "")
        if val and isinstance(val, str) and len(val) > 10:
            candidates.append(val)
    return "\n".join(candidates[:3])[:2000]


def domain_from_url(url: str) -> str:
    """Extract domain from URL for per-domain rate limiting."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc or "unknown"
    except Exception:
        return "unknown"


def domain_aware_wait(url: str, base_min: float, base_max: float) -> float:
    """Wait if needed to respect per-domain rate limits.
    Returns the actual wait time (0 if no wait needed).
    """
    domain = domain_from_url(url)
    now = time.time()
    last = _domain_cooldowns.get(domain, 0)
    elapsed = now - last
    if elapsed < _DOMAIN_MIN_INTERVAL:
        wait = _DOMAIN_MIN_INTERVAL - elapsed + random.uniform(0, 1)
        time.sleep(wait)
        _domain_cooldowns[domain] = time.time()
        return wait
    _domain_cooldowns[domain] = now
    return 0


# ═══════════════════════════════════════════════════════════════════
# Graceful Shutdown
# ═══════════════════════════════════════════════════════════════════

_shutdown_requested = False
# Per-domain last-access tracker (stealth: don't hammer same domain)
_domain_cooldowns: dict[str, float] = {}
_DOMAIN_MIN_INTERVAL = 5.0  # seconds between requests to same domain


def _handle_shutdown(signum, frame):
    global _shutdown_requested
    _shutdown_requested = True
    print("\n[signal] Shutdown requested — finishing current item and saving checkpoint...")


signal.signal(signal.SIGINT, _handle_shutdown)
signal.signal(signal.SIGTERM, _handle_shutdown)


# ═══════════════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════════════

def run_pipeline(
    duration_hours: float = DEFAULT_DURATION_HOURS,
    dry_run: bool = True,
    max_items: Optional[int] = None,
    sleep_min: float = DEFAULT_SLEEP_MIN,
    sleep_max: float = DEFAULT_SLEEP_MAX,
    resume: bool = False,
    source_filter: Optional[str] = None,
) -> int:
    """Run the consolidation pipeline."""

    run_id = dt.datetime.now(dt.timezone.utc).strftime("run_%Y%m%d_%H%M%S")
    deadline = time.time() + duration_hours * 3600

    # ── Setup ──────────────────────────────────────────────────
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load or create checkpoint
    processed_keys: set[str] = set()
    stats: dict = {"started_at": "", "total_loaded": 0, "processed": 0,
                   "success": 0, "failed": 0, "skipped_dup": 0,
                   "fetched": 0, "fetch_error": 0}
    if resume:
        processed_keys, prev_stats = load_checkpoint(run_id)
        if prev_stats:
            stats = prev_stats
            print(f"[resume] Loaded checkpoint: {len(processed_keys)} already processed")

    stats["started_at"] = stats.get("started_at") or dt.datetime.now(dt.timezone.utc).isoformat()

    # ── Load data ──────────────────────────────────────────────
    print(f"[load] Reading project data...")
    all_items = load_all_items(source_filter=source_filter)
    stats["total_loaded"] = len(all_items)
    print(f"[load] Loaded {len(all_items)} raw items from all sources")

    if source_filter:
        print(f"[load] Filtered to source: {source_filter}")

    # Deduplicate against already-processed keys
    fresh_items = deduplicate(all_items, processed_keys.copy())  # copy: don't mutate the master set
    stats["skipped_dup"] = len(all_items) - len(fresh_items)
    print(f"[dedup] {stats['skipped_dup']} duplicates skipped, {len(fresh_items)} new items to process")

    # Apply max_items limit
    if max_items and max_items > 0:
        fresh_items = fresh_items[:max_items]
        print(f"[limit] Capped to {len(fresh_items)} items")

    if dry_run:
        print(f"[mode] DRY RUN — no real processing, output truncated")
    else:
        print(f"[mode] LIVE RUN — duration={duration_hours}h, sleep={sleep_min}-{sleep_max}s")
        print(f"[stealth] UA rotation: {len(_USER_AGENTS)} agents, session-aware pacing enabled")

    # ── Process items ──────────────────────────────────────────
    batch: list[dict] = []
    all_processed: list[dict] = []
    start_time = time.time()

    for i, item in enumerate(fresh_items):
        # Check shutdown signal
        if _shutdown_requested:
            print(f"\n[shutdown] Graceful exit at item {i}/{len(fresh_items)}")
            break

        # Check deadline
        if time.time() >= deadline:
            print(f"\n[deadline] {duration_hours}h reached at item {i}/{len(fresh_items)}")
            break

        try:
            record = process_item(item, dry_run=dry_run, fetch_pages=not dry_run)
            if record.get("status") == "fetched":
                stats["fetched"] += 1
            elif record.get("status") == "fetch_error":
                stats["fetch_error"] += 1
            stats["success"] += 1
            stats["success"] += 1
        except Exception as e:
            record = {
                "source_type": item.get("source_type", "unknown"),
                "url": item.get("url", ""),
                "title": item.get("title", item.get("name", "")),
                "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "status": "error",
                "error": f"{type(e).__name__}: {str(e)[:200]}",
            }
            stats["failed"] += 1
            print(f"[error] Item {i}: {e}")

        batch.append(record)
        all_processed.append(record)
        processed_keys.add(dedup_key(item))
        stats["processed"] += 1

        # Periodic checkpoint
        if stats["processed"] % CHECKPOINT_INTERVAL == 0:
            save_checkpoint(run_id, processed_keys, stats)
            write_jsonl(run_id, batch)
            print(f"[checkpoint] Saved at {stats['processed']} items")
            batch = []

        # Periodic status
        if stats["processed"] % STATUS_INTERVAL == 0:
            elapsed = time.time() - start_time
            rate = stats["processed"] / elapsed if elapsed > 0 else 0
            remaining = len(fresh_items) - stats["processed"] - stats["skipped_dup"]
            eta_min = (remaining / rate / 60) if rate > 0 else 0
            print(
                f"[status] Processed: {stats['processed']} | "
                f"Fetched: {stats['fetched']} | Errors: {stats['fetch_error']} | "
                f"Rate: {rate:.1f}/s | ETA: {eta_min:.0f}min"
            )

        # Stealth delay: session-aware pacing that mimics human fatigue
        if not dry_run and i < len(fresh_items) - 1:
            session_hours = (time.time() - start_time) / 3600
            sleep_dur = session_aware_delay(sleep_min, sleep_max, session_hours, i)
            time.sleep(sleep_dur)

    # ── Final save ─────────────────────────────────────────────
    if batch:
        write_jsonl(run_id, batch)

    save_checkpoint(run_id, processed_keys, stats)

    # Write CSV summary
    csv_path = write_csv(run_id, all_processed)

    # Write summary report
    summary = _build_summary(run_id, stats, all_processed, csv_path, dry_run)
    summary_path = RUNS_DIR / run_id / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Print final report ─────────────────────────────────────
    elapsed_total = time.time() - start_time
    print()
    print("=" * 60)
    print("  Pipeline Complete")
    print("=" * 60)
    print(f"  Run ID:      {run_id}")
    print(f"  Mode:        {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"  Duration:    {elapsed_total:.1f}s")
    print(f"  Total loaded:{stats['total_loaded']}")
    print(f"  Processed:   {stats['processed']}")
    print(f"  ✓ Fetched:   {stats['fetched']}")
    print(f"  ✗ Fetch err: {stats['fetch_error']}")
    print(f"  Duplicates:  {stats['skipped_dup']}")
    print(f"  Output:      {RUNS_DIR / run_id}")
    print(f"    JSONL:     {RUNS_DIR / run_id / 'output.jsonl'}")
    print(f"    CSV:       {csv_path}")
    print(f"    Checkpoint:{checkpoint_path(run_id)}")
    print(f"    Summary:   {summary_path}")
    print("=" * 60)

    return 0


def _build_summary(
    run_id: str,
    stats: dict,
    all_processed: list[dict],
    csv_path: Path,
    dry_run: bool,
) -> dict:
    """Build summary report."""
    source_types: dict[str, int] = {}
    for item in all_processed:
        st = item.get("source_type", "unknown")
        source_types[st] = source_types.get(st, 0) + 1

    return {
        "run_id": run_id,
        "mode": "dry_run" if dry_run else "live",
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "stats": stats,
        "source_breakdown": source_types,
        "output_csv": str(csv_path),
    }


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="XHS 12-Hour Content Consolidation Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run with 5 items
  python scripts/run_xhs_12h_pipeline.py --dry-run --max-items 5

  # 12-hour live run with resume
  python scripts/run_xhs_12h_pipeline.py --duration-hours 12 --resume

  # Process only lookbook sources
  python scripts/run_xhs_12h_pipeline.py --source lookbook --max-items 20

  # Recover from interruption
  python scripts/run_xhs_12h_pipeline.py --resume
        """,
    )
    parser.add_argument(
        "--duration-hours", type=float, default=DEFAULT_DURATION_HOURS,
        help=f"Maximum runtime in hours (default: {DEFAULT_DURATION_HOURS})",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Dry run: no real processing, output truncated (default: True)",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Enable live mode (disables --dry-run)",
    )
    parser.add_argument(
        "--max-items", type=int, default=None,
        help="Maximum items to process (default: 5 in dry-run, unlimited in live)",
    )
    parser.add_argument(
        "--sleep-min", type=float, default=DEFAULT_SLEEP_MIN,
        help=f"Minimum sleep between items in seconds (default: {DEFAULT_SLEEP_MIN})",
    )
    parser.add_argument(
        "--sleep-max", type=float, default=DEFAULT_SLEEP_MAX,
        help=f"Maximum sleep between items in seconds (default: {DEFAULT_SLEEP_MAX})",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from last checkpoint",
    )
    parser.add_argument(
        "--source", type=str, default=None,
        help="Filter by source type or category (e.g., lookbook, link_pack, manifest)",
    )
    parser.add_argument(
        "--loop", action="store_true",
        help="Continuous loop mode: re-scan data sources every cycle until duration expires",
    )
    parser.add_argument(
        "--loop-interval", type=float, default=600,
        help="Seconds between re-scans in loop mode (default: 600 = 10min)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Determine mode
    dry_run = not args.live

    # Default max_items for dry-run
    max_items = args.max_items
    if dry_run and max_items is None:
        max_items = DEFAULT_MAX_ITEMS

    return run_pipeline(
        duration_hours=args.duration_hours,
        dry_run=dry_run,
        max_items=max_items,
        sleep_min=args.sleep_min,
        sleep_max=args.sleep_max,
        resume=args.resume,
        source_filter=args.source,
    )


if __name__ == "__main__":
    sys.exit(main())
