#!/usr/bin/env python3
"""Generate a sources dashboard HTML page.

Usage: python scripts/source_dashboard.py
Output: data/sources.html
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "taste_graph.db"
YIELD_PATH = BASE_DIR / "data" / "source_yield.json"
OUTPUT = BASE_DIR / "data" / "sources.html"


def build():
    db = sqlite3.connect(str(DB_PATH))

    # Load yield streaks
    yields = {}
    if YIELD_PATH.exists():
        try:
            yields = json.loads(YIELD_PATH.read_text())
        except Exception:
            pass

    rows = db.execute("""
        SELECT s.name, s.source_type, s.status, s.url, s.discovered_from,
               s.ai_reason, COUNT(i.id) as imgs,
               MAX(i.created_at) as last_img
        FROM sources s
        LEFT JOIN images i ON s.id = i.source_id
        GROUP BY s.name
        ORDER BY imgs DESC
    """).fetchall()

    # Failure counts
    fail_counts = {}
    for r in db.execute("SELECT source_name, COUNT(*) FROM scrape_failures GROUP BY source_name").fetchall():
        fail_counts[r[0]] = r[1]

    cards = []
    for name, stype, status, url, disc, reason, imgs, last_img in rows:
        streak = yields.get("", 0)
        # Look up by source name — but DB has different IDs. Try matching by name.
        # Actually source_yield uses source_id from DB, not name. Skip for now.
        status_emoji = "🟢" if status == "approved" else "⏸" if status == "deferred" else "⚪"
        fails = fail_counts.get(name, 0)
        last = last_img[:10] if last_img else "—"

        cards.append({
            "name": name,
            "type": stype,
            "status": status,
            "url": url,
            "reason": reason or "",
            "images": imgs,
            "fails": fails,
            "last": last,
            "emoji": status_emoji,
        })

    db.close()

    card_html = []
    for c in cards:
        tag_class = {
            "lookbook": "tag-lb", "article": "tag-art",
            "video": "tag-vid", "photo": "tag-photo", "mixed": "tag-mix",
        }.get(c["type"], "tag-mix")

        zero_class = "zero-yield" if c["images"] == 0 else ""
        card_html.append(f"""
    <div class="card {zero_class}">
      <div class="card-top">
        <span class="status">{c["emoji"]}</span>
        <span class="name">{c["name"]}</span>
        <span class="tag {tag_class}">{c["type"]}</span>
        <a href="{c["url"]}" target="_blank" class="url" title="{c["url"]}">🔗</a>
      </div>
      <div class="card-stats">
        <span class="stat"><strong>{c["images"]}</strong> 图片</span>
        <span class="stat"><strong>{c["fails"]}</strong> 失败</span>
        <span class="stat">最近: {c["last"]}</span>
      </div>
      <div class="card-reason">{c["reason"][:120]}</div>
    </div>""")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>信息源看板 — TasteGraph</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "PingFang SC", sans-serif; background: #f5f5f5; margin: 0; padding: 20px; color: #222; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ font-size: 24px; margin: 0 0 4px; }}
  .sub {{ color: #999; font-size: 13px; margin-bottom: 20px; }}
  .stats {{ display: flex; gap: 16px; margin-bottom: 24px; }}
  .stat-box {{ background: white; padding: 16px 24px; border-radius: 8px; flex: 1; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  .stat-box .num {{ font-size: 28px; font-weight: 700; }}
  .stat-box .label {{ font-size: 13px; color: #999; margin-top: 4px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }}
  .card {{ background: white; border-radius: 10px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); transition: transform 0.1s; }}
  .card:hover {{ transform: translateY(-1px); box-shadow: 0 3px 12px rgba(0,0,0,0.1); }}
  .card.zero-yield {{ border-left: 3px solid #ff4444; opacity: 0.7; }}
  .card-top {{ display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }}
  .card-top .name {{ font-weight: 700; font-size: 14px; flex: 1; }}
  .card-top .status {{ font-size: 14px; }}
  .card-top .url {{ font-size: 14px; text-decoration: none; }}
  .tag {{ font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 600; }}
  .tag-lb {{ background: #e3f2fd; color: #1976d2; }}
  .tag-art {{ background: #fce4ec; color: #c62828; }}
  .tag-vid {{ background: #e8f5e9; color: #2e7d32; }}
  .tag-photo {{ background: #fff3e0; color: #e65100; }}
  .tag-mix {{ background: #f3e5f5; color: #7b1fa2; }}
  .card-stats {{ display: flex; gap: 16px; font-size: 13px; color: #666; margin-bottom: 8px; }}
  .card-reason {{ font-size: 12px; color: #aaa; font-style: italic; }}
  .footer {{ text-align: center; color: #ccc; font-size: 12px; margin-top: 24px; }}
</style>
</head>
<body>
<div class="wrap">
<h1>📡 信息源看板</h1>
<div class="sub">{len(cards)} 个源 · 最后更新 {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>

<div class="stats">
  <div class="stat-box">
    <div class="num">{sum(c["images"] for c in cards)}</div>
    <div class="label">总图片</div>
  </div>
  <div class="stat-box">
    <div class="num">{sum(1 for c in cards if c["images"] > 0)}</div>
    <div class="label">活跃源</div>
  </div>
  <div class="stat-box">
    <div class="num">{sum(1 for c in cards if c["images"] == 0)}</div>
    <div class="label">零产出</div>
  </div>
  <div class="stat-box">
    <div class="num">{sum(c["fails"] for c in cards)}</div>
    <div class="label">抓取失败</div>
  </div>
</div>

<div class="grid">
{''.join(card_html)}
</div>

<div class="footer">TasteGraph AI · 源管理 · link_sources.json</div>
</div>
</body>
</html>"""

    OUTPUT.write_text(html, encoding="utf-8")
    return OUTPUT


if __name__ == "__main__":
    path = build()
    print(f"✅ {path}")
    print(f"   open {path}")
