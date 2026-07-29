"""Trend Tab API — 潮流趋势简报。

4 端点：
  GET  /api/v1/trend/virtual-lists  — 10 个虚拟分类（含 articles 等）
  GET  /api/v1/trend/snapshot        — 本周上升/消退关键词
  GET  /api/v1/trend/history         — 历史 trend-report-*.md 文件
  POST /api/v1/trend/decide          — 信息员 决策（采用/搁置/弃）
  GET  /api/v1/trend/decisions       — 已决策列表

数据来源：
  - link_sources.json   静态虚拟列表
  - data/taste_graph.db images.keywords_json  关键词聚合
  - data/trend-report-*.md  历史报告
  - data/trend_decisions.json  决策持久化
"""

from fastapi import APIRouter
from pathlib import Path
import json
import re
import sqlite3
from datetime import datetime, timedelta
from collections import Counter

router = APIRouter(prefix="/api/v1/trend", tags=["trend"])

REPO = Path("/Volumes/SanDisk2TB/自媒体作品/小红书起号/moodboard-hidden-ny-jjjjound")
LINK_SOURCES = REPO / "link_sources.json"
TREND_REPORTS_DIR = REPO / "data"
DB_PATH = REPO / "data" / "taste_graph.db"
DECISIONS_FILE = REPO / "data" / "trend_decisions.json"


# --- 1) 虚拟列表（articles 11 源 + 其他分类） ---
@router.get("/virtual-lists")
def virtual_lists():
    """返回 10 个分类 + 每个分类的源数 + articles 完整列表"""
    if not LINK_SOURCES.exists():
        return {"lists": [], "articles": [], "error": "link_sources.json not found"}
    data = json.loads(LINK_SOURCES.read_text())
    lists = []
    for cat, items in data.items():
        if not isinstance(items, list):
            continue
        if cat in ("version", "purpose"):
            continue
        lists.append({
            "category": cat,
            "count": len(items),
            "sample_names": [s.get("name", "") for s in items[:3] if isinstance(s, dict)],
            "items": [
                {"name": s.get("name", ""), "url": s.get("url", ""), "why": s.get("why", "")}
                for s in items if isinstance(s, dict)
            ],
        })
    # 按分类名排序 + articles 排第一
    lists.sort(key=lambda x: (0 if x["category"] == "articles" else 1, x["category"]))
    articles = data.get("articles", [])
    return {"lists": lists, "articles": articles}


# --- 2) 趋势数据（从历史 report + DB） ---
@router.get("/snapshot")
def trend_snapshot(days: int = 14):
    """返回本周主题、上升中、消退中（聚合最近 N 天 images.keywords_json）"""
    if not DB_PATH.exists():
        return {
            "days": days,
            "rising": [],
            "fading": [],
            "total_keywords": 0,
            "error": "taste_graph.db not found",
            "snapshot_at": datetime.utcnow().isoformat(),
        }
    conn = sqlite3.connect(str(DB_PATH))
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    # 收集最近 N 天的 keywords
    try:
        rows = conn.execute(
            """
            SELECT keywords_json, created_at FROM images
            WHERE created_at >= ?
            ORDER BY created_at DESC LIMIT 1000
            """,
            (cutoff,),
        ).fetchall()
    except Exception as e:
        conn.close()
        return {
            "days": days,
            "rising": [],
            "fading": [],
            "total_keywords": 0,
            "error": f"db query failed: {e}",
            "snapshot_at": datetime.utcnow().isoformat(),
        }

    keyword_counter = Counter()
    full_recent = Counter()  # 最近 7 天
    full_old = Counter()     # 8-14 天前
    week_ago_cutoff = (datetime.utcnow() - timedelta(days=days // 2)).isoformat()

    for kj, created_at in rows:
        try:
            kws = json.loads(kj) if kj else []
        except Exception:
            continue
        for k in kws:
            kl = k.lower().strip()
            if not kl:
                continue
            keyword_counter[kl] += 1
            if created_at and created_at >= week_ago_cutoff:
                full_recent[kl] += 1
            else:
                full_old[kl] += 1

    conn.close()

    top = keyword_counter.most_common(20)

    # 上升中：基于「近期 - 远古」差值
    rising = []
    for k, total in top[:30]:
        recent_c = full_recent.get(k, 0)
        old_c = full_old.get(k, 0)
        delta = recent_c - old_c
        rising.append({"keyword": k, "count": total, "recent": recent_c, "delta": delta})
    rising.sort(key=lambda x: (-x["delta"], -x["count"]))

    # 消退中：基于「远古 - 近期」
    fading = []
    for k, total in top[:30]:
        recent_c = full_recent.get(k, 0)
        old_c = full_old.get(k, 0)
        delta_inv = old_c - recent_c
        if old_c == 0 and recent_c == 0:
            continue
        fading.append({"keyword": k, "count": total, "recent": recent_c, "delta": -delta_inv})
    fading.sort(key=lambda x: (-x["delta"], -x["count"]))

    return {
        "days": days,
        "rising": [{"keyword": r["keyword"], "count": r["count"], "recent": r["recent"], "delta": r["delta"]}
                   for r in rising[:6]],
        "fading": [{"keyword": f["keyword"], "count": f["count"], "recent": f["recent"], "delta": f["delta"]}
                   for f in fading[:6]],
        "total_keywords": sum(keyword_counter.values()),
        "unique_keywords": len(keyword_counter),
        "image_count": len(rows),
        "snapshot_at": datetime.utcnow().isoformat(),
    }


# --- 3) 历史报告列表 ---
@router.get("/history")
def trend_history():
    """返回 data/trend-report-*.md 文件列表"""
    reports = []
    if not TREND_REPORTS_DIR.exists():
        return {"reports": []}
    for f in sorted(TREND_REPORTS_DIR.glob("trend-report-*.md"), reverse=True):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
        date_str = m.group(1) if m else ""
        try:
            preview = f.read_text()[:500]
        except Exception:
            preview = ""
        reports.append({
            "filename": f.name,
            "date": date_str,
            "size": f.stat().st_size,
            "preview": preview,
        })
    return {"reports": reports[:10]}


# --- 4) 信息员决策 ---
@router.post("/decide")
def decide(payload: dict):
    """信息员对一个 trend item 做决定"""
    item_keyword = payload.get("keyword")
    decision = payload.get("decision")  # 'adopt' | 'hold' | 'reject'
    if not item_keyword or decision not in ("adopt", "hold", "reject"):
        return {"error": "invalid payload"}

    if DECISIONS_FILE.exists():
        try:
            data = json.loads(DECISIONS_FILE.read_text())
        except Exception:
            data = {"decisions": []}
    else:
        data = {"decisions": []}

    data["decisions"].append({
        "keyword": item_keyword,
        "decision": decision,
        "decided_at": datetime.utcnow().isoformat(),
        "context": payload.get("context", {}),
    })
    DECISIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return {"ok": True, "total": len(data["decisions"])}


@router.get("/decisions")
def list_decisions():
    if not DECISIONS_FILE.exists():
        return {"adopted": [], "held": [], "rejected": []}
    try:
        data = json.loads(DECISIONS_FILE.read_text())
    except Exception:
        return {"adopted": [], "held": [], "rejected": []}

    by_dec = {"adopt": [], "hold": [], "reject": []}
    for d in data.get("decisions", []):
        by_dec.setdefault(d.get("decision", ""), []).append(d)

    return {
        "adopted": by_dec.get("adopt", []),
        "held": by_dec.get("hold", []),
        "rejected": by_dec.get("reject", []),
    }
