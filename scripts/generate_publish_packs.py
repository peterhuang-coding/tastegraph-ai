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


def _resolve_local_path(img) -> str:
    """local_path 列可能过期，按 image_id 在 data/images 下回填（.jpg/.png/.webp）。"""
    lp = getattr(img, "local_path", "") or ""
    if lp and Path(lp).exists():
        return lp
    for ext in (".jpg", ".png", ".webp"):
        p = BASE_DIR / "data" / "images" / f"{img.id}{ext}"
        if p.exists():
            return str(p)
    return ""


async def generate(date_str: str = None, count: int = 5, skip_queue: bool = False, pack_size: int = 1) -> Path:
    """Generate publish packs for the given date.

    pack_size=1 时与旧版一致（每目录单图）；pack_size>1 时一个 pack 目录装 N 张图
    （image-01..NN），供人工审一包 9 图直接发。
    """
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
    source_name_lookup = _build_source_lookup(all_sources)

    # Get recent images that are SELECTED (already used in packs) or PENDING
    target_total = count * pack_size
    candidates = await image_repo.list_by_status(ImageStatus.SELECTED, limit=max(100, target_total))
    pending = await image_repo.list_by_status(ImageStatus.PENDING, limit=3000)
    candidates.extend(pending)

    if not candidates:
        print("No images available.")
        await db.close()
        return batch_dir

    # Filter + backfill: local_path 列可能过期，按 image_id 在 data/images 下回填
    valid = []
    for img in candidates:
        lp = _resolve_local_path(img)
        if lp:
            img.local_path = lp
            valid.append(img)
    print(f"Found {len(valid)} valid images to choose from.")

    # Score and pick top-N diverse images
    clip_svc = get_clip()
    graph = get_container().taste_graph

    # ── 策展打分：图谱关键词 + 历史评分 + pillar 契合（快、可解释、进 curation.json）──
    PILLAR_KEYWORDS = {
        "lookbook": ["runway", "catwalk", "fashion", "model", "editorial", "streetwear", "outfit", "tailored", "silhouette", "coat", "时装", "秀场"],
        "daily_archive": ["city", "street", "coffee", "hotel", "architecture", "concrete", "shadow", "window", "walking", "interior", "街", "城市"],
        "moving_taste": ["film", "video", "cinematic", "motion", "backstage", "campaign", "moving", "影像"],
        "reading_taste": ["magazine", "editorial", "layout", "typography", "print", "archive", "book", "article", "杂志", "阅读"],
        "product_seeds": ["object", "product", "design", "industrial", "still", "furniture", "material", "detail", "watch", "bag", "器物", "设计"],
    }

    # 按 final_score 预筛控制成本，再进图谱/关键词打分
    valid.sort(key=lambda i: getattr(i, "final_score", 0.0) or 0.0, reverse=True)
    pool = valid[:max(200, target_total * 3)]
    print(f"Scoring pool: {len(pool)} (top by final_score)")

    runway_indicators = ["vogue", "runway", "off-white", "louis vuitton", "dior", "prada", "gucci"]

    def _pillar_match(kws, pkws):
        hit = sum(1 for k in kws for pk in pkws if pk in k)
        return min(1.0, hit / 4.0)

    scored = []
    for img in pool:
        kws = [k.lower() for k in _clean_keywords(list(getattr(img, "keywords", []) or []))]
        try:
            graph_score = min(1.0, graph.score_content(
                keywords=list(getattr(img, "keywords", []) or []),
                source_id=img.source_id or "",
            ) / 10)
        except Exception:
            graph_score = 0.0
        try:
            base = max(0.0, min(1.0, float(getattr(img, "final_score", 0.0) or 0.0)))
        except (TypeError, ValueError):
            base = 0.0

        src_name = source_name_lookup(img.source_id or "", getattr(img, "page_url", "") or "").lower()
        src_id = img.source_id or ""
        is_runway = any(ind in src_name or ind in src_id.lower() for ind in runway_indicators)

        pillar_scores = {pname: _pillar_match(kws, pkws) for pname, pkws in PILLAR_KEYWORDS.items()}
        total = (
            graph_score * 0.30
            + base * 0.30
            + max(pillar_scores.values()) * 0.25
            + (0.0 if is_runway else 0.15)
            + (0.10 if img.id in liked_ids else 0.0)
        )
        scored.append({
            "img": img, "total": total, "graph": graph_score, "base": base,
            "pillar_scores": pillar_scores, "is_runway": is_runway,
            "kws": kws, "src": img.source_id or "",
        })

    def _pick_from(ranked, need, used_sources, runway_cap):
        picked = []
        runway_count = 0
        for item in ranked:
            if len(picked) >= need:
                break
            if item["src"] in used_sources:
                continue
            if item["is_runway"] and runway_count >= runway_cap:
                continue
            picked.append(item)
            used_sources.add(item["src"])
            if item["is_runway"]:
                runway_count += 1
        if len(picked) < need:  # 池子不足时放宽来源限制
            for item in ranked:
                if len(picked) >= need:
                    break
                if item not in picked:
                    picked.append(item)
        return picked

    # ── 组包：综合 1 套 + 每 pillar 各 1 套（套内来源多样，套间允许复用）──
    pack_count = min(count, 1 + len(PILLAR_KEYWORDS))
    ranked_all = sorted(scored, key=lambda x: x["total"], reverse=True)
    groups = [_pick_from(ranked_all, pack_size, set(), max(pack_size // 2, 2))]
    for pname in PILLAR_KEYWORDS:
        if len(groups) >= pack_count:
            break
        ranked_p = sorted(scored, key=lambda x: (x["pillar_scores"][pname] * 3 + x["total"]), reverse=True)
        groups.append(_pick_from(ranked_p, pack_size, set(), max(pack_size // 2, 2)))
    print(f"Packed {len(groups)} 套方案（综合 + {len(groups) - 1} pillars）")

    # Generate post/pack folders
    post_dirs = []
    for gi, group in enumerate(groups):
        dir_num = f"pack-{gi + 1:03d}" if pack_size > 1 else f"post-{gi + 1:03d}"
        post_dir = batch_dir / dir_num
        post_dir.mkdir(parents=True, exist_ok=True)

        # 本套 pillar：综合套取图片命中最高者，其余套取对应 pillar
        if gi == 0:
            pillar_totals = {}
            for item in group:
                for pname, s in item["pillar_scores"].items():
                    pillar_totals[pname] = pillar_totals.get(pname, 0.0) + s
            pillar = max(pillar_totals, key=pillar_totals.get)
        else:
            pillar = list(PILLAR_KEYWORDS.keys())[gi - 1]

        metas = []
        keywords_all = []
        source_counts = {}
        # 清理旧帧，避免重复生成残留 image-0N.*（宫格会多帧）
        for stale in post_dir.glob("image-*"):
            try:
                stale.unlink()
            except OSError:
                pass
        for i, item in enumerate(group):
            img = item["img"]
            # Copy image (3:4 竖版裁切，小红书标准)
            src_path = Path(img.local_path)
            ext = src_path.suffix or ".jpg"
            dest_path = post_dir / (f"image-{i + 1:02d}{ext}" if pack_size > 1 else f"image{ext}")
            _prepare_image(src_path, dest_path)

            # Generate metadata
            src_name = source_name_lookup(img.source_id or "", getattr(img, "page_url", "") or "")
            keywords = _clean_keywords(list(img.keywords))
            # Fallback: CLIP auto-tag if no useful keywords
            if not keywords and img.local_path:
                keywords = _clip_auto_tag(img.local_path, clip_svc)
                img.keywords = keywords

            title, body, hashtags = _generate_post_metadata(img, item["total"], src_name, keywords, pillar)
            metas.append((item["total"], title, body, hashtags, pillar, src_name))
            keywords_all.extend(keywords)
            source_counts[src_name] = source_counts.get(src_name, 0) + 1

        # Pack-level metadata: 首图为封面文案，正文为逐图一句话叙事
        avg_score = sum(m[0] for m in metas) / len(metas)
        title = metas[0][1]
        body = "\n".join(f"{i + 1:02d} {m[1]} — {m[5]}" for i, m in enumerate(metas))
        hashtags = metas[0][3]

        # 策展逻辑（图谱依据）→ curation.json，供工作台「为什么是这套」展示
        kw_freq = {}
        for k in keywords_all:
            kw_freq[k] = kw_freq.get(k, 0) + 1
        shared = sorted(kw_freq.items(), key=lambda kv: kv[1], reverse=True)[:6]
        curation = {
            "pillar": pillar,
            "theme": title,
            "shared_keywords": [{"kw": k, "count": v} for k, v in shared if v >= 2],
            "top_keywords": [k for k, _ in shared],
            "sources": sorted(source_counts.items(), key=lambda kv: kv[1], reverse=True),
            "avg_score": round(avg_score, 2),
            "image_count": len(metas),
            "score_formula": "图谱分 30% + 历史评分 30% + pillar 契合 25% + 来源多样性 15%",
        }
        (post_dir / "curation.json").write_text(
            json.dumps(curation, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        (post_dir / "title.txt").write_text(title, encoding="utf-8")
        (post_dir / "body.txt").write_text(body, encoding="utf-8")
        (post_dir / "hashtags.txt").write_text(hashtags, encoding="utf-8")
        (post_dir / "score.txt").write_text(f"{avg_score:.2f}", encoding="utf-8")
        (post_dir / "pillar.txt").write_text(pillar, encoding="utf-8")

        # 观点草稿（机器起草，人改写后才可发）
        opinion_draft = _generate_opinion_draft(
            [m[1] for m in metas], [m[5] for m in metas], pillar
        )
        (post_dir / "opinion_draft.txt").write_text(opinion_draft, encoding="utf-8")

        # Checklist
        post_time = PILLAR_POST_TIMES.get(pillar, "20:00–22:00")
        img_note = (
            "（一包 9 图：Finder 打开目录全选拖入）" if pack_size > 1 else "图片方向正确（竖版优先）"
        )
        checklist = f"""# {dir_num} — Publish Checklist

- [ ] {img_note}
- [ ] 标题无误：「{title}」
- [ ] 正文 = 观点草稿改写版（机器叙事已另存 body.txt，发布用 opinion_draft.txt 改写）
- [ ] 话题标签完整
- [ ] 发布时间建议：{post_time}（本包 pillar: {pillar}）
- [ ] 位置/地点是否需要
- [ ] @用户是否需要
- [ ] 发布后在 http://localhost:8765/publish-log 登记（发帖后 30 秒）
"""
        (post_dir / "publish-checklist.md").write_text(checklist, encoding="utf-8")

        post_dirs.append(post_dir)
        print(f"  {dir_num}: {title} ({len(group)} images, avg score={avg_score:.2f})")

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

# 各 pillar 的小红书黄金发布时段建议
PILLAR_POST_TIMES = {
    "lookbook": "12:00–13:00",
    "daily_archive": "18:00–19:00",
    "moving_taste": "20:00–22:00",
    "reading_taste": "20:00–22:00",
    "product_seeds": "12:00–13:00",
}


def _prepare_image(src_path: Path, dest_path: Path) -> None:
    """中心裁切为 3:4 竖版（小红书标准），过大则缩到 1080×1440。PIL 不可用时原样复制。"""
    try:
        from PIL import Image
    except ImportError:
        shutil.copy2(src_path, dest_path)
        return
    try:
        with Image.open(src_path) as im:
            im = im.convert("RGB")
            w, h = im.size
            target_ratio = 3 / 4
            if w / h > target_ratio:  # 太宽 → 裁宽
                new_w = int(h * target_ratio)
                left = (w - new_w) // 2
                im = im.crop((left, 0, left + new_w, h))
            elif w / h < target_ratio:  # 太高 → 裁高
                new_h = int(w / target_ratio)
                top = (h - new_h) // 2
                im = im.crop((0, top, w, top + new_h))
            if im.width > 1080 or im.height > 1440:
                im.thumbnail((1080, 1440), Image.LANCZOS)
            im.save(dest_path, quality=90)
    except Exception:
        shutil.copy2(src_path, dest_path)


def _slug_words(source_id: str) -> str:
    """'src_off_white' → 'off white'，用于 legacy slug 与 DB 名称的模糊匹配。"""
    return source_id.removeprefix("src_").replace("_", " ").strip()


def _build_source_lookup(all_sources) -> dict[str, str]:
    """images.source_id 有 hex id / legacy slug 两套，且部分指向已删除的源行（孤儿引用）。

    命中顺序: hex id → url → slug 子串匹配 → 图片 page_url 域名匹配（兜底孤儿引用）。
    """
    import urllib.parse

    by_key: dict[str, str] = {}
    by_domain: dict[str, str] = {}
    names = []
    for s in all_sources:
        by_key[s.id] = s.name
        by_key[s.url] = s.name
        names.append(s.name)
        try:
            dom = urllib.parse.urlparse(s.url).netloc
            by_domain.setdefault(dom, s.name)
        except Exception:
            pass

    def lookup(sid: str, page_url: str = "") -> str:
        if sid:
            if sid in by_key:
                return by_key[sid]
            if sid.startswith("src_"):
                cand = _slug_words(sid)
                if cand:
                    matches = [n for n in names if cand in n.lower()]
                    if matches:
                        return min(matches, key=len)
        if page_url:
            try:
                dom = urllib.parse.urlparse(page_url).netloc
                if dom in by_domain:
                    return by_domain[dom]
            except Exception:
                pass
        return ""

    return lookup


def _generate_opinion_draft(titles: list[str], source_names: list[str], pillar: str) -> str:
    """把一包 9 图写成一段连贯的观点草稿。AI 可用则 AI，否则模板拼接。

    草稿只是起点——终稿必须由人改写（Goal 验收项：正文为人工撰写）。
    """
    lines = "\n".join(f"- {t}" for t in titles)
    srcs = "、".join(n for n in dict.fromkeys(source_names) if n) or "archive"
    try:
        import json as _json
        import os
        import urllib.request

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if api_key:
            prompt = f"""You write Xiaohongshu captions for a personal taste archive account.
Style: quiet, editorial, like Hidden NY meets a private visual diary.
NOT influencer. NOT marketing. NOT "姐妹们冲".

A moodboard pack of 9 images, per-image titles:
{lines}
Sources: {srcs}

Write ONE coherent 3-4 sentence draft caption in Chinese (80-150 chars):
- Sentence 1: what ties these 9 images together (the thread)
- Sentence 2-3: one sharp cultural observation, your taste judgment
- Sentence 4: who this is for, one line, no sales
Never: 氛围, 感觉, 安静, 柔和, 光线, 午后, 美, 高级, 绝了, 氛围感, 姐妹们.
Return ONLY the caption text, no quotes, no markdown."""
            req = urllib.request.Request(
                "https://api.deepseek.com/v1/chat/completions",
                data=_json.dumps({
                    "model": "deepseek-chat",
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": prompt}],
                }).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=30)
            out = _json.loads(resp.read().decode("utf-8"))
            text = out["choices"][0]["message"]["content"].strip()
            if text:
                return text
    except Exception:
        pass
    return (
        f"这九张图有一个共同的东西：{titles[0] if titles else '比例和节奏'}。"
        f"它们不抢眼，但每一张都在说同一句话——好品味不需要大声。"
        f"适合收藏起来，在下一次想「少买一点、买对一点」的时候翻出来看。"
    )


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
    """Generate an editorial workbench QUEUE.html — 暗房联系表设计。

    - 每套方案一张「打样卡」：左侧 9 帧联系表（胶片齿孔 + Frame 编号），右侧文案栏
    - 观点草稿作为「待改写正文」突出显示（保存/复制都会带上）
    - 「策展逻辑」条：主题线索 / 来源分布 / 均分 —— 为什么是这套的图谱依据
    - 换图后服务端生成新图注并回写 body.txt，卡片同步
    """
    import html as _html

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

        img_files = sorted(post_dir.glob("image*"))
        img_abs = str(img_files[0]) if img_files else ""
        img_rel = str(img_files[0].relative_to(batch_dir)) if img_files else ""
        post_id = post_dir.name
        is_pack = len(img_files) > 1
        open_target = str(post_dir) if is_pack else img_abs

        draft = ""
        draft_path = post_dir / "opinion_draft.txt"
        if draft_path.exists():
            draft = _html.escape(draft_path.read_text(encoding="utf-8").strip())

        curation = {}
        curation_path = post_dir / "curation.json"
        if curation_path.exists():
            try:
                curation = json.loads(curation_path.read_text(encoding="utf-8"))
            except Exception:
                curation = {}

        # ── 策展逻辑条（图谱依据） ──
        shared_kws = curation.get("shared_keywords", [])
        if shared_kws:
            logic_chips = " ".join(
                f'<span class="logic-chip">{_html.escape(k["kw"])}<i class="mono">{k["count"]}</i></span>'
                for k in shared_kws[:5]
            )
        else:
            logic_chips = '<span class="logic-empty">暂无共享关键词 — 换图或等下一班 crawl</span>'
        n_sources = len(curation.get("sources", []))
        avg = curation.get("avg_score", score)

        logic_block = f"""
      <div class="curation-logic">
        <div class="logic-label">📐 为什么是这套</div>
        <div class="logic-chips">{logic_chips}</div>
        <div class="logic-meta mono">来源 {n_sources} 个 · 均分 {avg} · {_html.escape(curation.get("score_formula", "图谱 + 历史评分 + pillar 契合"))}</div>
      </div>"""

        pillar_label = PILLAR_LABELS.get(pillar, "📔")

        if is_pack:
            thumbs = []
            for idx, f in enumerate(img_files, 1):
                f_rel = str(f.relative_to(batch_dir))
                thumbs.append(
                    f'<figure class="frame">'
                    f'<img src="{f_rel}" class="grid-img" loading="lazy" data-abs="{f}" data-pos="{idx}" '
                    f'onclick="openInPreview(\'{f}\')" title="点击在 Preview 打开">'
                    f'<figcaption class="frame-num mono">{idx:02d}</figcaption>'
                    f'<span class="thumb-replace" onclick="openReplaceModal(\'{post_id}\', {idx}, this)" title="从候选池换一张（图注自动同步）">⇄</span>'
                    f'</figure>'
                )
            img_block = f'<div class="sheet">{"".join(thumbs)}</div>'
        else:
            img_block = f'''<img src="{img_rel}" class="card-img"
             data-abs="{img_abs}"
             ondblclick="openInPreview('{open_target}')"
             title="双击在 Preview 中打开 → 拖到小红书">'''

        cards.append(f"""
    <article class="card" id="{post_id}" data-pillar="{pillar}" data-pack="{post_dir}">
      <input type="checkbox" class="select-cb" data-post="{post_id}" checked>
      <header class="card-head">
        <span class="plan-no mono">PLAN {i+1:02d}</span>
        <span class="pillar-chip" data-pillar="{pillar}">{pillar_label}</span>
        <span class="plan-score mono">score {score}</span>
        <span class="card-status" id="status-{post_id}" onclick="togglePublished('{post_id}')" title="点按标记已发">⏳</span>
      </header>
      <div class="card-main">
        {img_block}
        <div class="card-copy">
          <div class="card-title" contenteditable="true" data-file="{post_dir}/title.txt" data-post="{post_id}">{title}</div>
          <div class="copy-label">观点 · 待改写为你的正文</div>
          <div class="card-draft" contenteditable="true" data-file="{post_dir}/opinion_draft.txt" data-post="{post_id}" title="观点草稿（机器起草，改写后才是你的正文）">{draft}</div>
          <div class="copy-label">图注 · 逐帧一句话</div>
          <div class="card-text" contenteditable="true" data-file="{post_dir}/body.txt" data-post="{post_id}">{body}</div>
          <div class="copy-label">标签</div>
          <div class="card-tags" contenteditable="true" data-file="{post_dir}/hashtags.txt" data-post="{post_id}">{hashtags}</div>
        </div>
      </div>
      {logic_block}
      <footer class="card-actions">
        <button onclick="openInPreview('{open_target}', this)" title="在 Preview 中打开 → 拖进小红书">🖼 打开</button>
        <button onclick="copyImage('{img_abs}', this)" title="复制首图到剪贴板 → Cmd+V 到小红书">📋 首图</button>
        <button onclick="copyAll('{post_id}')" title="复制标题+观点+图注+标签">📝 全文案</button>
        <button onclick="saveEdits('{post_id}')" title="保存编辑到文件">💾 保存</button>
        <button onclick="recordFeedback('{post_id}')" title="发布后录入互动数据" class="fb-btn">📊 反馈</button>
      </footer>
    </article>""")

    pillar_summary = " · ".join(f"{PILLAR_LABELS.get(k, k)}: {v}" for k, v in pillar_counts.items())

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>编辑台 — {date_str}</title>
<style>
  :root {{
    --bg:#201e1c; --panel:#26231f; --card:#2d2a24; --card-edge:#3b362d;
    --ink:#e9e3d8; --mut:#a29a8d; --faint:#6e675d;
    --accent:#e0933c; --accent-dim:#8a622f;
    --green:#8f9a6b; --red:#c6462e;
    --line:#3b362d;
    --mono:"SF Mono", Menlo, monospace;
    --serif:"Songti SC","Noto Serif SC",Georgia,serif;
    --sans:-apple-system,"PingFang SC",sans-serif;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg:#e7e4dd; --panel:#efede7; --card:#f8f5ef; --card-edge:#d8d2c4;
      --ink:#26231f; --mut:#6e675d; --faint:#a09a8d; --line:#d8d2c4;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); font-family:var(--sans); }}
  .mono {{ font-family:var(--mono); }}

  .wrap {{ max-width:1100px; margin:0 auto; padding:32px 20px 80px; }}

  /* ── Header ── */
  .masthead {{ display:flex; justify-content:space-between; align-items:flex-end; border-bottom:1px solid var(--line); padding-bottom:16px; margin-bottom:20px; }}
  .masthead h1 {{ font-family:var(--serif); font-size:30px; font-weight:600; margin:0; letter-spacing:.01em; }}
  .masthead .dot {{ color:var(--accent); }}
  .masthead .sub {{ font-size:13px; color:var(--mut); margin-top:4px; }}
  .masthead .stats {{ font-family:var(--mono); font-size:12px; color:var(--mut); text-align:right; }}
  .masthead nav {{ margin-top:8px; }}
  .masthead nav a {{ color:var(--mut); text-decoration:none; font-size:13px; margin-left:14px; }}
  .masthead nav a:hover {{ color:var(--ink); }}

  /* ── Toolbar ── */
  .toolbar {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:24px; }}
  .toolbar button {{
    padding:7px 14px; border:1px solid var(--line); border-radius:4px; background:var(--panel);
    color:var(--ink); cursor:pointer; font-size:13px;
  }}
  .toolbar button:hover {{ border-color:var(--accent); }}
  .toolbar .save-all {{ background:var(--accent); color:var(--accent-ink,#241a0e); border-color:var(--accent); font-weight:600; }}
  .toolbar .spacer {{ flex:1; }}
  .pillar-filter {{ display:flex; gap:6px; flex-wrap:wrap; }}
  .pillar-filter button {{
    padding:5px 12px; font-size:12px; border:1px solid var(--line); border-radius:20px;
    background:transparent; color:var(--mut); cursor:pointer;
  }}
  .pillar-filter button.on {{ background:var(--card); color:var(--ink); border-color:var(--accent); }}

  /* ── Pack card: 暗房打样纸 ── */
  .card {{
    background:var(--card); border:1px solid var(--card-edge); border-radius:8px;
    margin-bottom:28px; padding:20px 20px 16px; position:relative;
    box-shadow:0 2px 0 rgba(0,0,0,.25), 0 12px 32px rgba(0,0,0,.35);
  }}
  .card.published {{ opacity:.4; }}
  .select-cb {{ position:absolute; top:18px; left:18px; width:16px; height:16px; cursor:pointer; z-index:5; }}

  .card-head {{ display:flex; align-items:center; gap:10px; padding-left:34px; margin-bottom:14px; }}
  .plan-no {{ font-size:11px; letter-spacing:.14em; color:var(--accent); border:1px solid var(--accent-dim); border-radius:3px; padding:3px 8px; }}
  .pillar-chip {{ font-size:12px; color:var(--mut); }}
  .pillar-chip[data-pillar="lookbook"]::before {{ content:"👔 "; }}
  .pillar-chip[data-pillar="daily_archive"]::before {{ content:"📔 "; }}
  .pillar-chip[data-pillar="moving_taste"]::before {{ content:"🎬 "; }}
  .pillar-chip[data-pillar="reading_taste"]::before {{ content:"📖 "; }}
  .pillar-chip[data-pillar="product_seeds"]::before {{ content:"🔧 "; }}
  .plan-score {{ font-size:11px; color:var(--faint); margin-left:auto; }}
  .card-status {{ font-size:16px; cursor:pointer; }}

  .card-main {{ display:flex; gap:24px; align-items:flex-start; }}
  @media (max-width:820px) {{ .card-main {{ flex-direction:column; }} }}

  /* ── 联系表 9 帧（胶片齿孔签名） ── */
  .sheet {{
    flex-shrink:0; display:grid; grid-template-columns:repeat(3, 150px); gap:8px;
    background:#171512; padding:14px 12px 10px; border-radius:4px; position:relative;
  }}
  .sheet::before, .sheet::after {{
    content:""; display:block; height:9px; position:absolute; left:0; right:0;
    background-image:radial-gradient(circle, var(--card) 2px, transparent 2.6px);
    background-size:22px 9px; background-repeat:repeat-x;
  }}
  .sheet::before {{ top:3px; }}
  .sheet::after {{ bottom:3px; }}
  @media (prefers-color-scheme: light) {{ .sheet {{ background:#171512; }} }}
  .frame {{ position:relative; margin:0; width:150px; }}
  .grid-img {{
    width:100%; aspect-ratio:3/4; object-fit:cover; border-radius:2px; display:block;
    cursor:pointer; border:2px solid transparent; transition:border-color .15s;
  }}
  .grid-img:hover {{ border-color:var(--accent); }}
  .frame-num {{ position:absolute; left:4px; bottom:4px; font-size:10px; color:#d8d2c6; background:rgba(0,0,0,.55); padding:1px 5px; border-radius:2px; }}
  .thumb-replace {{
    position:absolute; top:4px; right:4px; width:22px; height:22px; border-radius:4px;
    background:rgba(0,0,0,.6); color:#fff; font-size:12px; line-height:22px; text-align:center;
    cursor:pointer; opacity:0; transition:opacity .15s;
  }}
  .frame:hover .thumb-replace {{ opacity:1; }}
  .card-img {{ width:220px; border-radius:4px; cursor:pointer; flex-shrink:0; }}

  /* ── 文案栏 ── */
  .card-copy {{ flex:1; min-width:0; }}
  .card-title {{
    font-family:var(--serif); font-size:20px; font-weight:600; line-height:1.4;
    padding:2px 4px; border-radius:3px; outline:none; border:1px solid transparent;
  }}
  .card-title:focus {{ border-color:var(--accent); background:rgba(224,147,60,.06); }}
  .copy-label {{ font-size:10px; letter-spacing:.12em; color:var(--faint); margin:12px 4px 4px; }}
  .card-draft {{
    font-family:var(--serif); font-size:14px; line-height:1.8; color:var(--ink);
    border-left:2px solid var(--accent); padding:6px 10px; border-radius:2px;
    background:rgba(224,147,60,.05); outline:none; white-space:pre-line;
  }}
  .card-draft:focus {{ border-color:var(--accent); }}
  .card-text {{
    font-size:13px; color:var(--mut); line-height:1.7; white-space:pre-line;
    padding:2px 4px; border-radius:3px; outline:none; border:1px solid transparent; min-height:24px;
  }}
  .card-text:focus {{ border-color:var(--accent); color:var(--ink); }}
  .card-tags {{
    font-size:12px; color:var(--green); word-break:break-all;
    padding:2px 4px; border-radius:3px; outline:none; border:1px solid transparent;
  }}
  .card-tags:focus {{ border-color:var(--accent); }}

  /* ── 策展逻辑条 ── */
  .curation-logic {{ margin-top:16px; border-top:1px dashed var(--line); padding-top:10px; display:flex; flex-wrap:wrap; gap:10px; align-items:center; }}
  .logic-label {{ font-size:11px; letter-spacing:.1em; color:var(--accent); }}
  .logic-chips {{ display:flex; gap:6px; flex-wrap:wrap; }}
  .logic-chip {{
    font-size:12px; color:var(--ink); background:var(--panel); border:1px solid var(--line);
    border-radius:3px; padding:2px 8px;
  }}
  .logic-chip i {{ font-style:normal; color:var(--accent); margin-left:4px; }}
  .logic-empty {{ font-size:12px; color:var(--faint); }}
  .logic-meta {{ font-size:10px; color:var(--faint); margin-left:auto; }}

  .card-actions {{ display:flex; gap:8px; margin-top:12px; }}
  .card-actions button {{
    padding:6px 12px; font-size:12px; border:1px solid var(--line); border-radius:4px;
    background:var(--panel); color:var(--ink); cursor:pointer;
  }}
  .card-actions button:hover {{ border-color:var(--accent); }}
  .card-actions .fb-btn {{ color:var(--red); }}

  /* ── Modals ── */
  .modal-overlay {{
    display:none; position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:1000;
    justify-content:center; align-items:center;
  }}
  .modal-overlay.show {{ display:flex; }}
  .modal {{
    background:var(--card); border:1px solid var(--card-edge); border-radius:10px;
    padding:24px; max-width:640px; width:92%; box-shadow:0 18px 60px rgba(0,0,0,.5);
  }}
  .modal h2 {{ font-family:var(--serif); font-size:18px; margin:0 0 14px; }}
  .modal label {{ display:block; font-size:13px; color:var(--mut); margin-bottom:4px; }}
  .modal input {{
    width:100%; padding:8px 12px; border:1px solid var(--line); border-radius:6px;
    font-size:14px; margin-bottom:12px; background:var(--panel); color:var(--ink);
  }}
  .modal .row {{ display:flex; gap:8px; }}
  .modal .row input {{ flex:1; }}
  .modal button {{ padding:8px 16px; border:none; border-radius:6px; cursor:pointer; font-size:14px; }}
  .modal .btn-save {{ background:var(--red); color:#fff; }}
  .modal .btn-cancel {{ background:var(--panel); color:var(--mut); border:1px solid var(--line); }}
  .rm-grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:6px; max-height:440px; overflow-y:auto; }}
  .rm-grid img {{ width:100%; aspect-ratio:3/4; object-fit:cover; border-radius:4px; border:2px solid transparent; cursor:pointer; }}
  .rm-grid img:hover {{ border-color:var(--accent); }}
  .rm-grid .rm-cap {{ font-size:10px; color:var(--mut); text-align:center; margin-top:2px; }}

  .toast {{
    position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
    background:var(--ink); color:var(--bg); padding:10px 24px; border-radius:6px;
    font-size:14px; z-index:1999; animation:fadeOut 2.2s forwards; pointer-events:none;
  }}
  @keyframes fadeOut {{ 0%,60% {{ opacity:1; }} 100% {{ opacity:0; }} }}

  .footer {{ text-align:center; color:var(--faint); font-size:12px; margin-top:36px; }}
</style>
</head>
<body>
<div class="wrap">

<div class="masthead">
  <div>
    <h1>moodboard<span class="dot">.</span></h1>
    <div class="sub">编辑台 · {date_str} · 机器出方案，人做判断</div>
  </div>
  <div class="stats">
    {len(post_dirs)} 套方案 · 每套 9 帧<br>
    <nav>
      <a href="/">🏠 工作台</a>
      <a href="/publish-log">📓 发布登记</a>
      <a href="/sources">📡 信息源</a>
      <a href="#" onclick="showWeeklyReport()">📊 周报</a>
      <a href="http://127.0.0.1:8787">⚙️ 系统台</a>
    </nav>
  </div>
</div>

<div class="toolbar">
  <button onclick="selectAll()">☑ 全选</button>
  <button onclick="deselectAll()">☐ 取消全选</button>
  <button onclick="openSelected()">📁 打开选中</button>
  <button class="save-all" onclick="saveAllEdits()">💾 全部保存</button>
  <button onclick="markAllDone()">✅ 全部标为已发</button>
  <span class="spacer"></span>
  <div class="pillar-filter">
    <button class="on" data-p="all" onclick="filterByPillar('all',this)">全部</button>
    <button data-p="lookbook" onclick="filterByPillar('lookbook',this)">👔 Lookbook</button>
    <button data-p="daily_archive" onclick="filterByPillar('daily_archive',this)">📔 日常档案</button>
    <button data-p="moving_taste" onclick="filterByPillar('moving_taste',this)">🎬 影像</button>
    <button data-p="reading_taste" onclick="filterByPillar('reading_taste',this)">📖 阅读</button>
    <button data-p="product_seeds" onclick="filterByPillar('product_seeds',this)">🔧 产品</button>
  </div>
  <span class="mono" style="font-size:12px;color:var(--mut)" id="counter">{len(post_dirs)} 待发</span>
</div>

{''.join(cards)}

<!-- Feedback Modal -->
<div class="modal-overlay" id="feedback-modal">
  <div class="modal">
    <h2>📊 录入互动数据</h2>
    <div style="font-size:12px;color:var(--mut);margin-bottom:12px">从小红书创作者后台查看笔记数据</div>
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

<!-- Replace Image Modal -->
<div class="modal-overlay" id="replace-modal">
  <div class="modal">
    <h2>⇄ 换图 — <span id="rm-pos" class="mono"></span></h2>
    <div style="font-size:12px;color:var(--mut);margin-bottom:10px">候选池来自今日爬取（按评分排序）。点击一张即替换，图注自动同步。</div>
    <div class="rm-grid" id="rm-grid">加载中...</div>
    <div style="margin-top:16px;text-align:right">
      <button class="btn-cancel" onclick="closeReplaceModal()">取消</button>
    </div>
  </div>
</div>

<!-- Weekly Report Modal -->
<div class="modal-overlay" id="report-modal">
  <div class="modal" style="max-width:520px">
    <h2>📊 发布效果周报</h2>
    <div id="report-content" style="font-size:13px;line-height:1.8;max-height:400px;overflow-y:auto;color:var(--mut)">加载中...</div>
    <div style="margin-top:16px;text-align:right">
      <button class="btn-cancel" onclick="closeReport()">关闭</button>
    </div>
  </div>
</div>

<div class="footer">
  点击缩略图 → Preview 打开 · 悬停帧 ⇄ 换图（图注自动同步）· 文字直接编辑 · 💾 保存落盘 · 发完 📊 反馈
</div>

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
    if (btn) {{ setTimeout(() => {{ btn.innerText = '📋 首图'; btn.disabled = false; }}, 1000); }}
}}
function copyAll(postId) {{
    const card = document.getElementById(postId);
    const title = card.querySelector('.card-title').innerText;
    const body = card.querySelector('.card-text').innerText;
    const tags = card.querySelector('.card-tags').innerText;
    const draftEl = card.querySelector('.card-draft');
    const draft = draftEl ? draftEl.innerText.replace(/^💭\\s*/, '').trim() : '';
    const parts = [title, draft, body, tags].filter(p => p);
    copyToClipboard(parts.join('\\n\\n'));
}}

// ── Inline editing: save to file ──
async function saveEdits(postId) {{
    const card = document.getElementById(postId);
    const title = card.querySelector('.card-title');
    const body = card.querySelector('.card-text');
    const tags = card.querySelector('.card-tags');
    const draft = card.querySelector('.card-draft');

    const titleFile = title.dataset.file;
    const bodyFile = body.dataset.file;
    const tagsFile = tags.dataset.file;
    const draftFile = draft ? draft.dataset.file : null;
    const draftText = draft ? draft.innerText.replace(/^💭\\s*/, '') : '';

    let saved = 0;
    try {{
        await fetch('/save-file?path=' + encodeURIComponent(titleFile) + '&content=' + encodeURIComponent(title.innerText));
        saved++;
        await fetch('/save-file?path=' + encodeURIComponent(bodyFile) + '&content=' + encodeURIComponent(body.innerText));
        saved++;
        await fetch('/save-file?path=' + encodeURIComponent(tagsFile) + '&content=' + encodeURIComponent(tags.innerText));
        saved++;
        if (draftFile) {{
            await fetch('/save-file?path=' + encodeURIComponent(draftFile) + '&content=' + encodeURIComponent(draftText));
            saved++;
        }}
    }} catch(e) {{ /* silent */ }}

    localStorage.setItem(postId + '-title', title.innerText);
    localStorage.setItem(postId + '-body', body.innerText);
    localStorage.setItem(postId + '-tags', tags.innerText);
    if (draft) localStorage.setItem(postId + '-draft', draftText);

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
        document.getElementById('report-content').innerHTML = '<p style="color:#c6462e">API 未连接。请先启动: python taste_graph_ai/server.py</p>';
    }}
}}
function closeReport() {{
    document.getElementById('report-modal').classList.remove('show');
}}

// ── Pillar filter (chips) ──
function filterByPillar(pillar, btn) {{
    document.querySelectorAll('.pillar-filter button').forEach(b => b.classList.remove('on'));
    if (btn) btn.classList.add('on');
    document.querySelectorAll('.card').forEach(card => {{
        if (pillar === 'all' || card.dataset.pillar === pillar) {{
            card.style.display = 'block';
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
        const img = document.querySelector('#' + postId + ' .card-img, #' + postId + ' .grid-img');
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
    document.getElementById('counter').innerText = (total - published) + ' 待发 · ' + published + ' 已发';
}}

// ── Restore saved edits from localStorage ──
document.querySelectorAll('.card').forEach(card => {{
    const pid = card.id;
    ['title', 'body', 'tags', 'draft'].forEach(field => {{
        const saved = localStorage.getItem(pid + '-' + field);
        if (saved) {{
            const el = card.querySelector(
                field === 'title' ? '.card-title' : field === 'body' ? '.card-text' :
                field === 'tags' ? '.card-tags' : '.card-draft');
            if (!el) return;
            const current = field === 'draft' ? el.innerText.replace(/^💭\\s*/, '') : el.innerText;
            if (current !== saved) el.innerText = saved;
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

// ── Replace image (换图，图注同步) ──
let replaceTarget = null;
function openReplaceModal(postId, pos, btn) {{
    replaceTarget = {{ postId, pos }};
    document.getElementById('rm-pos').innerText = postId + ' · FRAME ' + String(pos).padStart(2,'0');
    document.getElementById('replace-modal').classList.add('show');
    loadCandidates();
}}
function closeReplaceModal() {{
    document.getElementById('replace-modal').classList.remove('show');
    replaceTarget = null;
}}
function _js(s) {{
    return JSON.stringify(String(s ?? ''));
}}
async function loadCandidates() {{
    const grid = document.getElementById('rm-grid');
    grid.innerHTML = '加载中...';
    try {{
        const resp = await fetch('/queue-candidates');
        const data = await resp.json();
        const imgs = (data.images || []);
        if (imgs.length === 0) {{
            grid.innerHTML = '<p>候选池为空 — 等下一班 crawl 后再试。</p>';
            return;
        }}
        grid.innerHTML = imgs.map(im => {{
            const kw = (im.keywords && im.keywords.length) ? im.keywords.slice(0,4).join(' ') : '';
            return '<div onclick="confirmReplace(' + _js(im.local_path) + ',' + _js(kw) + ',' + _js(im.source_name) + ')">' +
                '<img src="' + im.src.replace(/&/g,'&amp;').replace(/"/g,'&quot;') + '" loading="lazy" title="' +
                im.source_name.replace(/[&<>\"]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}})[c]) + '">' +
                '<div class="rm-cap mono">' + im.final_score + '</div></div>';
        }}).join('');
    }} catch(e) {{
        grid.innerHTML = '<p style="color:#c6462e">候选池加载失败 — 请确认 8787 服务在跑。</p>';
    }}
}}
async function confirmReplace(src, kw, srcname) {{
    if (!replaceTarget) return;
    const {{ postId, pos }} = replaceTarget;
    const card = document.getElementById(postId);
    const pack = card.dataset.pack;
    try {{
        const resp = await fetch('/replace-image?pack=' + encodeURIComponent(pack) +
            '&pos=' + pos + '&src=' + encodeURIComponent(src) +
            '&kw=' + encodeURIComponent(kw || '') + '&srcname=' + encodeURIComponent(srcname || ''));
        const data = await resp.json();
        if (data.ok) {{
            const thumb = card.querySelector('.grid-img[data-pos="' + pos + '"]');
            if (thumb) thumb.src = '/' + data.rel + '?t=' + Date.now();
            if (data.caption) {{
                const bodyEl = card.querySelector('.card-text');
                const lines = bodyEl.innerText.split('\\n');
                const pat = new RegExp('^' + String(pos).padStart(2,'0') + ' ');
                let found = false;
                for (let li = 0; li < lines.length; li++) {{
                    if (pat.test(lines[li])) {{ lines[li] = String(pos).padStart(2,'0') + ' ' + data.caption; found = true; break; }}
                }}
                if (!found) lines.push(String(pos).padStart(2,'0') + ' ' + data.caption);
                bodyEl.innerText = lines.join('\\n');
                saveEdits(postId);
            }}
            toast('✅ FRAME ' + String(pos).padStart(2,'0') + ' 已换，图注已同步');
            closeReplaceModal();
        }} else {{
            toast('❌ ' + (data.error || '替换失败'));
        }}
    }} catch(e) {{
        toast('❌ 替换失败 — 请确认工作台服务在跑');
    }}
}}

// ── Toast ──
function toast(msg) {{
    const t = document.createElement('div');
    t.className = 'toast';
    t.innerText = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2400);
}}
</script>
</body>
</html>"""

    (batch_dir / "QUEUE.html").write_text(html, encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(description="生成小红书发布包")
    parser.add_argument("--date", default=date_type.today().isoformat(), help="日期 (YYYY-MM-DD)")
    parser.add_argument("--count", type=int, default=5, help="生成几篇/几包")
    parser.add_argument("--pack-size", type=int, default=1, help="每包图片数（9 = 一包 9 图候选）")
    parser.add_argument("--skip-queue", action="store_true", help="不生成 QUEUE.html（自动模式）")
    args = parser.parse_args()

    asyncio.run(generate(date_str=args.date, count=args.count, skip_queue=args.skip_queue, pack_size=args.pack_size))


if __name__ == "__main__":
    main()
