"""Hourly crawl tick — runs once per CronCreate invocation.

Goal: every hour, capture real page state from anti-crawl-resistant channels
using Playwright (headless Chromium) so the next session can analyze structure
and pick winning scrape strategies. Outputs both per-tick artifacts and a
cumulative ``crawl_logs/proposals.md`` that the user reviews tomorrow.

Targets (round 1; will expand as wins/losses come in):
  - hypebeast.com/fashion      — known Akamai 202
  - grailed.com                — US streetwear resale (user-confirmed "Grill")
  - therealreal.com            — luxury resale comparator
  - duckduckgo HTML search     — proxy for "what others see" of eBay without OAuth
  - en.wikipedia.org/wiki/Online_marketplace — channel-mapping reference

Run: ``python3 -m scripts.hourly_crawl`` from project root, or directly.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("/Volumes/SanDisk2TB/自媒体作品/小红书起号/moodboard-tg-crawl-opt")
LOG_DIR = ROOT / "crawl_logs"
TZ = timezone(timedelta(hours=8))

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("playwright not installed; aborting", file=sys.stderr)
    raise

ARTIFACT_DIR = LOG_DIR / "artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
SHOTS_DIR = ARTIFACT_DIR / "shots"
HTML_DIR = ARTIFACT_DIR / "html"
SHOTS_DIR.mkdir(parents=True, exist_ok=True)
HTML_DIR.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("hypebeast", "https://hypebeast.com/fashion", 18),
    ("grailed", "https://www.grailed.com/", 18),
    ("therealreal", "https://www.therealreal.com/", 18),
    ("duckduckgo_ebay_search", "https://html.duckduckgo.com/html/?q=site%3Aebay.com+snkrdunk+jordan+1", 12),
    ("wiki_marketplace", "https://en.wikipedia.org/wiki/Online_marketplace", 12),
]


def fetch_one(page, label, url, budget_s):
    """Use a pre-made page to navigate + capture. Returns dict."""
    started = time.monotonic()
    record = {
        "label": label,
        "url": url,
        "ts_iso": datetime.now(TZ).isoformat(),
        "ok": False,
        "status": None,
        "elapsed_ms": 0,
        "bytes": 0,
        "blocked_signal": None,
        "note": "",
    }
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=budget_s * 1000)
        # give JS-challenge a moment to settle or challenge to fire
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeout:
            pass  # OK if it never goes idle — we'll snapshot
        elapsed_ms = int((time.monotonic() - started) * 1000)
        record["elapsed_ms"] = elapsed_ms
        if resp is not None:
            record["status"] = resp.status
        body = page.content()
        record["bytes"] = len(body)
        html_path = HTML_DIR / f"{label}.html"
        html_path.write_text(body)
        shot_path = SHOTS_DIR / f"{label}.png"
        page.screenshot(path=str(shot_path), full_page=False)
        # Anti-crawl heuristics — tighten to avoid SPA-shell false positives
        lower = body.lower()
        signals = []
        # Captcha only counts if body is small (real challenge page) OR shows Turnstile/hCaptcha widgets
        is_challenge_page = (
            ("captcha" in lower or "are you human" in lower)
            and (record["bytes"] < 60_000)
        )
        has_turnstile_widget = "challenges.cloudflare.com" in lower or "turnstile" in lower
        if is_challenge_page or has_turnstile_widget:
            signals.append("captcha")
        if "access denied" in lower and record["bytes"] < 30_000:
            signals.append("akamai_block")
        if "checking your browser" in lower or "cloudflare" in lower and "ray id" in lower:
            signals.append("cloudflare_challenge")
        if record["status"] in (202, 403, 429):
            signals.append(f"http_{record['status']}")
        if record["bytes"] < 4_000 and record["status"] == 200:
            signals.append("thin_body")
        record["blocked_signal"] = signals or None
        record["ok"] = record["status"] is not None and 200 <= record["status"] < 400
        return record
    except PlaywrightTimeout as e:
        record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        record["blocked_signal"] = ["playwright_timeout"]
        record["note"] = str(e)[:160]
        return record
    except Exception as e:
        record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        record["blocked_signal"] = [f"exception:{type(e).__name__}"]
        record["note"] = str(e)[:160]
        return record


def run_tick():
    started_iso = datetime.now(TZ).isoformat()
    started_monotonic = time.monotonic()
    hour_stamp = datetime.now(TZ).strftime("%Y-%m-%d-%H")
    tick_log_json = LOG_DIR / f"tick-{hour_stamp}.json"
    tick_log_md = LOG_DIR / f"tick-{hour_stamp}.md"

    records = []
    print(f"[{started_iso}] hourly tick start — {len(TARGETS)} targets", flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            locale="en-US",
            ignore_https_errors=True,
        )
        page = ctx.new_page()
        for label, url, budget in TARGETS:
            rec = fetch_one(page, label, url, budget)
            records.append(rec)
            status = rec.get("status") or -1
            sig = rec.get("blocked_signal") or ["clean"]
            print(f"  [{label}] status={status} bytes={rec['bytes']} sig={sig}", flush=True)
            time.sleep(1.0)  # gentle pacing
        ctx.close()
        browser.close()

    elapsed_total = int((time.monotonic() - started_monotonic) * 1000)
    healthy = sum(1 for r in records if r["ok"] and not r["blocked_signal"])
    blocked = sum(1 for r in records if r.get("blocked_signal"))
    summary = {
        "started_at": started_iso,
        "elapsed_total_ms": elapsed_total,
        "n_targets": len(records),
        "n_healthy": healthy,
        "n_with_signal": blocked,
        "records": records,
    }
    tick_log_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    md = [f"# Tick {hour_stamp}\n",
          f"**Healthy**: {healthy}/{len(records)}  |  **With anti-crawl signal**: {blocked}/{len(records)}  |  **Elapsed**: {elapsed_total//1000}s\n",
          "| Label | Status | Bytes | Signal | Elapsed |",
          "|---|---|---|---|---|"]
    for r in records:
        sig = ",".join(r.get("blocked_signal") or ["clean"])
        md.append(f"| {r['label']} | {r['status']} | {r['bytes']} | {sig} | {r['elapsed_ms']}ms |")
    tick_log_md.write_text("\n".join(md))

    proposals_path = LOG_DIR / "proposals.md"
    with proposals_path.open("a", encoding="utf-8") as fp:
        fp.write(f"\n## Tick {hour_stamp}\n")
        fp.write(f"- Healthy {healthy}/{len(records)} · Blocked {blocked}/{len(records)} · {elapsed_total//1000}s\n")
        for r in records:
            fp.write(f"  - **{r['label']}** → status {r['status']}, {r['bytes']}B, signal={(r.get('blocked_signal') or ['clean'])}\n")
    print(f"[{started_iso}] tick done — wrote {tick_log_json.name} + {tick_log_md.name}", flush=True)
    return summary


if __name__ == "__main__":
    run_tick()
