"""
Crawler Tab API — source management dashboard.

合并 link_sources.json（声明）与 SQLite sources/images/scrape_failures 表（已注册），
返回完整源清单 + 状态聚合，供前端 🕷 爬虫 tab 渲染。

端点：
  GET /api/v1/crawler/sources   → 所有源（declared + db + orphan）
  GET /api/v1/crawler/stats     → 按分类聚合的统计
"""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/crawler", tags=["crawler"])

# 项目根目录（此 routes 文件位于 taste_graph_ai/api/routes/，向上 3 层）
REPO = Path(__file__).resolve().parents[3]
DB_PATH = REPO / "data" / "taste_graph.db"
LINK_SOURCES = REPO / "link_sources.json"


def _read_link_sources() -> List[Dict[str, Any]]:
    """读取 link_sources.json 中所有 list 类型分类下的源，返回扁平列表。"""
    if not LINK_SOURCES.exists():
        return []
    try:
        with open(LINK_SOURCES, encoding="utf-8") as f:
            link_data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    declared: List[Dict[str, Any]] = []
    for cat, items in link_data.items():
        if not isinstance(items, list):
            continue
        for s in items:
            if isinstance(s, dict) and "name" in s:
                declared.append({
                    "name": s["name"],
                    "category": cat,
                    "url": s.get("url", ""),
                    "why": s.get("why", ""),
                })
    return declared


def _read_db_sources() -> Dict[str, Dict[str, Any]]:
    """读取 SQLite 中已注册的 sources，并 LEFT JOIN images 与 scrape_failures 做聚合。"""
    if not DB_PATH.exists():
        return {}

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        # scrape_failures 可能很多，用子查询而不是 GROUP BY，避免笛卡尔爆炸
        rows = conn.execute(
            """
            SELECT s.id,
                   s.name,
                   s.url        AS db_url,
                   s.source_type,
                   s.status,
                   s.created_at,
                   (SELECT COUNT(*) FROM images i
                    WHERE i.source_id = s.id) AS imgs,
                   (SELECT COUNT(*) FROM scrape_failures sf
                    WHERE sf.source_name = s.name) AS fails
            FROM sources s
            """
        ).fetchall()
    finally:
        conn.close()

    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = dict(r)
        # images 表里 SELECT COUNT(*) 用 INT → JSON 直接可序列化
        out[d["name"]] = {
            "id": d["id"],
            "name": d["name"],
            "db_url": d.get("db_url", ""),
            "source_type": d.get("source_type"),
            "status": d.get("status") or "unknown",
            "created_at": d.get("created_at"),
            "imgs": int(d.get("imgs") or 0),
            "fails": int(d.get("fails") or 0),
        }
    return out


@router.get("/sources")
def list_all_sources():
    """合并 link_sources.json（声明）+ DB（已注册），返回完整源列表 + 状态。"""
    declared = _read_link_sources()
    db_sources = _read_db_sources()

    # 合并：每个 declared 加 DB 字段
    for s in declared:
        in_db = s["name"] in db_sources
        s["in_db"] = in_db
        if in_db:
            db_row = db_sources[s["name"]]
            s["id"] = db_row["id"]
            s["source_type"] = db_row["source_type"]
            s["status"] = db_row["status"]
            s["created_at"] = db_row["created_at"]
            s["imgs"] = db_row["imgs"]
            s["fails"] = db_row["fails"]
        else:
            # 声明了但还没进 DB 也没爬过
            s["status"] = "pending"
            s["source_type"] = None
            s["imgs"] = 0
            s["fails"] = 0
            s["id"] = None
            s["created_at"] = None

    # DB 里有但 link_sources.json 没声明的（孤儿）
    declared_names = {s["name"] for s in declared}
    orphans = []
    for name, row in db_sources.items():
        if name in declared_names:
            continue
        orphans.append({
            "name": name,
            "category": "orphan",
            "url": row.get("db_url", ""),
            "in_db": True,
            "id": row["id"],
            "source_type": row["source_type"],
            "status": row["status"],
            "created_at": row["created_at"],
            "imgs": row["imgs"],
            "fails": row["fails"],
        })

    pending_count = sum(1 for s in declared if not s["in_db"])

    return {
        "total_declared": len(declared),
        "total_in_db": len(db_sources),
        "pending_count": pending_count,
        "orphan_count": len(orphans),
        "sources": declared,
        "orphans": orphans,
    }


@router.get("/stats")
def crawler_stats():
    """总览统计：总数 + 按分类聚合 in_db / pending / imgs / fails。"""
    data = list_all_sources()

    by_category: Dict[str, Dict[str, int]] = {}
    for s in data["sources"]:
        cat = s.get("category", "unknown")
        bucket = by_category.setdefault(cat, {
            "total": 0, "in_db": 0, "pending": 0, "imgs": 0, "fails": 0,
        })
        bucket["total"] += 1
        if s.get("in_db"):
            bucket["in_db"] += 1
            bucket["imgs"] += s.get("imgs", 0)
            bucket["fails"] += s.get("fails", 0)
        else:
            bucket["pending"] += 1

    # 单独把 orphan 也算进 by_category（前端可决定是否显示）
    if data["orphan_count"]:
        orphan_bucket = {
            "total": len(data["orphans"]),
            "in_db": len(data["orphans"]),
            "pending": 0,
            "imgs": sum(o.get("imgs", 0) for o in data["orphans"]),
            "fails": sum(o.get("fails", 0) for o in data["orphans"]),
        }
        by_category["_orphan"] = orphan_bucket

    return {
        "total_declared": data["total_declared"],
        "total_in_db": data["total_in_db"],
        "pending": data["pending_count"],
        "orphans": data["orphan_count"],
        "by_category": by_category,
    }
