#!/usr/bin/env python3
"""Generate publish packs from today's scraped images.

Produces:
  posts/YYYY-MM-DD/
  ├── post-001/
  │   ├── image.jpg          # the image
  │   ├── title.txt          # 标题
  │   ├── body.txt           # 正文
  │   ├── hashtags.txt       # 话题标签
  │   └── publish-checklist.md
  ├── post-002/
  ├── ...
  └── QUEUE.html             # 审稿总览页

Usage:
  python scripts/generate_publish_packs.py           # 从今日图片挑
  python scripts/generate_publish_packs.py --date 2026-06-25
  python scripts/generate_publish_packs.py --count 5  # 挑几张
"""

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
from datetime import date as date_type, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from taste_graph_ai.config import BASE_DIR, ensure_dirs
from taste_graph_ai.container import get_container
from taste_graph_ai.infrastructure.db.connection import init_db, get_db
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.infrastructure.repos.images import ImageRepository
from taste_graph_ai.infrastructure.repos.sources import SourceRepository
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.feedback import FeedbackRepository
from taste_graph_ai.domain.enums import ImageStatus
from taste_graph_ai.services.clip import get_clip


POSTS_DIR = BASE_DIR / "posts"
HASHTAGS = ["#moodboard", "#审美积累", "#穿搭参考"]

# Taste concept bank for CLIP auto-tagging when keywords are missing
TASTE_CONCEPTS = [
    "brutalist architecture", "concrete texture", "minimal interior",
    "runway silhouette", "tailored coat", "denim archive",
    "editorial fashion", "street style", "quiet luxury",
    "industrial design", "object still life", "shadow and light",
    "low saturation", "film grain", "black and white",
    "coffee table", "wool fabric", "leather detail",
    "vintage furniture", "Japanese design", "city walking",
    "hotel lobby", "airport transit", "museum interior",
    "sneaker detail", "shirt collar", "sunglasses reflection",
    "steel surface", "glass facade", "espresso cup",
]


async def generate(date_str: str = None, count: int = 5, skip_queue: bool = False) -> Path:
    """Generate publish packs for the given date."""
    if date_str is None:
        date_str = date_type.today().isoformat()

    batch_dir = POSTS_DIR / date_str
    batch_dir.mkdir(parents=True, exist_ok=True)

    ensure_dirs()
    await init_db()
    get_container()
    get_clip()  # pre-load CLIP

    db = await get_db()
    image_repo = ImageRepository(db)
    source_repo = SourceRepository(db)
    pack_repo = PackRepository(db)
    feedback_repo = FeedbackRepository(db)

    # Get liked image IDs for scoring bonus
    liked_ids = await feedback_repo.get_liked_image_ids()

    # Build source name lookup from DB (not graph — different IDs)
    all_sources = await source_repo.list_all()
    source_names: dict[str, str] = {s.id: s.name for s in all_sources}

    # Get recent images that are SELECTED (already used in packs) or PENDING
    candidates = await image_repo.list_by_status(ImageStatus.SELECTED, limit=100)
    if len(candidates) < count:
        pending = await image_repo.list_by_status(ImageStatus.PENDING, limit=200)
        candidates.extend(pending)

    if not candidates:
        print("No images available.")
        await db.close()
        return batch_dir

    # Filter: must have local_path
    valid = [img for img in candidates if img.local_path and Path(img.local_path).exists()]
    print(f"Found {len(valid)} valid images to choose from.")

    # Score and pick top-N diverse images
    clip_svc = get_clip()
    graph = get_container().taste_graph

    # ── Content pillar rotation ──
    # Each pillar gets a different CLIP reference text for scoring diversity
    PILLARS = [
        {"name": "lookbook", "weight": 0.3, "clip_text": "editorial fashion runway silhouette tailored coat"},
        {"name": "daily_archive", "weight": 0.2, "clip_text": "city walking coffee table hotel lobby airport transit concrete shadow"},
        {"name": "moving_taste", "weight": 0.15, "clip_text": "fashion film campaign video experimental moving image cinematic"},
        {"name": "reading_taste", "weight": 0.15, "clip_text": "magazine layout editorial design typography article cultural observation"},
        {"name": "product_seeds", "weight": 0.2, "clip_text": "object still life industrial design notebook tote desk object minimal product"},
    ]

    # Get previously used pillars this week to rotate
    today = date_type.today()
    week_ago = (today - timedelta(days=7)).isoformat()
    recent_packs = await pack_repo.get_latest_packs(20)
    recent_pillars_used = set()
    for rp in recent_packs:
        if rp.date >= week_ago:
            # Detect pillar from theme keywords
            theme_lower = rp.theme.lower()
            if any(kw in theme_lower for kw in ["runway", "秀场", "lookbook", "coat", "silhouette", "tailored"]):
                recent_pillars_used.add("lookbook")
            elif any(kw in theme_lower for kw in ["city", "coffee", "hotel", "travel", "street", "window"]):
                recent_pillars_used.add("daily_archive")
            elif any(kw in theme_lower for kw in ["video", "film", "moving", "cinematic"]):
                recent_pillars_used.add("moving_taste")
            elif any(kw in theme_lower for kw in ["article", "reading", "magazine", "editorial", "layout"]):
                recent_pillars_used.add("reading_taste")
            elif any(kw in theme_lower for kw in ["object", "product", "design", "industrial", "notebook", "tote"]):
                recent_pillars_used.add("product_seeds")
            else:
                recent_pillars_used.add("daily_archive")  # default

    # Prioritize unused pillars this week
    active_pillars = [p for p in PILLARS if p["name"] not in recent_pillars_used]
    if not active_pillars:
        active_pillars = PILLARS  # all used, cycle back

    # Score each image — with diversity bonus
    scored = []
    for img in valid:
        score = 0.0
        # Graph score (25%)
        graph_score = graph.score_content(
            keywords=img.keywords,
            source_id=img.source_id or "",
        )
        score += min(1.0, graph_score / 10) * 0.25

        # CLIP score against primary taste anchor (25%)
        try:
            clip_sim = clip_svc.compute_similarity(
                img.local_path,
                "editorial fashion low-saturation brutalist archive quiet minimal"
            )
            score += clip_sim * 0.25
        except Exception:
            score += 0.15

        # ── Diversity bonus: non-runway source boost ──
        src_name = source_names.get(img.source_id or "", "").lower()
        src_id = img.source_id or ""

        # Non-runway source diversity bonus (15% max)
        runway_indicators = ["vogue", "runway", "off-white", "louis vuitton", "dior", "prada", "gucci"]
        is_runway = any(ind in src_name or ind in src_id.lower() for ind in runway_indicators)
        if not is_runway:
            # Boost non-runway sources so they get visibility
            diversity_bonus = 0.15
        else:
            diversity_bonus = 0.0
        score += diversity_bonus

        # ── Pillar match bonus (15%) ──
        best_pillar_score = 0.0
        for pillar in active_pillars:
            try:
                pillar_sim = clip_svc.compute_similarity(img.local_path, pillar["clip_text"])
                best_pillar_score = max(best_pillar_score, pillar_sim * pillar["weight"])
            except Exception:
                pass
        score += best_pillar_score * 0.15

        # Source exploration bonus (10%) — newer sources get a boost
        from taste_graph_ai.services.images import ImageFetchService
        exploration = ImageFetchService._exploration_bonus(img)  # 0-0.25
        score += exploration * 0.10

        # Previously liked bonus (10%)
        try:
            if img.id in liked_ids:
                score += 0.10
        except Exception:
            pass

        scored.append((score, img, is_runway))

    scored.sort(key=lambda x: x[0], reverse=True)

    # ── Pick diverse top-N ──
    # Strategy: mix runway and non-runway, enforce source diversity, pillar balance
    picked = []
    used_sources: set[str] = set()
    used_pillars: set[str] = set()
    runway_count = 0
    max_runway = max(count // 2, 2)  # at most half can be runway

    for score, img, is_runway in scored:
        src = img.source_id or ""

        # Skip if source already used (strict diversity)
        if src in used_sources:
            continue

        # Cap runway picks
        if is_runway and runway_count >= max_runway:
            continue

        picked.append((score, img))
        used_sources.add(src)
        if is_runway:
            runway_count += 1

        if len(picked) >= count:
            break

    # If we didn't get enough, relax runway cap
    if len(picked) < count:
        for score, img, is_runway in scored:
            src = img.source_id or ""
            if src in used_sources:
                continue
            picked.append((score, img))
            used_sources.add(src)
            if len(picked) >= count:
                break

    # Generate post folders
    post_dirs = []
    for i, (score, img) in enumerate(picked):
        post_num = f"post-{i + 1:03d}"
        post_dir = batch_dir / post_num
        post_dir.mkdir(parents=True, exist_ok=True)

        # Copy image
        src_path = Path(img.local_path)
        ext = src_path.suffix or ".jpg"
        dest_path = post_dir / f"image{ext}"
        shutil.copy2(src_path, dest_path)

        # Generate metadata
        src_name = source_names.get(img.source_id or "", "")
        keywords = _clean_keywords(list(img.keywords))
        # Fallback: CLIP auto-tag if no useful keywords
        if not keywords and img.local_path:
            keywords = _clip_auto_tag(img.local_path, clip_svc)
            img.keywords = keywords

        # Detect pillar for this image
        pillar = _detect_image_pillar(img, src_name, clip_svc)

        title, body, hashtags = _generate_post_metadata(img, score, src_name, keywords, pillar)

        # Write files
        (post_dir / "title.txt").write_text(title, encoding="utf-8")
        (post_dir / "body.txt").write_text(body, encoding="utf-8")
        (post_dir / "hashtags.txt").write_text(hashtags, encoding="utf-8")
        (post_dir / "score.txt").write_text(f"{score:.2f}", encoding="utf-8")
        (post_dir / "pillar.txt").write_text(pillar, encoding="utf-8")

        # Checklist
        checklist = f"""# Post {post_num} — Publish Checklist

- [ ] 图片方向正确（竖版优先）
- [ ] 标题无误：「{title}」
- [ ] 正文无误
- [ ] 话题标签完整
- [ ] 位置/地点是否需要
- [ ] @用户是否需要
- [ ] 发布
"""
        (post_dir / "publish-checklist.md").write_text(checklist, encoding="utf-8")

        post_dirs.append(post_dir)
        print(f"  {post_num}: {title} (score={score:.2f})")

    # Generate QUEUE.html overview (skip in auto mode)
    if not skip_queue:
        _generate_queue_html(batch_dir, post_dirs, date_str)

    await db.close()
    print(f"\n✅ {len(post_dirs)} publish packs saved to {batch_dir}")
    print(f"   Open {batch_dir / 'QUEUE.html'} to review")
    return batch_dir


# Auto-generated / accessibility alt texts that should never be used as keywords
_BAD_KEYWORD_PATTERNS = [
    "image may contain", "person standing", "person sitting",
    "indoor", "outdoor", "clothing", "apparel", "footwear",
    "accessories", "fashion", "photo", "picture", "photograph",
    "no description", "untitled", "img", "image",
]


def _clip_auto_tag(image_path: str, clip_svc, top_n: int = 4) -> list[str]:
    """Use CLIP to find which taste concepts best match this image."""
    try:
        scores = clip_svc.batch_similarity(
            [image_path] * len(TASTE_CONCEPTS),
            "",  # unused — but batch_similarity takes (paths, text)
        )
        # Actually, batch_similarity takes a list of paths and a single text.
        # We need the reverse: one image vs many texts.
        # Let's do it manually per concept.
        results = []
        img_emb = clip_svc.embed_image(image_path)
        if img_emb is None:
            return []
        import numpy as np
        img_vec = np.array(img_emb)
        for concept in TASTE_CONCEPTS:
            text_emb = clip_svc.embed_text(concept)
            if text_emb is None:
                continue
            sim = float(np.dot(img_vec, np.array(text_emb)))
            # Map from [-0.2, 0.5] → [0, 1]
            sim_norm = max(0.0, min(1.0, (sim + 0.2) / 0.7))
            results.append((concept, sim_norm))
        results.sort(key=lambda x: x[1], reverse=True)
        # Pick top concepts, shorten them
        return [r[0][:20] for r in results[:top_n]]
    except Exception:
        return []


def _clean_keywords(keywords: list[str]) -> list[str]:
    """Filter out auto-generated alt-text garbage."""
    clean = []
    for kw in keywords:
        kw_lower = kw.lower().strip()
        # Skip if too long or too short
        if len(kw) < 2 or len(kw) > 30:
            continue
        # Skip auto-generated descriptions
        if any(bad in kw_lower for bad in _BAD_KEYWORD_PATTERNS):
            continue
        clean.append(kw.strip()[:20])
    return clean[:5]


def _generate_post_metadata(img, score: float, source_name: str = "", keywords: list[str] = None, pillar: str = "daily_archive") -> tuple[str, str, str]:
    """Generate title, body, hashtags for a single post.

    Strategy: prefer AI-generated copy when available. Fall back to
    keyword-driven catalog-style labels only when AI is unreachable.
    The AI prompt is aligned with taste_ip_system.md voice standards.
    The pillar hint adjusts the AI prompt angle for diversity.
    """
    if keywords is None:
        keywords = _clean_keywords(list(img.keywords))

    # Try AI generation first (with pillar context)
    ai_title, ai_body = _ai_generate_post_copy(source_name, keywords, img, pillar)

    if ai_title and ai_body:
        title = ai_title
        body = ai_body
    else:
        # Fallback: improved catalog-style (better than old template)
        title, body = _fallback_post_copy(source_name, keywords, pillar)

    # Hashtags: keep them useful but not spammy
    hashtags = _generate_hashtags(source_name, keywords, pillar)

    return title, body, hashtags


def _detect_image_pillar(img, source_name: str, clip_svc) -> str:
    """Detect which content pillar this image best fits."""
    pillar_texts = {
        "lookbook": "editorial fashion runway silhouette tailored coat",
        "daily_archive": "city walking coffee table hotel lobby airport transit concrete shadow",
        "moving_taste": "fashion film campaign video experimental moving image cinematic",
        "reading_taste": "magazine layout editorial design typography article cultural observation",
        "product_seeds": "object still life industrial design notebook tote desk object minimal product",
    }

    src_lower = source_name.lower()
    # Quick source-based detection
    if any(kw in src_lower for kw in ["vogue", "runway", "brand", "fashion-show"]):
        return "lookbook"
    if any(kw in src_lower for kw in ["video", "film", "moving", "vimeo", "showstudio"]):
        return "moving_taste"
    if any(kw in src_lower for kw in ["article", "editorial", "magazine", "ssense", "guardian"]):
        return "reading_taste"
    if any(kw in src_lower for kw in ["design", "industrial", "product", "object", "rams", "muji"]):
        return "product_seeds"

    # CLIP-based detection
    if img.local_path:
        try:
            best_pillar = "daily_archive"
            best_sim = 0.0
            for pillar, text in pillar_texts.items():
                sim = clip_svc.compute_similarity(img.local_path, text)
                if sim > best_sim:
                    best_sim = sim
                    best_pillar = pillar
            if best_sim > 0.2:
                return best_pillar
        except Exception:
            pass

    return "daily_archive"


def _ai_generate_post_copy(source_name: str, keywords: list[str], img, pillar: str = "daily_archive") -> tuple[str, str]:
    """Use AI to generate a taste-driven post title and body.

    Returns (title, body) or ("", "") on failure.
    """
    try:
        from taste_graph_ai.infrastructure.ai.client import AIClient

        kw_str = ", ".join(keywords[:8]) if keywords else "editorial, archive, low-saturation"
        src_str = source_name or "archive"

        # Pillar-specific angle hints
        pillar_hints = {
            "lookbook": "Focus on silhouette, fabric, proportion, styling logic. This is a runway/lookbook observation.",
            "daily_archive": "Focus on everyday objects, city moments, hotel lobbies, coffee tables. Like a visual diary entry.",
            "moving_taste": "Focus on pacing, framing, attitude, cinematic energy. This is about moving image aesthetics.",
            "reading_taste": "Focus on cultural observation, editorial judgment. This reads like a magazine note.",
            "product_seeds": "Focus on objects, materials, industrial design. This could become a product reference.",
        }
        angle_hint = pillar_hints.get(pillar, pillar_hints["daily_archive"])

        prompt = f"""You write Xiaohongshu captions for a personal taste archive account.
Style: quiet, editorial, like Hidden NY meets a private visual diary.
NOT influencer. NOT marketing. NOT "姐妹们冲".

Account rules:
- Titles are taste judgments, not descriptions
- Body is like a museum label: brand, material, year, city. Short fragments. Periods.
- Never: 氛围, 感觉, 安静, 柔和, 光线, 午后, 美, 高级, 绝了, 氛围感
- Never: cute, luxury logo, influencer energy
- Good titles: "最近越来越喜欢不主动讨好的东西", "灰。羊毛。没有logo。", "冷调建筑内衬"
- Good body: "RAF SIMONS. AW 1998. Antwerp." or "灰色羊毛。落肩。没有多余的东西。"
- Max 3-4 fragments in body. 30-80 chars total.
- Body is museum label + 1 cultural observation line max.

Today's angle: {angle_hint}
Source: {src_str}
Image keywords: {kw_str}

Return ONLY valid JSON (no markdown, no ```json):
{{"title": "12-25 chars Chinese title. A taste judgment, not a description. Like a catalog label with attitude.", "body": "30-80 chars. Museum label fragments with periods. Brand. Year. Material. City. One cultural line max. No feelings. No weather."}}"""

        # Use sync HTTP call to avoid async-in-sync event loop issues
        import os, json as _json
        import urllib.request
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            return "", ""

        req = urllib.request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=_json.dumps({
                "model": "deepseek-chat",
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            }).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=30)
        data = _json.loads(resp.read())
        text = data["choices"][0]["message"]["content"]
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
        result = _json.loads(text)

        if result and result.get("title") and result.get("body"):
            # Validate and clean
            title = _polish_title(result["title"])
            body = _polish_body(result["body"])
            if title and body:
                return title, body
    except Exception:
        pass

    return "", ""


def _fallback_post_copy(source_name: str, keywords: list[str], pillar: str = "daily_archive") -> tuple[str, str]:
    """Fallback: keyword-driven catalog-style copy (better than old template).

    Uses taste_ip_system.md voice rules even in fallback mode.
    """
    # Abbreviate source name
    short_src = source_name
    for prefix in ["Vogue Runway - ", "Vogue "]:
        if short_src.startswith(prefix):
            short_src = short_src[len(prefix):]
    short_src = short_src.replace("Magazine", "").strip()

    # Title: taste judgment format when possible
    if keywords and len(keywords) >= 2:
        # Use the first two meaningful keywords
        kw_clean = [k.replace(" ", "").replace("-", "").replace("_", "") for k in keywords[:3] if len(k) > 2]
        if kw_clean:
            title = " · ".join(kw_clean[:2])
        else:
            title = f"{short_src} · 编辑档案" if short_src else "编辑档案"
    else:
        title = f"{short_src} · 编辑档案" if short_src else "编辑档案"

    # Body: catalog label fragments
    parts = []
    if short_src:
        parts.append(short_src)
    parts.append("2024")
    if keywords:
        material_words = [k for k in keywords[:4] if len(k) > 3]
        if material_words:
            parts.append(" · ".join(material_words[:3]))
    body = "。".join(parts[:3]) + "。"

    return title, body


def _polish_title(title: str) -> str:
    """Clean and validate AI-generated title."""
    import re
    # Strip emoji, hashtags
    title = re.sub(r'#\S+', '', title)
    title = re.sub(r'[\U0001F300-\U0001F9FF☀-➿⭐✀-➿️‍]', '', title)
    # Strip excessive punctuation
    title = re.sub(r'！+', '', title)
    title = re.sub(r'。+$', '', title)
    title = re.sub(r' +', ' ', title).strip()
    # Cap at 30 chars
    if len(title) > 30:
        title = title[:28] + '…'
    return title


def _polish_body(body: str) -> str:
    """Clean and validate AI-generated body."""
    import re
    body = re.sub(r'#\S+', '', body)
    body = re.sub(r'[\U0001F300-\U0001F9FF☀-➿⭐✀-➿️‍]', '', body)
    body = re.sub(r' +', ' ', body).strip()
    # Cap at 120 chars
    if len(body) > 120:
        body = body[:117] + '...'
    return body


def _generate_hashtags(source_name: str, keywords: list[str], pillar: str = "daily_archive") -> str:
    """Generate relevant but minimal hashtags (no spam)."""
    tags = ["#moodboard", "#审美积累", "#穿搭参考"]

    # Add 2-3 keyword tags
    if keywords:
        added = 0
        for kw in keywords[:4]:
            tag = kw.replace(" ", "").replace("-", "").replace("_", "")
            if len(tag) >= 2 and tag not in str(tags):
                tags.append(f"#{tag}")
                added += 1
                if added >= 2:
                    break

    # Source-topic tag
    src_lower = str(source_name).lower()
    if "runway" in src_lower or "vogue" in src_lower:
        tags.append("#秀场笔记")
    elif "dieter" in src_lower or "rams" in src_lower:
        tags.append("#工业设计")
    elif "032c" in src_lower or "ssense" in src_lower:
        tags.append("#编辑视角")
    elif "architecture" in src_lower or "brutalist" in src_lower:
        tags.append("#建筑美学")

    # Pillar-specific tags
    pillar_tags = {
        "lookbook": "#穿搭笔记",
        "daily_archive": "#日常灵感",
        "moving_taste": "#影像审美",
        "reading_taste": "#文化笔记",
        "product_seeds": "#设计参考",
    }
    if pillar in pillar_tags and pillar_tags[pillar] not in tags:
        tags.append(pillar_tags[pillar])

    return " ".join(tags[:6])


PILLAR_LABELS = {
    "lookbook": "👔 Lookbook",
    "daily_archive": "📔 日常档案",
    "moving_taste": "🎬 影像",
    "reading_taste": "📖 阅读",
    "product_seeds": "🔧 产品",
}


def _generate_queue_html(batch_dir: Path, post_dirs: list[Path], date_str: str):
    """Generate an editorial workbench QUEUE.html.

    Features:
    - Inline editable title, body, hashtags (click to edit)
    - Pillar labels for content diversity awareness
    - One-click copy, Preview open, Finder reveal
    - Publish status tracking + feedback recording button
    - Pillar distribution summary at the top
    """
    cards = []
    pillar_counts = {}

    for i, post_dir in enumerate(post_dirs):
        title = (post_dir / "title.txt").read_text(encoding="utf-8").strip()
        body = (post_dir / "body.txt").read_text(encoding="utf-8").strip()
        hashtags = (post_dir / "hashtags.txt").read_text(encoding="utf-8").strip()
        score = (post_dir / "score.txt").read_text().strip() if (post_dir / "score.txt").exists() else "0.00"
        pillar = "daily_archive"
        if (post_dir / "pillar.txt").exists():
            pillar = (post_dir / "pillar.txt").read_text(encoding="utf-8").strip()
        pillar_counts[pillar] = pillar_counts.get(pillar, 0) + 1

        img_file = list(post_dir.glob("image.*"))
        img_abs = str(img_file[0]) if img_file else ""
        img_rel = str(img_file[0].relative_to(batch_dir)) if img_file else ""
        post_id = post_dir.name

        pillar_label = PILLAR_LABELS.get(pillar, "📔")

        cards.append(f"""
    <div class="card" id="{post_id}" data-pillar="{pillar}">
      <input type="checkbox" class="select-cb" data-post="{post_id}" checked>
      <div class="card-num">#{i+1}<br><span class="pillar-tag">{pillar_label}</span></div>
      <img src="{img_rel}" class="card-img"
           data-abs="{img_abs}"
           ondblclick="openInPreview('{img_abs}')"
           title="双击在 Preview 中打开 → 拖到小红书">
      <div class="card-body">
        <div class="card-title" contenteditable="true" data-file="{post_dir}/title.txt" data-post="{post_id}">{title}</div>
        <div class="card-text" contenteditable="true" data-file="{post_dir}/body.txt" data-post="{post_id}">{body}</div>
        <div class="card-tags" contenteditable="true" data-file="{post_dir}/hashtags.txt" data-post="{post_id}">{hashtags}</div>
        <div class="card-meta">Score: {score} · Pillar: {pillar}</div>
      </div>
      <div class="card-actions">
        <button onclick="openInPreview('{img_abs}', this)" title="在 Preview 中打开 → 拖进小红书">🖼 打开</button>
        <button onclick="copyImage('{img_abs}', this)" title="复制图片到剪贴板 → Cmd+V 到小红书">📋 图片</button>
        <button onclick="copyAll('{post_id}')" title="复制标题+正文+标签">📝 文案</button>
        <button onclick="saveEdits('{post_id}')" title="保存编辑到文件">💾 保存</button>
        <button onclick="fetch('/open-folder?path=' + encodeURIComponent('{img_abs}'))">📁</button>
        <button onclick="recordFeedback('{post_id}')" title="发布后录入互动数据" style="color:#ff2442">📊 反馈</button>
      </div>
      <div class="card-status" id="status-{post_id}" onclick="togglePublished('{post_id}')">⏳</div>
    </div>""")

    # Pillar distribution summary
    pillar_summary = " · ".join(f"{PILLAR_LABELS.get(k, k)}: {v}" for k, v in pillar_counts.items())

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>编辑工作台 — {date_str}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "PingFang SC", sans-serif; background: #f0f0f0; margin: 0; padding: 20px; }}
  .header {{ max-width: 960px; margin: 0 auto 12px; display: flex; justify-content: space-between; align-items: flex-start; }}
  .header h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .header .date {{ color: #999; font-size: 13px; }}
  .header .pillars {{ font-size: 12px; color: #666; margin-top: 4px; }}

  .toolbar {{ max-width: 960px; margin: 0 auto 16px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
  .toolbar button {{ padding: 8px 16px; border: 1px solid #ccc; border-radius: 6px; background: white; cursor: pointer; font-size: 13px; }}
  .toolbar button:hover {{ background: #eee; }}
  .toolbar button.primary {{ background: #222; color: white; border-color: #222; }}
  .toolbar button.save-all {{ background: #007aff; color: white; border-color: #007aff; }}

  .queue {{ max-width: 960px; margin: 0 auto; }}
  .card {{
    display: flex; gap: 16px; align-items: flex-start;
    background: white; border-radius: 10px; padding: 16px; margin-bottom: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    transition: transform 0.15s, box-shadow 0.15s;
    border-left: 3px solid transparent;
  }}
  .card[data-pillar="lookbook"] {{ border-left-color: #6b7db3; }}
  .card[data-pillar="daily_archive"] {{ border-left-color: #8b9d83; }}
  .card[data-pillar="moving_taste"] {{ border-left-color: #b38b6b; }}
  .card[data-pillar="reading_taste"] {{ border-left-color: #9b7bb3; }}
  .card[data-pillar="product_seeds"] {{ border-left-color: #b36b7b; }}
  .card:hover {{ transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
  .card.published {{ opacity: 0.45; }}
  .card-num {{ font-size: 13px; color: #bbb; font-weight: 700; min-width: 42px; padding-top: 4px; text-align: center; }}
  .pillar-tag {{ font-size: 10px; color: #999; font-weight: 400; display: block; margin-top: 2px; }}
  .card-img {{
    width: 120px; height: 120px; object-fit: cover; border-radius: 6px;
    cursor: pointer; flex-shrink: 0;
    border: 2px solid transparent; transition: border-color 0.2s;
  }}
  .card-img:hover {{ border-color: #ff2442; }}
  .card-body {{ flex: 1; min-width: 0; }}
  .card-title {{
    font-size: 16px; font-weight: 700; margin-bottom: 6px; color: #111;
    padding: 2px 4px; border-radius: 3px; outline: none;
    border: 1px solid transparent; transition: border-color 0.2s;
  }}
  .card-title:focus {{ border-color: #007aff; background: #f8f9ff; }}
  .card-text {{
    font-size: 13px; color: #555; margin-bottom: 6px; line-height: 1.5;
    white-space: pre-line; padding: 2px 4px; border-radius: 3px; outline: none;
    border: 1px solid transparent; transition: border-color 0.2s;
    min-height: 24px;
  }}
  .card-text:focus {{ border-color: #007aff; background: #f8f9ff; }}
  .card-tags {{
    font-size: 11px; color: #999; word-break: break-all;
    padding: 2px 4px; border-radius: 3px; outline: none;
    border: 1px solid transparent; transition: border-color 0.2s;
  }}
  .card-tags:focus {{ border-color: #007aff; background: #f8f9ff; }}
  .card-meta {{ font-size: 10px; color: #ccc; margin-top: 4px; }}
  .card-actions {{ display: flex; flex-direction: column; gap: 4px; flex-shrink: 0; }}
  .card-actions button {{
    padding: 5px 10px; border: 1px solid #ddd; border-radius: 4px;
    background: white; cursor: pointer; font-size: 11px; white-space: nowrap;
    text-align: left;
  }}
  .card-actions button:hover {{ background: #f5f5f5; border-color: #bbb; }}
  .card-status {{ font-size: 20px; min-width: 36px; text-align: center; padding-top: 4px; cursor: pointer; }}

  /* Feedback modal */
  .modal-overlay {{
    display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.4); z-index: 1000;
    justify-content: center; align-items: center;
  }}
  .modal-overlay.show {{ display: flex; }}
  .modal {{
    background: white; border-radius: 12px; padding: 24px; max-width: 400px; width: 90%;
    box-shadow: 0 8px 30px rgba(0,0,0,0.2);
  }}
  .modal h2 {{ font-size: 18px; margin: 0 0 16px; }}
  .modal label {{ display: block; font-size: 13px; color: #666; margin-bottom: 4px; }}
  .modal input {{ width: 100%; padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; margin-bottom: 12px; }}
  .modal .row {{ display: flex; gap: 8px; }}
  .modal .row input {{ flex: 1; }}
  .modal button {{ padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }}
  .modal .btn-save {{ background: #ff2442; color: white; }}
  .modal .btn-cancel {{ background: #eee; }}

  .select-cb {{ margin-top: 6px; width: 16px; height: 16px; cursor: pointer; flex-shrink: 0; }}

  .toast {{
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    background: #222; color: #fff; padding: 10px 24px; border-radius: 8px;
    font-size: 14px; z-index: 1999; animation: fadeOut 2s forwards;
    pointer-events: none;
  }}
  @keyframes fadeOut {{ 0%,60% {{ opacity:1; }} 100% {{ opacity:0; }} }}

  .footer {{ text-align: center; color: #bbb; font-size: 12px; margin-top: 24px; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>✏️ 编辑工作台</h1>
    <div class="date">{date_str} · {len(post_dirs)} 篇待发</div>
    <div class="pillars">{pillar_summary}</div>
  </div>
  <div style="font-size:13px;color:#999;text-align:right">
    点击文字直接编辑 · 双击图片打开 Preview<br>
    <a href="/sources" style="color:#666">📡 信息源</a> ·
    <a href="#" onclick="showWeeklyReport()" style="color:#666">📊 周报</a>
  </div>
</div>

<div class="toolbar">
  <button onclick="selectAll()">☑ 全选</button>
  <button onclick="deselectAll()">☐ 取消全选</button>
  <button class="primary" onclick="openSelected()">📁 打开选中图片</button>
  <button class="save-all" onclick="saveAllEdits()">💾 全部保存</button>
  <button onclick="markAllDone()">✅ 全部标为已发</button>
  <select id="pillar-filter" onchange="filterByPillar(this.value)" style="padding:8px 12px;border:1px solid #ccc;border-radius:6px;font-size:13px;margin-left:auto">
    <option value="all">🏷 全部 pillar</option>
    <option value="lookbook">👔 Lookbook</option>
    <option value="daily_archive">📔 日常档案</option>
    <option value="moving_taste">🎬 影像</option>
    <option value="reading_taste">📖 阅读</option>
    <option value="product_seeds">🔧 产品</option>
  </select>
  <span style="font-size:13px;color:#999" id="counter">{len(post_dirs)} 篇待发</span>
</div>

<div class="queue">
{''.join(cards)}
</div>

<!-- Feedback Modal -->
<div class="modal-overlay" id="feedback-modal">
  <div class="modal">
    <h2>📊 录入互动数据</h2>
    <div style="font-size:12px;color:#999;margin-bottom:12px">从小红书创作者后台查看笔记数据</div>
    <label>Pack ID</label>
    <input type="text" id="fb-pack-id" readonly>
    <div class="row">
      <div><label>❤️ 点赞</label><input type="number" id="fb-likes" value="0"></div>
      <div><label>⭐ 收藏</label><input type="number" id="fb-saves" value="0"></div>
    </div>
    <div class="row">
      <div><label>💬 评论</label><input type="number" id="fb-comments" value="0"></div>
      <div><label>🔄 分享</label><input type="number" id="fb-shares" value="0"></div>
    </div>
    <div style="margin-top:16px;display:flex;gap:8px;justify-content:flex-end">
      <button class="btn-cancel" onclick="closeFeedback()">取消</button>
      <button class="btn-save" onclick="submitFeedback()">提交到图谱</button>
    </div>
  </div>
</div>

<!-- Weekly Report Modal -->
<div class="modal-overlay" id="report-modal">
  <div class="modal" style="max-width:500px">
    <h2>📊 发布效果周报</h2>
    <div id="report-content" style="font-size:13px;line-height:1.8;max-height:400px;overflow-y:auto">加载中...</div>
    <div style="margin-top:16px;text-align:right">
      <button class="btn-cancel" onclick="closeReport()">关闭</button>
    </div>
  </div>
</div>

<div class="footer">
  双击图片 → Preview → 拖进小红书 · 点击文字直接编辑 · 💾 保存到文件 · 📊 发布后录入反馈
</div>

<script>
// ── Open image in Preview ──
async function openInPreview(path, btn) {{
    if (btn) {{ btn.innerText = '...'; btn.disabled = true; }}
    try {{
        const resp = await fetch('/open-file?path=' + encodeURIComponent(path));
        const data = await resp.json();
        if (data.ok) toast('✅ Preview 已打开 → 拖图片到小红书');
        else toast('❌ 失败');
    }} catch(e) {{ toast('❌ 请先启动服务: python scripts/queue_server.py'); }}
    if (btn) {{ setTimeout(() => {{ btn.innerText = '🖼 打开'; btn.disabled = false; }}, 1000); }}
}}

// ── Copy ──
function copyToClipboard(text) {{
    navigator.clipboard.writeText(text).then(() => toast('已复制 ✓'));
}}
async function copyImage(path, btn) {{
    if (btn) {{ btn.innerText = '...'; btn.disabled = true; }}
    try {{
        const resp = await fetch('/copy-image?path=' + encodeURIComponent(path));
        const data = await resp.json();
        if (data.ok) toast('✅ 图片已复制到剪贴板 → Cmd+V 到小红书');
        else toast('❌ ' + (data.error || '失败'));
    }} catch(e) {{
        toast('❌ 请先启动服务: bash start.sh serve');
    }}
    if (btn) {{ setTimeout(() => {{ btn.innerText = '📋 图片'; btn.disabled = false; }}, 1000); }}
}}
function copyAll(postId) {{
    const title = document.querySelector('#' + postId + ' .card-title').innerText;
    const body = document.querySelector('#' + postId + ' .card-text').innerText;
    const tags = document.querySelector('#' + postId + ' .card-tags').innerText;
    copyToClipboard(title + '\\n\\n' + body + '\\n\\n' + tags);
}}

// ── Inline editing: save to file ──
async function saveEdits(postId) {{
    const card = document.getElementById(postId);
    const title = card.querySelector('.card-title');
    const body = card.querySelector('.card-text');
    const tags = card.querySelector('.card-tags');

    const titleFile = title.dataset.file;
    const bodyFile = body.dataset.file;
    const tagsFile = tags.dataset.file;

    let saved = 0;
    try {{
        await fetch('/save-file?path=' + encodeURIComponent(titleFile) + '&content=' + encodeURIComponent(title.innerText));
        saved++;
        await fetch('/save-file?path=' + encodeURIComponent(bodyFile) + '&content=' + encodeURIComponent(body.innerText));
        saved++;
        await fetch('/save-file?path=' + encodeURIComponent(tagsFile) + '&content=' + encodeURIComponent(tags.innerText));
        saved++;
    }} catch(e) {{ /* silent */ }}

    // LocalStorage fallback: store edits so they survive refresh
    localStorage.setItem(postId + '-title', title.innerText);
    localStorage.setItem(postId + '-body', body.innerText);
    localStorage.setItem(postId + '-tags', tags.innerText);

    toast('💾 已保存 (' + saved + ' 个文件)');
}}

async function saveAllEdits() {{
    const cards = document.querySelectorAll('.card');
    let count = 0;
    for (const card of cards) {{
        await saveEdits(card.id);
        count++;
    }}
    toast('💾 全部已保存 (' + count + ' 篇)');
}}

// ── Feedback ──
function recordFeedback(postId) {{
    document.getElementById('fb-pack-id').value = postId;
    document.getElementById('feedback-modal').classList.add('show');
}}
function closeFeedback() {{
    document.getElementById('feedback-modal').classList.remove('show');
}}
async function submitFeedback() {{
    const packId = document.getElementById('fb-pack-id').value;
    const likes = parseInt(document.getElementById('fb-likes').value) || 0;
    const saves = parseInt(document.getElementById('fb-saves').value) || 0;
    const comments = parseInt(document.getElementById('fb-comments').value) || 0;
    const shares = parseInt(document.getElementById('fb-shares').value) || 0;

    try {{
        const resp = await fetch('/api/v1/feedback/publish-metrics', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{pack_id: packId, likes, saves, comments, shares, post_url: ''}})
        }});
        const data = await resp.json();
        toast('📊 已录入 · 互动分: ' + data.engagement_score + '/10 · 图谱调权: ' + (data.delta > 0 ? '+' : '') + data.delta);
        closeFeedback();

        // Auto-mark as published
        const card = document.getElementById(packId);
        if (card) {{
            card.classList.add('published');
            document.getElementById('status-' + packId).innerText = '✅';
            updateCounter();
        }}
    }} catch(e) {{
        toast('❌ 录入失败，请确认 API 服务已启动');
    }}
}}

// ── Weekly Report ──
async function showWeeklyReport() {{
    document.getElementById('report-modal').classList.add('show');
    document.getElementById('report-content').innerHTML = '加载中...';
    try {{
        const resp = await fetch('/api/v1/feedback/weekly-report');
        const data = await resp.json();
        let html = '';
        if (data.message) {{
            html = '<p>' + data.message + '</p>';
        }} else {{
            html += '<p><strong>' + data.period + '</strong><br>平均互动分: ' + data.avg_engagement + '/10</p>';
            html += '<p>🔥 高强度: ' + data.high_performers_count + ' 篇 | ❄️ 低互动: ' + data.low_performers_count + ' 篇</p>';
            if (data.top_themes && data.top_themes.length > 0) {{
                html += '<p><strong>🏆 Top 主题:</strong></p><ul>';
                data.top_themes.forEach(t => {{
                    html += '<li>' + t.avg_score + ' — ' + t.theme + ' (' + t.count + '篇, ' + t.total_likes + '赞)</li>';
                }});
                html += '</ul>';
            }}
            if (data.suggestions && data.suggestions.length > 0) {{
                html += '<p><strong>💡 建议:</strong></p><ul>';
                data.suggestions.forEach(s => html += '<li>' + s + '</li>');
                html += '</ul>';
            }}
        }}
        document.getElementById('report-content').innerHTML = html;
    }} catch(e) {{
        document.getElementById('report-content').innerHTML = '<p style="color:red">API 未连接。请先启动: python taste_graph_ai/server.py</p>';
    }}
}}
function closeReport() {{
    document.getElementById('report-modal').classList.remove('show');
}}

// ── Pillar filter ──
function filterByPillar(pillar) {{
    document.querySelectorAll('.card').forEach(card => {{
        if (pillar === 'all' || card.dataset.pillar === pillar) {{
            card.style.display = 'flex';
        }} else {{
            card.style.display = 'none';
        }}
    }});
}}

// ── Published toggle ──
function togglePublished(postId) {{
    const card = document.getElementById(postId);
    const status = document.getElementById('status-' + postId);
    if (card.classList.contains('published')) {{
        card.classList.remove('published');
        status.innerText = '⏳';
    }} else {{
        card.classList.add('published');
        status.innerText = '✅';
    }}
    updateCounter();
}}

// ── Select / Counter ──
function getChecked() {{
    return [...document.querySelectorAll('.select-cb:checked')].map(cb => cb.dataset.post);
}}
function selectAll() {{ document.querySelectorAll('.select-cb').forEach(cb => cb.checked = true); updateCounter(); }}
function deselectAll() {{ document.querySelectorAll('.select-cb').forEach(cb => cb.checked = false); updateCounter(); }}
function openSelected() {{
    const checked = getChecked();
    if (checked.length === 0) {{ toast('请先勾选要打开的卡片'); return; }}
    checked.forEach(postId => {{
        const img = document.querySelector('#' + postId + ' .card-img');
        if (img && img.dataset.abs) {{
            const dir = img.dataset.abs.split('/').slice(0, -1).join('/');
            window.open('file://' + dir, '_blank');
        }}
    }});
}}
function markAllDone() {{
    document.querySelectorAll('.card').forEach(c => c.classList.add('published'));
    document.querySelectorAll('.card-status').forEach(s => s.innerText = '✅');
    updateCounter();
    toast('已标记 ✓');
}}
function updateCounter() {{
    const total = document.querySelectorAll('.card').length;
    const published = document.querySelectorAll('.card.published').length;
    const visible = document.querySelectorAll('.card[style*="display: flex"], .card:not([style*="display"])').length;
    document.getElementById('counter').innerText = (total - published) + ' 待发 · ' + published + ' 已发' + (visible !== total ? ' · ' + visible + ' 显示' : '');
}}

// ── Restore saved edits from localStorage ──
document.querySelectorAll('.card').forEach(card => {{
    const pid = card.id;
    ['title', 'body', 'tags'].forEach(field => {{
        const saved = localStorage.getItem(pid + '-' + field);
        if (saved) {{
            const el = card.querySelector(field === 'title' ? '.card-title' : field === 'body' ? '.card-text' : '.card-tags');
            if (el && el.innerText !== saved) el.innerText = saved;
        }}
    }});
}});

// ── Auto-save on blur ──
document.querySelectorAll('[contenteditable="true"]').forEach(el => {{
    el.addEventListener('blur', function() {{
        const postId = this.dataset.post;
        if (postId) saveEdits(postId);
    }});
}});

// ── Toast ──
function toast(msg) {{
    const t = document.createElement('div');
    t.className = 'toast';
    t.innerText = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2200);
}}
</script>
</body>
</html>"""

    (batch_dir / "QUEUE.html").write_text(html, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="生成小红书发布包")
    parser.add_argument("--date", default=date_type.today().isoformat(), help="日期 (YYYY-MM-DD)")
    parser.add_argument("--count", type=int, default=5, help="生成几篇")
    parser.add_argument("--skip-queue", action="store_true", help="不生成 QUEUE.html（自动模式）")
    args = parser.parse_args()

    asyncio.run(generate(date_str=args.date, count=args.count, skip_queue=args.skip_queue))


if __name__ == "__main__":
    main()
