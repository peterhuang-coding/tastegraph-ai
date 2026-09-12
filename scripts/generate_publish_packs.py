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
import urllib.parse
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

# QUEUE.html 模板版本戳（auto_deploy 用它判断是否需要重生成今日包）
# 2026-09-08: 安全收口 — 移除 open-file/copy-image/file:// 远程动作，
# 改页内预览 + 单张下载 + 九图 ZIP；导航去硬编码；草稿「最后保存于」。
TEMPLATE_VERSION = "2026-09-13.editorial.1"

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


def _load_published_image_ids() -> set:
    """Use the same publication exclusions as the API candidate picker."""
    from taste_graph_ai.services.images import _load_published_image_ids as load_ids
    return load_ids()


async def generate(date_str: str = None, count: int = 5, skip_queue: bool = False, pack_size: int = 1) -> Path:
    """Export traceable research candidates; an editorial review is required before use."""
    from datetime import datetime
    import uuid
    from taste_graph_ai.config import DB_FILE
    from taste_graph_ai.services.editorial import load_annotations, choose_candidate_groups, score_candidate
    from taste_graph_ai.services.publication_records import resolve_publication_pack

    date_str = date_str or date_type.today().isoformat()
    batch_dir = POSTS_DIR / date_str
    batch_dir.mkdir(parents=True, exist_ok=True)
    ensure_dirs()
    await init_db()
    graph = get_container().taste_graph
    db = await get_db()
    try:
        image_repo = ImageRepository(db)
        liked_ids = await FeedbackRepository(db).get_liked_image_ids()
        annotations = load_annotations(DB_FILE)
        published_ids = _load_published_image_ids()
        from taste_graph_ai.services.images import _image_content_hash
        published_urls, published_hashes = set(), set()
        for image_id in published_ids:
            original = await image_repo.get_by_id(image_id)
            if original is None:
                continue
            if original.url:
                published_urls.add(original.url)
            original.local_path = _resolve_local_path(original)
            digest = _image_content_hash(original)
            if digest is not None:
                published_hashes.add(digest)
        # Query both states without the old score-first 100/3000 truncation.
        rows = await (await db.execute("SELECT * FROM images WHERE status IN ('pending','selected') ORDER BY id")).fetchall()
        candidates = [image_repo._row_to_image(row) for row in rows]
        valid = []
        for img in candidates:
            if img.id in published_ids or img.url in published_urls:
                continue
            local = _resolve_local_path(img)
            if local and Path(local).is_file():
                img.local_path = local
                if published_hashes:
                    digest = _image_content_hash(img)
                    if digest is None or digest in published_hashes:
                        continue
                valid.append(img)
        scored = []
        for img in valid:
            parts = score_candidate(img, graph, annotations.get(img.id), liked_ids)
            scored.append({"img":img, **parts, "kws":list(img.keywords)})
        groups = choose_candidate_groups(scored,count,pack_size,annotations,published_ids)
        names = _build_source_lookup(await SourceRepository(db).list_all())
        run_key = datetime.now().strftime("%H%M%S") + "-" + uuid.uuid4().hex[:4]
        post_dirs = []
        for gi,group in enumerate(groups,1):
            folder = batch_dir / f"pack-editorial-{run_key}-{gi:03d}"
            folder.mkdir()
            pack_path = str(folder.relative_to(BASE_DIR))
            pack_id = "fs_" + hashlib.sha256(pack_path.encode()).hexdigest()[:20]
            notes=[]
            for position,item in enumerate(group,1):
                img=item["img"]
                _prepare_image(Path(img.local_path),folder/f"image-{position:02d}{Path(img.local_path).suffix}")
                provenance = [dict(r) for r in await (await db.execute("SELECT * FROM image_provenance WHERE image_id=? ORDER BY observed_at DESC LIMIT 5",(img.id,))).fetchall()]
                notes.append({"image_id":img.id,"position":position-1,"source_page":img.page_url,
                    "source_name":names(img.source_id or "",img.page_url),
                    "original_image_url":img.url,"original_sha256":hashlib.sha256(Path(img.local_path).read_bytes()).hexdigest(),
                    "annotation":annotations.get(img.id,{}),"provenance":provenance,
                    "role":"","visual_evidence":"","selection_reason":"",
                    "score_parts":{k:v for k,v in item.items() if k not in {"img","kws"}}})
            suggested=annotations.get(group[0]["img"].id,{}).get("topic_hint","")
            title=suggested or "待定选题 · " + (notes[0]["source_name"] or "素材研究")
            body="\n\n".join(f"{i+1:02d} 来源：{note['source_page']}\n入选理由：待补充" for i,note in enumerate(notes))
            curation={"pack_id":pack_id,"theme":title,"pillar":"editorial_research",
                "workflow_status":"needs_editorial_review","thesis":"","sequence_reason":"",
                "image_ids":[item["img"].id for item in group],"image_count":len(group),"images":notes,
                "pool_size":len(valid),"avg_score":sum(item["total"] for item in group)/len(group),
                "sources":list({note["source_name"]:sum(n["source_name"]==note["source_name"] for n in notes) for note in notes}.items()),
                "score_formula":"图谱50% + 出处已核验20% + 具体内容页10% + 运营优先10% + 明确单图喜欢10%",
                "grouping":"按运营命题或具体来源页归组；关系与顺序仍待审核"}
            (folder/"curation.json").write_text(json.dumps(curation,ensure_ascii=False,indent=2),encoding="utf-8")
            for filename,text in [("title.txt",title),("body.txt",body),("hashtags.txt",""),("opinion_draft.txt","请先确认命题、每图的画面证据与入选理由，再撰写正文。"),("score.txt",str(curation["avg_score"])),("pillar.txt","editorial_research")]:
                (folder/filename).write_text(text,encoding="utf-8")
            (folder/"publish-checklist.md").write_text("# 候选研究图集\n\n- [ ] 核实出处和图注\n- [ ] 明确组图命题\n- [ ] 填写每图角色、画面证据、入选理由与顺序说明\n- [ ] 在运营打标页完成审核\n- [ ] 审阅标题与正文后再发布\n",encoding="utf-8")
            await resolve_publication_pack(db,pack_id,pack_path=pack_path,base_dir=BASE_DIR)
            post_dirs.append(folder)
            print(f"Candidate {folder.name}: {len(group)} images; needs editorial review")
        await db.commit()
        if not skip_queue:
            _generate_queue_html(batch_dir,post_dirs,date_str)
        print(f"Saved {len(post_dirs)} research candidates; editorial review: /editorial.html")
        return batch_dir
    finally:
        await db.close()


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
    """Keep the complete original composition and exact bytes."""
    shutil.copy2(src_path, dest_path)


def _slug_words(source_id: str) -> str:
    """'src_off_white' → 'off white'，用于 legacy slug 与 DB 名称的模糊匹配。"""
    return source_id.removeprefix("src_").replace("_", " ").strip()


def _build_source_lookup(all_sources):
    """Prefer a matching source URL scope; never label a different collection by ID."""
    def normalized(value):
        parsed=urllib.parse.urlsplit(value or "")
        return parsed.hostname.lower().removeprefix("www.") if parsed.hostname else "", parsed.path.rstrip("/")
    def lookup(sid, page_url=""):
        domain,path=normalized(page_url)
        matches=[]
        for source in all_sources:
            source_domain,source_path=normalized(source.url)
            if domain and domain==source_domain and (not source_path or path==source_path or path.startswith(source_path+"/")):
                matches.append((len(source_path),source.name))
        if matches:
            return max(matches)[1]
        if domain:
            return domain
        return next((source.name for source in all_sources if source.id==sid), "")
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


def _generate_editorial_queue_html(batch_dir, post_dirs, date_str):
    """Readonly candidate overview; all decisions go through canonical editorial IDs."""
    import html
    import os
    dashboard = os.environ.get("TASTEGRAPH_DASHBOARD_URL", "http://127.0.0.1:8787").rstrip("/")
    cards=[]
    for folder in post_dirs:
        metadata_path=folder/"curation.json"
        meta=json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        title=(folder/"title.txt").read_text() if (folder/"title.txt").exists() else "待定选题"
        images="".join('<img src="'+html.escape(str(p.relative_to(batch_dir)),quote=True)+'" alt="原始素材">' for p in sorted(folder.glob("image*")) if p.suffix.lower() in {".jpg",".jpeg",".png",".webp"})
        href=dashboard+"/editorial.html?pack="+urllib.parse.quote(meta.get("pack_id",""))
        action='<a href="'+html.escape(href,quote=True)+'">进入图集审核 →</a>' if meta.get("pack_id") else "<p>旧素材目录 · 尚未登记图集身份</p>"
        cards.append('<article><h2>'+html.escape(title)+'</h2><p>候选研究 · 命题、逐图理由与顺序待审核</p><div class="images">'+images+'</div>'+action+'</article>')
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TAPE · 候选研究</title><style>body{font:15px/1.6 -apple-system, sans-serif;background:#eef0f3;color:#242d35;margin:30px}main{max-width:1250px;margin:auto}article{background:white;padding:24px;margin:24px 0;border-radius:8px}h1{font-weight:600}h2{font-size:18px}p{color:#667584}.images{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}.images img{height:190px;max-width:100%;object-fit:contain;background:#f8f9fa}a{color:#244f73}</style><main><h1>TAPE · 候选研究</h1><p>'+html.escape(date_str)+' · 保留原图；完成策展审核后再准备发布。</p>'+''.join(cards)+'</main></html>'
    page = f"<!-- queue-template-v: {TEMPLATE_VERSION} -->\n" + page
    (batch_dir/"QUEUE.html").write_text(page,encoding="utf-8")


def _generate_queue_html(batch_dir: Path, post_dirs: list[Path], date_str: str):
    """Generate the editorial workbench QUEUE.html — 极简工作室设计（老板选定方向 B）。

    - 浅灰底 + 白卡片 + 墨绿点缀，Apple/Linear 式克制
    - 每套方案一张卡：左 9 帧联系表（圆角帧 + 编号），右文案栏
    - 观点草稿 = 绿色底提示框「待改写」；策展逻辑条在卡底
    - 换图自动同步图注（服务端生成并回写 body.txt）
    """
    if any((p / "curation.json").exists() and json.loads((p / "curation.json").read_text()).get("workflow_status") for p in post_dirs):
        return _generate_editorial_queue_html(batch_dir, post_dirs, date_str)

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
        img_rel = str(img_files[0].relative_to(batch_dir)) if img_files else ""
        post_id = post_dir.name
        is_pack = len(img_files) > 1
        # 九图 ZIP 下载走工作台 /pack-zip（浏览器内能力，替代 Finder/剪贴板远程动作）
        zip_href = f"/pack-zip?pack={urllib.parse.quote(str(post_dir))}"
        zip_name = f"{date_str}-{post_id}.zip"

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

        shared_kws = curation.get("shared_keywords", [])
        if shared_kws:
            logic_chips = "".join(
                f'<span class="chip">{_html.escape(k["kw"])}<i>{k["count"]}</i></span>'
                for k in shared_kws[:5]
            )
        else:
            logic_chips = '<span class="chip" style="color:var(--faint)">请填写命题、逐图证据与顺序说明</span>'
        n_sources = len(curation.get("sources", []))
        avg = curation.get("avg_score", score)

        logic_block = f"""
      <div class="logic">
        <span class="lbl">候选线索 · 待策展审核</span>
        {logic_chips}
        <span class="meta">候选池 {curation.get("pool_size", "?")} 张 · 来源 {n_sources} 个 · 均分 {avg}</span>
      </div>"""

        pillar_label = PILLAR_LABELS.get(pillar, "📔")
        if i == 0:
            pill_text = "综合"
        else:
            pill_text = pillar_label.split(" ")[-1] if pillar_label else "方案"

        if is_pack:
            thumbs = []
            for idx, f in enumerate(img_files, 1):
                f_rel = str(f.relative_to(batch_dir))
                thumbs.append(
                    f'<div class="frame">'
                    f'<img src="{f_rel}" class="grid-img" loading="lazy" data-pos="{idx}" '
                    f'onclick="showLightbox(this.src)" title="点击页内预览（⇄ 换图）">'
                    f'<span class="num">{idx:02d}</span>'
                    f'<span class="swap" onclick="openReplaceModal(\'{post_id}\', {idx}, this)" title="换一张（图注自动同步）">⇄</span>'
                    f'</div>'
                )
            img_block = f'<div class="sheet">{"".join(thumbs)}</div>'
        else:
            img_block = f'''<img src="{img_rel}" class="card-img"
             onclick="showLightbox(this.src)"
             title="点击页内预览 → 用「下载」按钮存图">'''

        cards.append(f"""
    <article class="plan" id="{post_id}" data-pillar="{pillar}" data-pack="{post_dir}">
      <input type="checkbox" class="select-cb" data-post="{post_id}" checked>
      <div class="plan-head">
        <span class="pill">{pill_text}</span>
        <span class="pill-no">PLAN {i+1:02d} · {pillar_label}</span>
        <span class="score">score {score}</span>
        <span class="status" id="status-{post_id}" onclick="togglePublished('{post_id}')" title="点按标记已发">⏳</span>
      </div>
      <div class="plan-main">
        {img_block}
        <div class="copy">
          <div class="title" contenteditable="true" data-file="{post_dir}/title.txt" data-post="{post_id}">{title}</div>
          <div class="label">观点 · 待改写为你的正文</div>
          <div class="draft" contenteditable="true" data-file="{post_dir}/opinion_draft.txt" data-post="{post_id}" title="机器起草，改写后才是你的正文">{draft}</div>
          <div class="label">图注 · 逐帧一句话</div>
          <div class="caps" contenteditable="true" data-file="{post_dir}/body.txt" data-post="{post_id}">{body}</div>
          <div class="label">标签</div>
          <div class="tags" contenteditable="true" data-file="{post_dir}/hashtags.txt" data-post="{post_id}">{hashtags}</div>
        </div>
      </div>
      {logic_block}
      <div class="actions">
        <a class="btn" href="{zip_href}" download="{zip_name}" data-zip title="打包本包 9 帧为 ZIP（浏览器下载，解压后全选拖入小红书）">📦 下载九图</a>
        <button class="btn" onclick="copyAll('{post_id}')" title="复制标题+观点+图注+标签到剪贴板">📝 复制文案</button>
        <button class="btn" onclick="saveEdits('{post_id}')" title="保存编辑到文件（失焦也会自动保存）">💾 保存</button>
        <button class="btn fb" onclick="recordFeedback('{post_id}')" title="发布后录入互动数据">📊 反馈</button>
        <span class="saved-at" id="saved-{post_id}"></span>
      </div>
    </article>""")

    pillar_summary = " · ".join(f"{PILLAR_LABELS.get(k, k)}: {v}" for k, v in pillar_counts.items())

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<!-- queue-template-v: {TEMPLATE_VERSION} -->
<meta charset="UTF-8">
<title>编辑台 — {date_str}</title>
<style>
  :root {{
    --bg:#f5f5f7; --card:#ffffff; --ink:#1d1d1f; --mut:#6e6e73; --faint:#aeaeb2;
    --line:#e5e5ea; --green:#1a6b4f; --green-soft:#eef5f1; --red:#c0392b;
    --mono:"SF Mono",Menlo,monospace;
    --sans:-apple-system,"PingFang SC",sans-serif;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--ink); font-family:var(--sans); -webkit-font-smoothing:antialiased; }}
  .bar {{ height:3px; background:var(--green); }}

  .wrap {{ max-width:1000px; margin:0 auto; padding:0 20px 80px; }}

  .top {{ display:flex; justify-content:space-between; align-items:center; padding:26px 0 18px; }}
  .top .brand {{ font-size:24px; font-weight:700; letter-spacing:-.02em; }}
  .top .brand .dot {{ color:var(--green); }}
  .top .meta {{ font-size:13px; color:var(--mut); }}
  .top nav a {{ font-size:13px; color:var(--mut); text-decoration:none; margin-left:18px; }}
  .top nav a:hover {{ color:var(--ink); }}

  .intro {{ padding:6px 0 22px; }}
  .intro h1 {{ font-size:28px; font-weight:700; letter-spacing:-.02em; margin-bottom:6px; }}
  .intro p {{ font-size:14px; color:var(--mut); }}

  .steps {{ display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin-bottom:16px; }}
  @media (max-width:820px) {{ .steps {{ grid-template-columns:repeat(2,1fr); }} }}
  .step {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px; }}
  .step .n {{ font-size:11px; font-weight:700; color:var(--green); margin-bottom:5px; }}
  .step b {{ display:block; font-size:13px; margin-bottom:2px; }}
  .step span {{ font-size:12px; color:var(--mut); line-height:1.5; }}

  .toolbar {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:22px; }}
  .btn {{ font-size:13px; font-weight:500; padding:7px 14px; border-radius:10px; border:1px solid var(--line); background:var(--card); color:var(--ink); cursor:pointer; }}
  .btn:hover {{ border-color:var(--green); }}
  .btn.primary {{ background:var(--green); border-color:var(--green); color:#fff; }}
  .filters {{ display:flex; gap:6px; margin-left:auto; flex-wrap:wrap; }}
  .filter {{ font-size:12px; padding:6px 12px; border-radius:20px; border:1px solid var(--line); background:var(--card); color:var(--mut); cursor:pointer; }}
  .filter.on {{ background:var(--green-soft); border-color:var(--green); color:var(--green); font-weight:600; }}
  #counter {{ font-size:12px; color:var(--faint); margin-left:10px; }}

  /* ── 方案卡 ── */
  .plan {{ position:relative; background:var(--card); border:1px solid var(--line); border-radius:16px; padding:20px; margin-bottom:20px; }}
  .plan.published {{ opacity:.4; }}
  .select-cb {{ position:absolute; top:22px; left:20px; width:16px; height:16px; cursor:pointer; z-index:5; }}
  .plan-head {{ display:flex; align-items:center; gap:10px; padding-left:26px; margin-bottom:16px; }}
  .pill {{ background:var(--green-soft); color:var(--green); font-size:12px; font-weight:600; padding:4px 12px; border-radius:20px; }}
  .pill-no {{ font-size:12px; color:var(--mut); }}
  .score {{ font-size:12px; color:var(--faint); margin-left:auto; }}
  .status {{ font-size:15px; cursor:pointer; }}

  .plan-main {{ display:grid; grid-template-columns:1fr 1.3fr; gap:24px; }}
  @media (max-width:820px) {{ .plan-main {{ grid-template-columns:1fr; }} }}

  .sheet {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }}
  .frame {{ position:relative; aspect-ratio:3/4; border-radius:10px; overflow:hidden; background:#eee; }}
  .grid-img {{ width:100%; height:100%; object-fit:cover; display:block; cursor:pointer; transition:transform .15s; }}
  .grid-img:hover {{ transform:scale(1.03); }}
  .frame .num {{ position:absolute; left:6px; bottom:6px; font-size:10px; font-weight:600; color:#fff; background:rgba(0,0,0,.45); padding:2px 6px; border-radius:6px; }}
  .frame .swap {{
    position:absolute; top:6px; right:6px; width:24px; height:24px; border-radius:8px;
    background:rgba(0,0,0,.5); color:#fff; font-size:13px; line-height:24px; text-align:center;
    cursor:pointer; opacity:0; transition:opacity .15s;
  }}
  .frame:hover .swap {{ opacity:1; }}
  .card-img {{ width:100%; border-radius:10px; cursor:pointer; }}

  .title {{ font-size:22px; font-weight:700; letter-spacing:-.01em; margin-bottom:2px; padding:2px 4px; border-radius:8px; outline:none; border:1px solid transparent; }}
  .title:focus {{ border-color:var(--green); background:var(--green-soft); }}
  .label {{ font-size:11px; font-weight:600; color:var(--mut); text-transform:uppercase; letter-spacing:.06em; margin:14px 4px 6px; }}
  .draft {{ font-size:14px; line-height:1.8; background:var(--green-soft); border-radius:10px; padding:12px 14px; outline:none; border:1px solid transparent; white-space:pre-line; }}
  .draft:focus {{ border-color:var(--green); }}
  .caps {{ font-size:13px; line-height:1.9; color:var(--mut); white-space:pre-line; padding:2px 4px; border-radius:8px; outline:none; border:1px solid transparent; }}
  .caps:focus {{ border-color:var(--green); color:var(--ink); }}
  .tags {{ font-size:12px; color:var(--green); padding:2px 4px; border-radius:8px; outline:none; border:1px solid transparent; }}
  .tags:focus {{ border-color:var(--green); }}

  .logic {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; border-top:1px solid var(--line); margin-top:16px; padding-top:12px; }}
  .logic .lbl {{ font-size:11px; font-weight:600; color:var(--green); }}
  .chip {{ font-size:12px; background:var(--bg); border:1px solid var(--line); border-radius:8px; padding:3px 10px; }}
  .chip i {{ font-style:normal; color:var(--green); margin-left:4px; font-weight:600; }}
  .logic .meta {{ font-size:11px; color:var(--faint); margin-left:auto; }}

  .actions {{ display:flex; gap:8px; margin-top:14px; align-items:center; flex-wrap:wrap; }}
  .actions .btn {{ text-decoration:none; display:inline-block; line-height:1.2; }}
  .actions .fb {{ color:var(--red); }}
  .saved-at {{ font-size:11px; color:var(--faint); margin-left:auto; }}

  /* ── 页内预览 lightbox（替代 Preview/Finder 远程打开） ── */
  .lightbox {{
    display:none; position:fixed; inset:0; background:rgba(0,0,0,.82); z-index:2000;
    justify-content:center; align-items:center; cursor:zoom-out;
  }}
  .lightbox.show {{ display:flex; }}
  .lightbox img {{ max-width:92vw; max-height:82vh; border-radius:10px; box-shadow:0 20px 60px rgba(0,0,0,.5); }}
  .lightbox .lb-bar {{ position:absolute; top:18px; right:22px; display:flex; gap:10px; }}
  .lightbox .lb-bar a, .lightbox .lb-bar button {{
    background:rgba(255,255,255,.14); color:#fff; border:1px solid rgba(255,255,255,.35);
    border-radius:10px; padding:8px 16px; font-size:13px; cursor:pointer; text-decoration:none;
  }}
  .lightbox .lb-bar a:hover, .lightbox .lb-bar button:hover {{ background:rgba(255,255,255,.28); }}

  /* ── Modals ── */
  .modal-overlay {{
    display:none; position:fixed; inset:0; background:rgba(0,0,0,.4); z-index:1000;
    justify-content:center; align-items:center;
  }}
  .modal-overlay.show {{ display:flex; }}
  .modal {{
    background:var(--card); border-radius:16px; padding:24px; max-width:640px; width:92%;
    box-shadow:0 20px 60px rgba(0,0,0,.2);
  }}
  .modal h2 {{ font-size:18px; font-weight:700; margin:0 0 14px; }}
  .modal label {{ display:block; font-size:13px; color:var(--mut); margin-bottom:4px; }}
  .modal input {{
    width:100%; padding:9px 12px; border:1px solid var(--line); border-radius:10px;
    font-size:14px; margin-bottom:12px; background:var(--bg); color:var(--ink); outline:none;
  }}
  .modal input:focus {{ border-color:var(--green); }}
  .modal .row {{ display:flex; gap:8px; }}
  .modal .row input {{ flex:1; }}
  .modal .btn-save {{ background:var(--green); color:#fff; padding:9px 18px; border:none; border-radius:10px; cursor:pointer; font-size:14px; }}
  .modal .btn-cancel {{ background:var(--bg); color:var(--mut); border:1px solid var(--line); padding:9px 18px; border-radius:10px; cursor:pointer; font-size:14px; }}
  .rm-grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:6px; max-height:440px; overflow-y:auto; }}
  .rm-grid img {{ width:100%; aspect-ratio:3/4; object-fit:cover; border-radius:8px; border:2px solid transparent; cursor:pointer; }}
  .rm-grid img:hover {{ border-color:var(--green); }}
  .rm-cap {{ font-size:10px; color:var(--mut); text-align:center; margin-top:2px; }}

  .toast {{
    position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
    background:var(--ink); color:#fff; padding:10px 22px; border-radius:12px;
    font-size:14px; z-index:1999; animation:fadeOut 2.2s forwards; pointer-events:none;
  }}
  @keyframes fadeOut {{ 0%,60% {{ opacity:1; }} 100% {{ opacity:0; }} }}

  .foot {{ text-align:center; font-size:12px; color:var(--faint); margin-top:34px; }}
</style>
</head>
<body>
<div class="bar"></div>
<div class="wrap">

<div class="top">
  <div class="brand">moodboard<span class="dot">.</span></div>
  <div class="meta">{date_str} · {len(post_dirs)} 套方案 · 机器出方案，人做判断</div>
  <nav>
    <a href="/">🏠 首页</a>
    <a href="/publish-log">📓 发布登记</a>
    <a href="/sources">📡 信息源</a>
    <a href="/trend-report">📝 编前会</a>
    <a href="#" onclick="showWeeklyReport()">📊 周报</a>
  </nav>
</div>

<div class="intro">
  <h1>今天发哪套？</h1>
  <p>机器从全库未发布档案里准备了 {len(post_dirs)} 套方案。挑一套，换图，改写观点，然后发布。</p>
</div>

<div class="steps">
  <div class="step"><span class="n">1</span><b>挑一套</b><span>每套一个切入点</span></div>
  <div class="step"><span class="n">2</span><b>换图</b><span>悬停帧上 ⇄，图注自动同步</span></div>
  <div class="step"><span class="n">3</span><b>改写观点</b><span>终稿必须是你的话</span></div>
  <div class="step"><span class="n">4</span><b>发布</b><span>复制全文案，手动发</span></div>
  <div class="step"><span class="n">5</span><b>登记</b><span>30 秒，24/48h 回填</span></div>
</div>

<div class="toolbar">
  <button class="btn" onclick="selectAll()">☑ 全选</button>
  <button class="btn" onclick="deselectAll()">☐ 取消全选</button>
  <button class="btn" onclick="downloadSelected()">📦 下载选中 ZIP</button>
  <button class="btn primary" onclick="saveAllEdits()">💾 全部保存</button>
  <button class="btn" onclick="markAllDone()">✅ 全部标为已发</button>
  <div class="filters">
    <button class="filter on" data-p="all" onclick="filterByPillar('all',this)">全部</button>
    <button class="filter" data-p="lookbook" onclick="filterByPillar('lookbook',this)">👔 Lookbook</button>
    <button class="filter" data-p="daily_archive" onclick="filterByPillar('daily_archive',this)">📔 日常档案</button>
    <button class="filter" data-p="moving_taste" onclick="filterByPillar('moving_taste',this)">🎬 影像</button>
    <button class="filter" data-p="reading_taste" onclick="filterByPillar('reading_taste',this)">📖 阅读</button>
    <button class="filter" data-p="product_seeds" onclick="filterByPillar('product_seeds',this)">🔧 产品</button>
  </div>
  <span id="counter">{len(post_dirs)} 待发</span>
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
    <h2>⇄ 换图 — <span id="rm-pos" class="mono" style="font-family:var(--mono)"></span></h2>
    <div style="font-size:12px;color:var(--mut);margin-bottom:10px">候选池 = 全库未发布档案（按评分排序）。点击一张即替换，图注自动同步。</div>
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

<!-- In-page image preview (lightbox) -->
<div class="lightbox" id="lightbox" onclick="closeLightbox(event)">
  <div class="lb-bar">
    <a id="lb-download" download onclick="event.stopPropagation()">⬇️ 下载这张</a>
    <button onclick="closeLightbox(event)">关闭</button>
  </div>
  <img id="lb-img" src="" alt="预览">
</div>

<div class="foot">点帧页内预览（⬇️ 可存单张）· 📦 下载九图 ZIP · 悬停帧 ⇄ 换图（图注自动同步）· 文字直接编辑自动保存 · 人工发布后 📊 登记</div>

</div>

<script>
// ── 页内预览（lightbox，全部浏览器内完成，无远程 open/剪贴板动作） ──
function showLightbox(src) {{
    document.getElementById('lb-img').src = src;
    const dl = document.getElementById('lb-download');
    dl.href = src;
    dl.download = src.split('/').pop() || 'image.jpg';
    document.getElementById('lightbox').classList.add('show');
}}
function closeLightbox() {{
    document.getElementById('lightbox').classList.remove('show');
}}
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeLightbox(); }});

// ── 复制文案（navigator.clipboard） ──
function copyToClipboard(text) {{
    navigator.clipboard.writeText(text).then(() => toast('文案已复制 ✓'));
}}
function copyAll(postId) {{
    const card = document.getElementById(postId);
    const title = card.querySelector('.title').innerText;
    const body = card.querySelector('.caps').innerText;
    const tags = card.querySelector('.tags').innerText;
    const draftEl = card.querySelector('.draft');
    const draft = draftEl ? draftEl.innerText.replace(/^💭\\s*/, '').trim() : '';
    const parts = [title, draft, body, tags].filter(p => p);
    copyToClipboard(parts.join('\\n\\n'));
}}

// ── Inline editing: save to file ──
async function saveEdits(postId) {{
    const card = document.getElementById(postId);
    const title = card.querySelector('.title');
    const body = card.querySelector('.caps');
    const tags = card.querySelector('.tags');
    const draft = card.querySelector('.draft');

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

    const hhmm = new Date().toTimeString().slice(0, 5);
    const savedAt = document.getElementById('saved-' + postId);
    if (savedAt) savedAt.innerText = '最后保存于 ' + hhmm;
    toast('💾 已保存 (' + saved + ' 个文件) · ' + hhmm);
}}

async function saveAllEdits() {{
    const cards = document.querySelectorAll('.plan');
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

    try {{
        // 单一入口：写发布账本（有真实数据时服务端自动镜像到图谱做调权）
        const resp = await fetch('/publish-entries', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{
                pack: packId, time: new Date().toISOString(),
                l24: likes, s24: saves, c24: comments
            }})
        }});
        const data = await resp.json();
        toast('📊 已登记到发布账本 · 24h 后回填到 /publish-log');
        closeFeedback();

        const card = document.getElementById(packId);
        if (card) {{
            card.classList.add('published');
            document.getElementById('status-' + packId).innerText = '✅';
            localStorage.setItem(packId + '-published', '1');
            updateCounter();
        }}
    }} catch(e) {{
        toast('❌ 登记失败，请确认工作台服务在跑');
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
        document.getElementById('report-content').innerHTML = '<p style="color:#c0392b">API 未连接。请先启动: python taste_graph_ai/server.py</p>';
    }}
}}
function closeReport() {{
    document.getElementById('report-modal').classList.remove('show');
}}

// ── Pillar filter (chips) ──
function filterByPillar(pillar, btn) {{
    document.querySelectorAll('.filter').forEach(b => b.classList.remove('on'));
    if (btn) btn.classList.add('on');
    document.querySelectorAll('.plan').forEach(card => {{
        if (pillar === 'all' || card.dataset.pillar === pillar) {{
            card.style.display = 'block';
        }} else {{
            card.style.display = 'none';
        }}
    }});
}}

// ── Published toggle：服务端发布账本为权威（契约 §3），localStorage 仅本地缓存 ──
function togglePublished(postId) {{
    const card = document.getElementById(postId);
    const status = document.getElementById('status-' + postId);
    const on = !card.classList.contains('published');
    if (on) {{
        card.classList.add('published');
        status.innerText = '✅';
        localStorage.setItem(postId + '-published', '1');
        fetch('/publish-entries', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ pack: postId, published_at: new Date().toISOString() }}) }});
    }} else {{
        card.classList.remove('published');
        status.innerText = '⏳';
        localStorage.setItem(postId + '-published', '0');
        fetch('/publish-entries').then(r => r.json()).then(data => {{
            const e = (data.entries || []).find(x => x.pack === postId);
            if (e) fetch('/publish-entries', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ delete: e.id }}) }});
        }});
    }}
    updateCounter();
}}

// ── Select / Counter ──
function getChecked() {{
    return [...document.querySelectorAll('.select-cb:checked')].map(cb => cb.dataset.post);
}}
function selectAll() {{ document.querySelectorAll('.select-cb').forEach(cb => cb.checked = true); updateCounter(); }}
function deselectAll() {{ document.querySelectorAll('.select-cb').forEach(cb => cb.checked = false); updateCounter(); }}
function downloadSelected() {{
    const checked = getChecked();
    if (checked.length === 0) {{ toast('请先勾选要下载的卡片'); return; }}
    // 逐包触发 /pack-zip 浏览器下载（间隔避免多下载拦截；不依赖本机 Finder/路径协议）
    checked.forEach((postId, i) => {{
        const link = document.querySelector('#' + postId + ' a[data-zip]');
        if (link) setTimeout(() => link.click(), i * 600);
    }});
    toast('📦 开始下载 ' + checked.length + ' 个 ZIP');
}}
function markAllDone() {{
    document.querySelectorAll('.plan').forEach(c => {{
        c.classList.add('published');
        localStorage.setItem(c.id + '-published', '1');
        fetch('/publish-entries', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ pack: c.id, published_at: new Date().toISOString() }}) }});
    }});
    document.querySelectorAll('.status').forEach(s => s.innerText = '✅');
    updateCounter();
    toast('已标记 ✓');
}}
function updateCounter() {{
    const total = document.querySelectorAll('.plan').length;
    const published = document.querySelectorAll('.plan.published').length;
    document.getElementById('counter').innerText = (total - published) + ' 待发 · ' + published + ' 已发';
}}

// ── Restore saved edits from localStorage ──
document.querySelectorAll('.plan').forEach(card => {{
    const pid = card.id;
    ['title', 'body', 'tags', 'draft'].forEach(field => {{
        const saved = localStorage.getItem(pid + '-' + field);
        if (saved) {{
            const el = card.querySelector(
                field === 'title' ? '.title' : field === 'body' ? '.caps' :
                field === 'tags' ? '.tags' : '.draft');
            if (!el) return;
            const current = field === 'draft' ? el.innerText.replace(/^💭\\s*/, '') : el.innerText;
            if (current !== saved) el.innerText = saved;
        }}
    }});
}});

// ── Restore published state：服务端发布账本为权威，localStorage 仅离线兜底 ──
async function restorePublished() {{
    const apply = (published) => {{
        document.querySelectorAll('.plan').forEach(card => {{
            if (published.has(card.id)) {{
                card.classList.add('published');
                document.getElementById('status-' + card.id).innerText = '✅';
            }}
        }});
        updateCounter();
    }};
    try {{
        const resp = await fetch('/publish-entries');
        const data = await resp.json();
        apply(new Set((data.entries || []).map(e => e.pack)));
    }} catch (e) {{
        const local = new Set();
        document.querySelectorAll('.plan').forEach(card => {{
            if (localStorage.getItem(card.id + '-published') === '1') local.add(card.id);
        }});
        apply(local);
    }}
}}
restorePublished();

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
                '<img src="' + im.src.replace(/&/g,'&amp;').replace(/"/g,'&quot;') + '" loading="lazy">' +
                '<div class="rm-cap mono" style="font-family:var(--mono)">' + im.final_score + '</div></div>';
        }}).join('');
    }} catch(e) {{
        grid.innerHTML = '<p style="color:#c0392b">候选池加载失败 — 请确认 8787 服务在跑。</p>';
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
                const bodyEl = card.querySelector('.caps');
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
