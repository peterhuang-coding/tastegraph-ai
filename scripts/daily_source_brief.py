#!/usr/bin/env python3
"""
Generate Daily Source Brief - recommended information sources for the user to browse.

Each day, picks 8 approved sources (oldest reviewed first) + 4 newly discovered
sources (from latest crawl) and renders posts/YYYY-MM-DD/SOURCES.html.
"""
import sqlite3
import json
import html
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path("/Volumes/SanDisk2TB/自媒体作品/小红书起号/moodboard-hidden-ny-jjjjound")
DB = PROJECT_ROOT / "data" / "taste_graph.db"
POSTS = PROJECT_ROOT / "posts"


def get_newly_discovered(limit=4):
    """从图谱抓 crawled_loop 有值的 source 节点（新爬的源），按 url 去重。"""
    g = json.loads((PROJECT_ROOT / "data" / "taste_graph.json").read_text())
    nodes = [n for n in g.get("nodes", []) if n.get("type") == "source"]
    new = []
    seen = set()
    for n in nodes:
        props = n.get("properties") or {}
        loop = props.get("crawled_loop")
        if not loop:
            continue
        url = props.get("url") or n.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        new.append({
            "graph_id": n.get("id"),
            "url": url,
            "title": (props.get("title") or "")[:120],
            "anchor": (props.get("anchor") or "")[:80],
            "og_image": props.get("og_image") or "",
            "crawled_loop": loop,
            "source_type": props.get("source_type") or "crawled",
            "collected_at": props.get("collected_at") or "",
        })
    new.sort(key=lambda x: x.get("collected_at") or "", reverse=True)
    return new[:limit]


def _card_newly_html(n, i):
    og = n["og_image"]
    if og:
        thumb = '<img src="%s" loading="lazy" alt="" style="width:80px;height:80px;object-fit:cover;border-radius:4px;border:1px solid var(--border)">' % html.escape(og)
    else:
        thumb = '<div style="width:80px;height:80px;background:var(--bg);border-radius:4px;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:11px">无预览</div>'
    anchor_html = ""
    if n["anchor"]:
        anchor_html = '<div style="font-size:11px;color:var(--text-muted);margin-top:4px">%s</div>' % html.escape(n["anchor"])
    title_safe = html.escape(n["title"] or n["url"][:60])
    url_safe = html.escape(n["url"])
    gid_safe = html.escape(n["graph_id"])
    loop_short = html.escape(n["crawled_loop"][:25])
    url_short = html.escape(n["url"][:80])
    return """
<article class="card new" data-id="%s" style="border-left:3px solid var(--accent)">
  <header>
    <span class="rank">NEW #%d</span>
    <span class="type" style="background:var(--accent);color:white">新发现</span>
    <span class="age">crawl: %s</span>
  </header>
  <div style="display:flex;gap:12px;align-items:flex-start;margin-bottom:10px">
    %s
    <div style="flex:1;min-width:0">
      <h3 style="margin:0 0 4px;font-size:14px">%s</h3>
      <a class="url" href="%s" target="_blank" rel="noopener">%s</a>
      %s
    </div>
  </div>
  <div class="actions">
    <button class="btn go"   data-label="想深挖">想深挖</button>
    <button class="btn done" data-label="已去过">已去过</button>
    <button class="btn skip" data-label="跳过">跳过</button>
    <button class="btn bad"  data-label="不对味">不对味</button>
  </div>
</article>
""" % (gid_safe, i, loop_short, thumb, title_safe, url_safe, url_short, anchor_html)


def _render_newly(newly):
    if not newly:
        return ""
    cards = [_card_newly_html(n, i) for i, n in enumerate(newly, 1)]
    banner_html = """
  <div class="newly-banner" style="background:linear-gradient(135deg,var(--accent),#d96845);color:white;padding:16px 20px;border-radius:8px;margin-bottom:16px">
    <div style="font-size:15px;font-weight:600">今晚新发现 %d 个源</div>
    <div style="font-size:12px;opacity:0.85;margin-top:4px">来自 %s — 这是你今天爬到的新 URL，挨个点进去看一眼</div>
  </div>
%s
""" % (len(newly), html.escape(newly[0]["crawled_loop"][:30]), "".join(cards))
    return banner_html


def _card_approved_html(it, i):
    if it["thumbnails"]:
        thumb_imgs = "".join('<img src="%s" loading="lazy" alt="">' % html.escape(t) for t in it["thumbnails"])
        thumb_html = '<div class="thumbs">' + thumb_imgs + "</div>"
    else:
        thumb_html = '<div class="thumbs empty">无预览</div>'
    label_badge = ""
    if it["today_label"]:
        label_badge = '<span class="badge">%s</span>' % html.escape(it["today_label"])
    age = '%d天前看过' % it["days_old"] if it["days_old"] < 999 else "从未看过"
    return """
<article class="card" data-id="%s">
  <header>
    <span class="rank">#%d</span>
    <span class="score">评分 %.2f</span>
    <span class="type">%s</span>
    %s
    <span class="age">%s</span>
  </header>
  <h3>%s</h3>
  <a class="url" href="%s" target="_blank" rel="noopener">%s</a>
  <p class="reason">%s</p>
  %s
  <div class="actions">
    <button class="btn go"   data-label="想去">想去</button>
    <button class="btn done" data-label="已去过">已去过</button>
    <button class="btn more" data-label="想深挖">想深挖</button>
    <button class="btn skip" data-label="跳过">跳过</button>
    <button class="btn bad"  data-label="不对味">不对味</button>
  </div>
</article>
""" % (it["id"], i, it["score"], html.escape(it["type"] or ""), label_badge, age,
       html.escape(it["name"]), html.escape(it["url"]), html.escape(it["url"][:80]),
       html.escape(it["reason"]), thumb_html)


PAGE_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>每日信息源简报 · {today}</title>
<style>
:root {{
  --bg: #fafaf8; --fg: #1a1a1a; --muted: #777;
  --border: #e0ddd6; --accent: #c84b31;
  --card-bg: #fff; --card-shadow: 0 1px 3px rgba(0,0,0,0.06);
}}
* {{ box-sizing: border-box; }}
body {{
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Helvetica Neue", "PingFang SC", sans-serif;
  color: var(--fg); background: var(--bg); margin: 0; padding: 32px 16px;
}}
.wrap {{ max-width: 880px; margin: 0 auto; }}
header.top {{ margin-bottom: 24px; padding-bottom: 16px; border-bottom: 2px solid var(--fg); }}
h1 {{ margin: 0 0 8px; font-size: 22px; }}
.sub {{ color: var(--muted); font-size: 13px; }}
.legend {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px; padding: 12px 16px; margin-bottom: 24px; font-size: 13px; }}
.card {{
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 18px 20px; margin-bottom: 16px; box-shadow: var(--card-shadow);
}}
.card header {{ display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--muted); margin-bottom: 8px; }}
.card .rank {{ font-weight: 600; color: var(--fg); font-size: 14px; }}
.card .score {{ color: var(--accent); font-weight: 600; }}
.card .type {{ padding: 2px 8px; background: var(--bg); border-radius: 3px; }}
.card .badge {{ padding: 2px 8px; background: var(--accent); color: white; border-radius: 3px; font-size: 11px; }}
.card h3 {{ margin: 0 0 6px; font-size: 17px; }}
.card .url {{ color: #666; font-size: 12px; text-decoration: none; word-break: break-all; display: block; margin-bottom: 8px; }}
.card .url:hover {{ color: var(--accent); text-decoration: underline; }}
.card .reason {{ color: #444; font-size: 13px; margin: 8px 0 12px; }}
.card .thumbs {{ display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; }}
.card .thumbs img {{ width: 110px; height: 80px; object-fit: cover; border-radius: 4px; border: 1px solid var(--border); }}
.card .thumbs.empty {{ color: var(--muted); font-size: 12px; font-style: italic; }}
.card .actions {{ display: flex; gap: 6px; flex-wrap: wrap; }}
.btn {{
  padding: 6px 12px; border: 1px solid var(--border); background: white;
  border-radius: 4px; cursor: pointer; font-size: 13px; transition: all 0.15s;
}}
.btn:hover {{ transform: translateY(-1px); }}
.btn:active {{ transform: translateY(0); }}
.btn.go   {{ border-color: var(--accent); color: var(--accent); }}
.btn.go:hover   {{ background: var(--accent); color: white; }}
.btn.done {{ border-color: #4a7c4a; color: #4a7c4a; }}
.btn.done:hover {{ background: #4a7c4a; color: white; }}
.btn.more {{ border-color: #b8860b; color: #b8860b; }}
.btn.more:hover {{ background: #b8860b; color: white; }}
.btn.skip {{ border-color: #999; color: #777; }}
.btn.skip:hover {{ background: #999; color: white; }}
.btn.bad  {{ border-color: #555; color: #555; }}
.btn.bad:hover  {{ background: #555; color: white; }}
.btn.chosen {{ opacity: 0.4; }}
.toast {{ position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); background: var(--fg); color: white; padding: 10px 18px; border-radius: 4px; opacity: 0; transition: opacity 0.2s; pointer-events: none; font-size: 13px; }}
.toast.show {{ opacity: 1; }}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>每日信息源简报 · {today}</h1>
    <div class="sub">approved {n_approved} 个 + 新发现 {n_newly} 个 · 点按钮给我 feedback</div>
  </header>
  <div class="legend">
    <b>怎么用：</b>挨个打开链接看 1-3 分钟 → 回来点按钮。想去/想深挖的我下次会优先深爬；不对味的剔出图谱。
  </div>
  {newly_html}
  {approved_cards}
</div>
<div class="toast" id="toast"></div>
<script>
const toast = document.getElementById('toast');
function showToast(msg) {{
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 1500);
}}
document.querySelectorAll('.card').forEach(card => {{
  const id = card.dataset.id;
  card.querySelectorAll('.btn').forEach(btn => {{
    btn.addEventListener('click', async () => {{
      const label = btn.dataset.label;
      btn.parentElement.querySelectorAll('.btn').forEach(b => b.classList.add('chosen'));
      btn.classList.remove('chosen');
      btn.disabled = true;
      try {{
        const res = await fetch('/api/v1/feedback/curate-source', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ source_id: id, label }})
        }});
        if (res.ok) showToast('OK ' + label + ' 已写进图谱');
        else showToast('FAIL ' + res.status);
      }} catch(e) {{ showToast('FAIL ' + e.message); }}
      setTimeout(() => btn.disabled = false, 800);
    }});
  }});
}});
</script>
</body>
</html>
"""


def main():
    today = date.today().isoformat()
    out_dir = POSTS / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out_html = out_dir / "SOURCES.html"
    out_json = out_dir / "sources.json"

    newly = get_newly_discovered(limit=4)

    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        SELECT id, name, url, source_type, ai_score, ai_reason,
               preview_thumbnails, reviewed_at
        FROM sources
        WHERE status = 'approved'
        ORDER BY reviewed_at ASC
        LIMIT 8
    """)
    rows = cur.fetchall()
    cur.execute("""
        SELECT target_id, label, created_at
        FROM feedback_log
        WHERE target_type = 'source' AND date(created_at) = date('now')
    """)
    today_feedback = {r[0]: r[1] for r in cur.fetchall()}
    con.close()

    items = []
    for r in rows:
        sid, name, url, stype, score, reason, thumbs, reviewed = r
        try:
            thumbs_list = json.loads(thumbs or "[]")
        except Exception:
            thumbs_list = []
        items.append({
            "id": sid, "name": name, "url": url, "type": stype,
            "score": score or 0.0, "reason": reason or "",
            "thumbnails": thumbs_list[:4],
            "reviewed_at": reviewed,
            "days_old": (
                (datetime.now() - datetime.fromisoformat(reviewed.replace("Z", "+00:00").split(".")[0])).days
                if reviewed else 999
            ),
            "today_label": today_feedback.get(sid, ""),
        })

    out_json.write_text(json.dumps({"approved": items, "newly_discovered": newly}, ensure_ascii=False, indent=2))

    newly_html = _render_newly(newly)
    approved_cards = "".join(_card_approved_html(it, i) for i, it in enumerate(items, 1))

    page = PAGE_TEMPLATE.format(
        today=today,
        n_approved=len(items),
        n_newly=len(newly),
        newly_html=newly_html,
        approved_cards=approved_cards,
    )
    out_html.write_text(page, encoding="utf-8")
    print(f"wrote {out_html}")
    print(f"  {len(items)} approved + {len(newly)} newly_discovered")


if __name__ == "__main__":
    main()