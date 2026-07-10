#!/usr/bin/env python3
"""
Weekly Trend Report
====================
Analyzes recent crawl records (image keywords, source metadata, daily packs)
to produce a structured editorial briefing: "what's rising, what's fading".

Usage:
    python3 scripts/trend_report.py                       # last 7 days
    python3 scripts/trend_report.py --days 14             # last 14 days
    python3 scripts/trend_report.py --output report.md    # custom output path
    python3 scripts/trend_report.py --json                # also output JSON
"""

import argparse
import asyncio
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Project paths ──────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "taste_graph.db"
GRAPH_PATH = DATA_DIR / "taste_graph.json"
DEFAULT_OUTPUT = DATA_DIR / "trend-report-{date}.md"

# Ensure project root is on sys.path for taste_graph_ai imports
sys.path.insert(0, str(PROJECT_ROOT))


# ── Data extraction ────────────────────────────────────────────────────

def load_recent_keywords(days: int) -> list[dict]:
    """Load keywords from images table within the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.isoformat()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(
        """SELECT created_at, keywords_json, source_id, page_url, url
           FROM images
           WHERE created_at >= ?
             AND keywords_json IS NOT NULL
             AND keywords_json != '[]'
           ORDER BY created_at DESC""",
        (cutoff_str,),
    ).fetchall()

    records = []
    for r in rows:
        try:
            kws = json.loads(r["keywords_json"])
        except (json.JSONDecodeError, TypeError):
            kws = []
        if kws:
            records.append({
                "created_at": r["created_at"],
                "keywords": kws,
                "source_id": r["source_id"],
                "page_url": r["page_url"] or "",
                "image_url": r["url"] or "",
            })
    conn.close()
    return records


def load_recent_sources(days: int) -> list[dict]:
    """Load sources added within the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.isoformat()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(
        """SELECT name, source_type, url, ai_reason, created_at
           FROM sources
           WHERE created_at >= ?
           ORDER BY created_at DESC""",
        (cutoff_str,),
    ).fetchall()

    records = [dict(r) for r in rows]
    conn.close()
    return records


def load_recent_packs(days: int) -> list[dict]:
    """Load daily packs (published editorial content) within the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.isoformat()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(
        """SELECT date, theme, why_today, caption, status
           FROM daily_packs
           WHERE date >= ?
           ORDER BY date DESC""",
        (cutoff_str[:10],),
    ).fetchall()

    records = [dict(r) for r in rows]
    conn.close()
    return records


def load_recent_graph_nodes(days: int) -> list[dict]:
    """Load taste graph nodes created/updated recently (concepts, brands, etc.)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.isoformat()

    try:
        with open(GRAPH_PATH) as f:
            graph = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    # Graph nodes don't have universal timestamps; we filter by edges
    # with recent last_updated
    recent_node_ids = set()
    for edge in graph.get("edges", []):
        updated = edge.get("last_updated", "")
        if updated >= cutoff_str:
            recent_node_ids.add(edge.get("source", ""))
            recent_node_ids.add(edge.get("target", ""))

    # Collect concept/brand/mood nodes that are referenced
    recent_nodes = []
    for node in graph.get("nodes", []):
        if node["id"] in recent_node_ids:
            recent_nodes.append({
                "id": node["id"],
                "type": node.get("type", ""),
                "label": node.get("label", ""),
                "description": node.get("properties", {}).get("description", ""),
            })

    return recent_nodes


# ── Stop words (English + Chinese) ─────────────────────────────────────

_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "can", "could", "shall", "should", "may", "might", "it",
    "its", "this", "that", "these", "those", "i", "you", "he", "she",
    "we", "they", "me", "him", "her", "us", "them", "my", "your", "his",
    "its", "our", "their", "not", "no", "nor", "so", "if", "then",
    "than", "too", "very", "just", "about", "also", "up", "out", "off",
    "over", "under", "again", "further", "once", "here", "there", "when",
    "where", "why", "how", "all", "each", "every", "both", "few", "more",
    "most", "some", "any", "none", "one", "two", "three", "first",
    "s", "t", "re", "ve", "ll", "per", "via", "&", "+", "x", "vs",
    "into", "during", "before", "after", "above", "below", "between",
    "through", "am", "pm",
    "des", "les", "une", "du", "de", "la", "le", "que", "est", "pas",
    "screenshot", "shopper",
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
    "什么", "怎么", "因为", "所以", "如果", "虽然", "但是",
    "可以", "可能", "应该", "已经", "还", "才", "再", "又", "就", "都",
    "而", "且", "或", "与", "及", "等", "之", "所", "为", "能", "被",
    "让", "把", "将", "从", "对", "向", "比", "在", "于", "由", "以",
    "给", "用", "做", "成", "作", "从", "第",
    "中", "把", "被", "让", "给", "对", "将", "在",
}


# ── Analysis ───────────────────────────────────────────────────────────

def compute_keyword_trends(
    records: list[dict],
    days: int,
) -> dict:
    """Count keywords and compute rise/trend direction.

    Splits the period into two halves to compare recent vs. earlier frequency.
    """
    if not records:
        return {"all_keywords": [], "rising": [], "fading": [], "total_records": 0}

    # Sort by created_at ascending
    sorted_recs = sorted(records, key=lambda r: r["created_at"])
    mid = len(sorted_recs) // 2
    earlier_half = sorted_recs[:mid]
    later_half = sorted_recs[mid:]

    def is_noise(kw: str) -> bool:
        """Check if a keyword is noise or stop word."""
        kw_lower = kw.strip().lower()
        if kw_lower in _STOP_WORDS:
            return True
        if re.match(r'^\d{4}$', kw_lower):
            return True
        if re.match(r'^\d+$', kw_lower):
            return True
        if re.match(r'^[a-z]$', kw_lower):
            return True
        if len(kw_lower) <= 1:
            return True
        if kw_lower.endswith(".") or kw_lower.endswith("?"):
            return True
        # Filter out long phrases (full sentences / article titles)
        if len(kw_lower) > 35:
            return True
        # Filter out multi-word phrases that look like article titles or news headlines
        word_count = len(kw_lower.split())
        if word_count > 4:
            return True
        if word_count > 3 and len(kw_lower) > 20:
            # Check for title-like patterns
            title_indicators = r'\b(the|best|from|photos|shows|collection|spring|summer|fall|winter|menswear|brand|magazine|exit|collab|sneakers|technical|fabrics|sweater)\b'
            if re.search(title_indicators, kw_lower):
                return True
        # Filter out single words that are just common nouns not useful for trend analysis
        if len(kw_lower.split()) == 1:
            w = kw_lower.strip()
            # Very short (single letter + maybe one more)
            if len(w) <= 2:
                return True
            # Pure numbers with trailing characters
            if re.match(r'^\d+\w*$', w):
                return True
        return False

    def clean_keyword(kw: str) -> str:
        """Clean a single keyword: strip punctuation, normalize."""
        kw = kw.strip()
        # Remove trailing punctuation
        kw = re.sub(r'[.。，,?!;:：；？！]+$', '', kw)
        kw = re.sub(r'^[.。，,?!;:：；？！\s]+', '', kw)
        # Remove embedded quotes (from CLIP output like product" name)
        kw = kw.replace('"', '').replace("'", "").replace('"', '')
        # Remove content in parentheses (product variants)
        kw = re.sub(r'\s*\([^)]*\)\s*', ' ', kw)
        # Normalize whitespace
        kw = re.sub(r'\s+', ' ', kw)
        # Remove leading/trailing dashes
        kw = kw.strip(' -–—')
        return kw.strip()

    def normalize_keyword(kw: str) -> str:
        """Normalize a keyword for comparison."""
        if re.match(r'^[\x00-\x7F]+$', kw):
            return kw.lower()
        return kw

    def flatten_keywords(recs):
        c = Counter()
        for r in recs:
            for kw in r["keywords"]:
                cleaned = clean_keyword(kw)
                if not cleaned or is_noise(cleaned):
                    continue
                normalized = normalize_keyword(cleaned)
                if normalized and len(normalized) > 1:
                    c[normalized] += 1
        return c

    earlier = flatten_keywords(earlier_half)
    later = flatten_keywords(later_half)
    all_keyword_counts = flatten_keywords(sorted_recs)

    # Build keyword list with counts and direction
    keyword_list = []
    for kw, count in all_keyword_counts.most_common(80):
        earlier_count = earlier.get(kw, 0)
        later_count = later.get(kw, 0)
        total = earlier_count + later_count
        if total < 2:
            continue  # skip noise
        # Calculate change percentage
        if earlier_count > 0:
            pct_change = round((later_count - earlier_count) / earlier_count * 100)
        else:
            pct_change = 100 if later_count > 0 else 0

        # Direction
        if pct_change >= 20:
            direction = "rising"
        elif pct_change <= -20:
            direction = "fading"
        else:
            direction = "stable"

        keyword_list.append({
            "keyword": kw,
            "count": total,
            "earlier": earlier_count,
            "later": later_count,
            "pct_change": pct_change,
            "direction": direction,
        })

    # Sort: rising first (by pct_change desc), then stable, then fading
    rising = sorted(
        [k for k in keyword_list if k["direction"] == "rising"],
        key=lambda x: -x["pct_change"],
    )[:10]
    fading = sorted(
        [k for k in keyword_list if k["direction"] == "fading"],
        key=lambda x: x["pct_change"],
    )[:10]

    return {
        "all_keywords": keyword_list[:30],
        "rising": rising,
        "fading": fading,
        "total_records": len(records),
        "total_keywords": sum(len(r["keywords"]) for r in records),
    }


def _kw_match(kw: str, ckw: str) -> bool:
    """Check if a keyword matches a cluster keyword (word boundary)."""
    kw_lower = kw.lower()
    ckw_lower = ckw.lower()
    # Direct match
    if kw_lower == ckw_lower:
        return True
    # Check if ckw appears as a word or phrase boundary within kw
    pattern = r'\b' + re.escape(ckw_lower) + r'\b'
    if re.search(pattern, kw_lower):
        return True
    # For single-word cluster keywords, also check if kw is contained (e.g., "lemaire" in "lemaire fw26")
    if ' ' not in ckw_lower:
        if re.search(r'\b' + re.escape(ckw_lower) + r'\b', kw_lower):
            return True
    return False

def extract_theme_clusters(keywords: list[dict]) -> list[dict]:
    """Group related keywords into thematic clusters."""
    # Define theme clusters based on keyword matching
    clusters = {
        "fashion/designer": ["prada", "margiela", "jil sander", "helmut lang", "rick owens",
                              "maison margiela", "acne studios", "lemaire", "loewe", "the row",
                              "dries van noten", "comme des garçons", "yohji yamamoto", "issey miyake",
                              "undercover", "junya watanabe", "ann demeulemeester", "haider ackermann",
                              "raf simons", "phoebe philo", "old céline", "bottega veneta",
                              "gucci", "balenciaga", "prada", "miumiu", "chloé", "dior", "louis vuitton",
                              "saint laurent", "hermes", "chanel", "burberry", "alexander mcqueen",
                              "vivienne westwood", "cdg", "y-3", "visvim", "kapital", "nanamica",
                              "arc'teryx", "stone island", "acronym", "uniform experiment", "sophnet",
                              "wtaps", "neighborhood", "supreme", "palace", "kith", "noah", "aime leon dore",
                              "junya", "undercover", "number (n)ine", "takahiromiyashita the soloist.",
                              "attachment", "roen", "guid i", "m.a+", "paul harnden", "c cp company",
                              "sucs", "deepti", "layer", "dior", "ssense", "runway", "fashion week",
                              "paris fashion week", "milan fashion week", "london fashion week",
                              "tokyo fashion week", "haute couture", "ready-to-wear", "lookbook",
                              "editorial", "campaign", "ad campaign", "fall/winter", "spring/summer",
                              "ss25", "aw25", "fw25", "ss26", "aw26", "fw26", "ss27", "aw27",
                              "couture", "prêt-à-porter", "textile", "fabric", "silhouette", "tailoring",
                              "drape", "layering", "deconstruction", "avant-garde", "minimalist",
                              "grunge", "normcore", "gorpcore", "blokecore", "indie sleaze", "quiet luxury"],
        "architecture/space": ["brutalism", "brutalist", "concrete", "architecture", "brutalist architecture",
                               "modernist", "mid-century", "bauhaus", "minimalist", "japanese architecture",
                               "tadao ando", "le corbusier", "mies van der rohe", "alvar aalto",
                               "louis kahn", "carlo scarpa", "peter zumthor", "john pawson",
                               "david chipperfield", "office", "lobby", "hotel lobby", "hotel",
                               "interior", "space", "room", "apartment", "studio", "loft",
                               "warehouse", "gallery", "museum", "exhibition", "staircase",
                               "corridor", "hallway", "window", "facade", "building", "structure",
                               "column", "beam", "material", "texture", "surface", "wall",
                               "floor", "ceiling", "light", "shadow", "natural light"],
        "city/urban": ["tokyo", "paris", "london", "new york", "berlin", "milan", "kyoto",
                       "osaka", "shanghai", "seoul", "copenhagen", "stockholm", "amsterdam",
                       "los angeles", "san francisco", "mexico city", "marrakech", "东京",
                       "巴黎", "伦敦", "纽约", "柏林", "上海", "北京", "广州", "香港",
                       "city walk", "city", "urban", "street", "street photography",
                       "subway", "metro", "train", "station", "platform", "commute",
                       "walking", "pedestrian", "sidewalk", "pavement", "alley", "laneway",
                       "night", "night city", "neon", "霓虹灯", "rain", "wet", "reflection",
                       "street corner", "crosswalk", "traffic", "parking lot", "rooftop"],
        "object/material": ["plastic", "pvc", "polyester", "nylon", "cotton", "wool", "linen",
                            "leather", "suede", "denim", "canvas", "mesh", "rubber", "silicone",
                            "resin", "acrylic", "metal", "steel", "aluminum", "brass", "copper",
                            "wood", "ceramic", "porcelain", "glass", "stone", "marble", "granite",
                            "terrazzo", "concrete", "brick", "tile", "mosaic", "paper", "cardboard",
                            "fabric", "textile", "thread", "stitch", "seam", "button", "zipper",
                            "velcro", "magnetic", "clip", "buckle", "strap", "handle", "knob",
                            "shelf", "table", "chair", "stool", "bench", "cabinet", "desk",
                            "lamp", "light", "vase", "bowl", "cup", "glass", "bottle", "jar",
                            "book", "magazine", "catalog", "poster", "print", "photograph",
                            "frame", "mirror", "clock", "watch", "phone", "camera", "speaker",
                            "headphone", "keyboard", "mouse", "monitor", "laptop", "computer"],
        "mood/atmosphere": ["quiet", "silent", "calm", "still", "stillness", "serene", "peaceful",
                            "tranquil", "meditative", "contemplative", "thoughtful", "melancholy",
                            "nostalgia", "nostalgic", "wistful", "lonely", "solitude", "alone",
                            "empty", "void", "negative space", "wabi-sabi", "imperfect", "raw",
                            "rough", "weathered", "aged", "patina", "faded", "worn", "distressed",
                            "cracked", "chipped", "scratched", "stained", "dusty", "dirty",
                            "clean", "sterile", "clinical", "cold", "cool", "warm", "cozy",
                            "intimate", "private", "personal", "diary", "journal", "archive",
                            "memory", "time", "temporal", "ephemeral", "transient", "moment"],
        "color": ["black", "white", "grey", "gray", "beige", "cream", "ivory", "off-white",
                  "brown", "tan", "camel", "khaki", "olive", "army green", "navy", "navy blue",
                  "dark blue", "indigo", "denim blue", "slate", "charcoal", "ash", "pewter",
                  "silver", "gold", "pink", "粉色", "pale pink", "dusty pink", "blush",
                  "rose", "coral", "red", "burgundy", "maroon", "wine", "bordeaux",
                  "orange", "rust", "terracotta", "clay", "ochre", "mustard", "yellow",
                  "green", "sage", "mint", "forest green", "lime", "teal", "turquoise",
                  "purple", "lavender", "lilac", "plum", "violet", "monochrome", "monotone",
                  "muted", "desaturated", "low saturation", "pastel", "neutral", "earth tone"],
        "food/drink": ["coffee", "espresso", "latte", "cappuccino", "black coffee", "cold brew",
                       "tea", "green tea", "matcha", "ocha", "sake", "wine", "natural wine",
                       "beer", "whisky", "cocktail", "water", "sparkling water", "tonic",
                       "bread", "pastry", "croissant", "baguette", "sourdough", "rice", "onigiri",
                       "sushi", "ramen", "soba", "udon", "tempura", "yakitori", "izakaya",
                       "market", "farmers market", "grocer", "fruit", "vegetable", "produce",
                       "restaurant", "cafe", "bar", "diner", "bistro"],
        "design/art": ["brutalism", "modernist", "bauhaus", "swiss design", "helvetica",
                       "typography", "typeface", "font", "graphic design", "poster design",
                       "book design", "editorial design", "layout", "grid", "composition",
                       "minimal", "minimalist", "maximalist", "pop art", "abstract", "surreal",
                       "contemporary art", "fine art", "painting", "sculpture", "installation",
                       "photography", "black and white", "b&w", "film photography", "analog",
                       "digital art", "collage", "mixed media", "printmaking", "lithograph",
                       "silkscreen", "etching", "watercolor", "oil painting", "acrylic",
                       "pencil", "ink", "charcoal", "pastel", "ceramic", "pottery", "glass art",
                       "furniture design", "product design", "industrial design", "object design",
                       "dieter rams", "vitsoe", "braun", "muji", "ikea", "hay", "muuto",
                       "&tradition", "fritz hansen", "arflex", "cassina", "knoll", "herman miller",
                       "eames", "nelson", "noguchi", "jacobsen", "panton", "aarnio", "castiglioni"],
        "music/culture": ["jazz", "classical", "ambient", "electronic", "techno", "house",
                          "minimal", "drone", "experimental", "indie", "rock", "punk", "post-punk",
                          "new wave", "synth", "lo-fi", "hip hop", "trap", "r&b", "soul", "funk",
                          "disco", "reggae", "dub", "afrobeat", "world music", "folk", "country",
                          "vinyl", "record", "cassette", "cd", "tape", "walkman", "discman",
                          "record store", "concert", "live", "festival", "club", "dj", "producer",
                          "guitar", "bass", "drums", "piano", "saxophone", "trumpet", "violin",
                          "cello", "synth", "drum machine", "sampler", "mixer", "turntable",
                          "zine", "fanzine", "independent", "underground", "subculture", "counterculture"],
    }

    # Collect all keywords from the analysis
    all_kw_set = {k["keyword"] for k in keywords}

    # Score each cluster
    cluster_scores = []
    for cluster_name, cluster_keywords in clusters.items():
        matches = []
        for kw in all_kw_set:
            for ckw in cluster_keywords:
                if _kw_match(kw, ckw):
                    # Find the original keyword entry
                    for entry in keywords:
                        if entry["keyword"] == kw:
                            matches.append(entry)
                            break
        if matches:
            total_count = sum(m["count"] for m in matches)
            # Compute direction: check if the cluster is mostly rising or fading
            rising_count = sum(1 for m in matches if m["pct_change"] >= 20)
            fading_count = sum(1 for m in matches if m["pct_change"] <= -20)
            stable_count = len(matches) - rising_count - fading_count
            if rising_count > fading_count and rising_count > stable_count:
                direction = "rising"
            elif fading_count > rising_count and fading_count > stable_count:
                direction = "fading"
            else:
                direction = "stable"
            # Compute meaningful avg pct change (exclude 0->100 edge case)
            non_edge = [m for m in matches if m["earlier"] > 0 and m["later"] > 0]
            if non_edge:
                avg_pct = round(sum(m["pct_change"] for m in non_edge) / len(non_edge))
            else:
                avg_pct = 0
            cluster_scores.append({
                "cluster": cluster_name,
                "count": total_count,
                "keywords": [m["keyword"] for m in matches[:8]],
                "avg_pct_change": avg_pct,
                "direction": direction,
            })

    # Sort by count descending
    cluster_scores.sort(key=lambda x: -x["count"])
    return cluster_scores


# ── AI-powered analysis ────────────────────────────────────────────────

async def generate_ai_report(
    keywords_text: str,
    themes_text: str,
    record_count: int,
    days: int,
) -> dict:
    """Use AI to generate the structured trend report."""
    from taste_graph_ai.infrastructure.ai.client import AIClient

    client = AIClient()
    if not client.client:
        # Fallback: return a basic report without AI
        return {"error": "AI not configured", "report": ""}

    prompt = f"""你是一个品味驱动的内容简报分析师。账号调性：冷静、克制、都市、低饱和、Hidden NY / JJJJound 风格。

最近 {days} 天的爬取数据中，共 {record_count} 条记录包含关键词标签。以下是关键词频率统计和主题聚类信息。

请分析并输出一份趋势简报。返回纯 JSON（不要 markdown 代码块）：

{{
  "top_themes": [
    {{"rank": 1, "name": "主题中文名", "mention_count": 数值, "trend_pct": 整数百分比, "description": "一句话说明这个主题"}}
  ],
  "rising": [
    {{"keyword": "关键词", "reason": "为什么上升"}}
  ],
  "fading": [
    {{"keyword": "关键词", "reason": "为什么消退"}}
  ],
  "editorial_picks": [
    {{"topic": "选题建议", "rationale": "为什么本周值得写"}}
  ],
  "summary": "本周整体趋势一句话总结"
}}

关键词频率数据（keyword: 出现次数, 变化百分比）：
{keywords_text[:2000]}

主题聚类数据（cluster: 出现次数, 趋势方向）：
{themes_text[:1000]}

注意：
1. top_themes 最多 5 个，按出现次数排序
2. rising 和 fading 各最多 6 个
3. editorial_picks 最多 3 个
4. 所有返回内容需符合账号调性，不要出现"可爱""甜美""网红""奢华"等不匹配词汇
5. 趋势百分比单位是 %，正数表示上升，负数表示下降"""

    result = await client.chat_json(prompt, max_tokens=1500)
    await client.close()
    return result


# ── Report assembly ────────────────────────────────────────────────────

def build_markdown(
    date_str: str,
    days: int,
    keyword_trends: dict,
    clusters: list[dict],
    ai_report: dict,
    record_count: int,
) -> str:
    """Build the final Markdown report."""
    lines = []
    lines.append(f"# 趋势简报 — {date_str}")
    lines.append("")
    lines.append(f"> 分析周期：过去 {days} 天 | 数据来源：图像标签、内容源、每日发布包")
    lines.append("")

    # ── Top themes ──
    lines.append("## 本周主题")
    lines.append("")
    if ai_report and "top_themes" in ai_report and ai_report["top_themes"]:
        for t in ai_report["top_themes"]:
            name = t.get("name", "未知")
            count = t.get("mention_count", 0)
            trend = t.get("trend_pct", 0)
            desc = t.get("description", "")
            trend_str = f"↑{trend}%" if trend > 0 else (f"↓{abs(trend)}%" if trend < 0 else "持平")
            lines.append(f"1. **{name}** — 出现 {count} 次，{trend_str}")
            if desc:
                lines.append(f"   {desc}")
            lines.append("")
    else:
        # Fallback: use cluster data
        for i, c in enumerate(clusters[:5], 1):
            direction = "↑" if c["direction"] == "rising" else ("↓" if c["direction"] == "fading" else "→")
            lines.append(f"{i}. **{c['cluster']}** — 出现 {c['count']} 次，{direction} {abs(c['avg_pct_change'])}%")
            lines.append("")

    # ── Rising ──
    lines.append("## 上升中")
    lines.append("")
    if ai_report and "rising" in ai_report and ai_report["rising"]:
        for item in ai_report["rising"]:
            kw = item.get("keyword", "")
            reason = item.get("reason", "")
            lines.append(f"- **{kw}** — {reason}")
    else:
        for k in keyword_trends.get("rising", []):
            lines.append(f"- **{k['keyword']}** — 出现 {k['count']} 次，较前半段增长 {k['pct_change']}%")
    lines.append("")

    # ── Fading ──
    lines.append("## 消退中")
    lines.append("")
    if ai_report and "fading" in ai_report and ai_report["fading"]:
        for item in ai_report["fading"]:
            kw = item.get("keyword", "")
            reason = item.get("reason", "")
            lines.append(f"- **{kw}** — {reason}")
    else:
        for k in keyword_trends.get("fading", []):
            lines.append(f"- **{k['keyword']}** — 出现 {k['count']} 次，较前半段下降 {abs(k['pct_change'])}%")
    lines.append("")

    # ── Editorial suggestions ──
    lines.append("## 编辑建议")
    lines.append("")
    if ai_report and "editorial_picks" in ai_report and ai_report["editorial_picks"]:
        for item in ai_report["editorial_picks"]:
            topic = item.get("topic", "")
            rationale = item.get("rationale", "")
            lines.append(f"- **{topic}**")
            lines.append(f"  {rationale}")
            lines.append("")
    else:
        lines.append("（依靠关键词统计：本周值得关注的主题领域已在上方列出，建议结合具体关键词内容策划）")
        lines.append("")

    # ── Summary ──
    if ai_report and "summary" in ai_report and ai_report["summary"]:
        lines.append("## 总编按")
        lines.append("")
        lines.append(ai_report["summary"])
        lines.append("")

    # ── Data sources ──
    lines.append("## 数据来源")
    lines.append("")
    lines.append(f"- 分析覆盖 {keyword_trends['total_records']} 张图片记录")
    lines.append(f"- 共 {keyword_trends['total_keywords']} 个关键词标签")
    lines.append(f"- 来源：`images` 表关键词、`daily_packs` 主题/文案、`sources` 元数据")

    return "\n".join(lines)


def build_json_report(
    date_str: str,
    days: int,
    keyword_trends: dict,
    clusters: list[dict],
    ai_report: dict,
) -> dict:
    """Build the structured JSON report."""
    return {
        "report_date": date_str,
        "analysis_period_days": days,
        "total_records": keyword_trends["total_records"],
        "total_keywords": keyword_trends["total_keywords"],
        "top_themes": ai_report.get("top_themes", []) if ai_report else [],
        "rising_keywords": ai_report.get("rising", keyword_trends.get("rising", [])),
        "fading_keywords": ai_report.get("fading", keyword_trends.get("fading", [])),
        "editorial_picks": ai_report.get("editorial_picks", []) if ai_report else [],
        "summary": ai_report.get("summary", "") if ai_report else "",
        "clusters": clusters[:10],
        "keyword_trends": keyword_trends["all_keywords"][:20],
    }


# ── Main ────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Weekly Trend Report — analyze recent crawl data for editorial insights",
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Number of days to look back (default: 7)",
    )
    parser.add_argument(
        "--output", type=str, default="",
        help="Output path for the Markdown report (default: data/trend-report-YYYY-MM-DD.md)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Also output a JSON version of the report",
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    date_str = datetime.now().strftime("%Y-%m-%d")

    # 1. Load data
    print(f"🔍 加载过去 {args.days} 天的数据...")
    keywords = load_recent_keywords(args.days)
    sources = load_recent_sources(args.days)
    packs = load_recent_packs(args.days)
    graph_nodes = load_recent_graph_nodes(args.days)

    print(f"   - 关键词记录: {len(keywords)}")
    print(f"   - 内容源: {len(sources)}")
    print(f"   - 发布包: {len(packs)}")
    print(f"   - 图谱节点: {len(graph_nodes)}")

    # 2. Compute keyword trends
    print("📊 计算关键词趋势...")
    keyword_trends = compute_keyword_trends(keywords, args.days)
    clusters = extract_theme_clusters(keyword_trends["all_keywords"])

    # 3. AI analysis
    print("🤖 正在调用 AI 生成趋势简报...")
    keywords_text = "\n".join(
        f"  {k['keyword']}: {k['count']}次, 变化 {k['pct_change']:+d}%"
        for k in keyword_trends["all_keywords"][:40]
    )
    themes_text = "\n".join(
        f"  {c['cluster']}: {c['count']}次, 趋势 {c['direction']} ({c['avg_pct_change']:+d}%)"
        for c in clusters[:15]
    )
    ai_report = await generate_ai_report(
        keywords_text, themes_text, keyword_trends["total_records"], args.days,
    )

    if "error" in ai_report:
        print(f"⚠️  AI 未配置，使用纯统计模式: {ai_report['error']}")
        ai_report = {}

    # 4. Build report
    print("📝 生成报告...")
    report_md = build_markdown(
        date_str, args.days, keyword_trends, clusters, ai_report,
        len(keywords),
    )

    # 5. Write output
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path(str(DEFAULT_OUTPUT).format(date=date_str))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_md, encoding="utf-8")
    print(f"✅ 趋势报告已保存到: {output_path}")

    # 6. JSON output
    if args.json:
        json_report = build_json_report(
            date_str, args.days, keyword_trends, clusters, ai_report,
        )
        json_path = output_path.with_suffix(".json")
        json_path.write_text(
            json.dumps(json_report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"✅ JSON 报告已保存到: {json_path}")

    # Print preview
    print("\n" + "=" * 50)
    print("报告预览（前 20 行）:")
    print("=" * 50)
    preview_lines = report_md.split("\n")[:20]
    for line in preview_lines:
        print(line)


if __name__ == "__main__":
    asyncio.run(main())
