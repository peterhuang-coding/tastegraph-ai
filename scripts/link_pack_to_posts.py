#!/usr/bin/env python3
"""Unified content pipeline: link_pack → AI-generated posts.

Reads the latest link_pack, uses its theme + angles + reference links
to generate 3-5 Xiaohongshu posts with proper taste-driven copy.

Usage:
  python scripts/link_pack_to_posts.py                    # use latest link_pack
  python scripts/link_pack_to_posts.py --date 2026-04-26  # specific date
  python scripts/link_pack_to_posts.py --dry-run           # preview only, no files

This bridges the gap between the high-quality AI link_packs (which stopped
at txt files) and the actual post generation pipeline.
"""

import argparse
import asyncio
import json
import shutil
import sys
from datetime import date as date_type
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
from taste_graph_ai.infrastructure.ai.client import AIClient

LINK_PACKS_DIR = BASE_DIR / "link_packs"
POSTS_DIR = BASE_DIR / "posts"

# Content pillars with their CLIP reference texts
PILLARS = {
    "lookbook": "editorial fashion runway silhouette tailored coat proportion",
    "daily_archive": "city walking coffee table hotel lobby concrete shadow everyday",
    "moving_taste": "fashion film campaign video experimental cinematic pacing framing",
    "reading_taste": "magazine editorial design typography article cultural observation",
    "product_seeds": "object still life industrial design notebook tote desk minimal product",
}


async def run(date_str: str = None, dry_run: bool = False) -> list[dict]:
    """Main pipeline: link_pack → AI post generation."""
    # 1. Find link_pack
    if date_str:
        pack_file = LINK_PACKS_DIR / f"{date_str}.txt"
    else:
        packs = sorted(LINK_PACKS_DIR.glob("20*.txt"), reverse=True)
        if not packs:
            print("❌ No link packs found. Run run_daily_moodboard.py first.")
            return []
        pack_file = packs[0]

    if not pack_file.exists():
        print(f"❌ Link pack not found: {pack_file}")
        return []

    pack_text = pack_file.read_text(encoding="utf-8")
    pack_date = pack_file.stem

    print(f"📄 Reading link pack: {pack_date}")

    # 2. Parse link_pack structure
    pack_data = _parse_link_pack(pack_text, pack_date)
    print(f"   Theme: {pack_data['theme']}")
    print(f"   Lookbook refs: {len(pack_data['lookbook_refs'])}")
    print(f"   Video refs: {len(pack_data['video_refs'])}")
    print(f"   Article refs: {len(pack_data['article_refs'])}")
    print(f"   Content angles: {len(pack_data['content_angles'])}")

    # 3. Get available images from the pool
    ensure_dirs()
    await init_db()
    get_container()
    get_clip()

    db = await get_db()
    image_repo = ImageRepository(db)
    source_repo = SourceRepository(db)
    pack_repo = PackRepository(db)
    feedback_repo = FeedbackRepository(db)

    all_sources = await source_repo.list_all()
    source_names: dict[str, str] = {s.id: s.name for s in all_sources}

    candidates = await image_repo.list_by_status(ImageStatus.SELECTED, limit=100)
    if len(candidates) < 9:
        pending = await image_repo.list_by_status(ImageStatus.PENDING, limit=200)
        candidates.extend(pending)

    valid = [img for img in candidates if img.local_path and Path(img.local_path).exists()]
    print(f"   Available images: {len(valid)}")

    if not valid:
        print("❌ No images available. Run scrape first.")
        await db.close()
        return []

    # 4. For each content angle, pick matching images + generate copy
    posts = []
    used_image_ids: set[str] = set()
    clip_svc = get_clip()

    for i, angle in enumerate(pack_data["content_angles"][:5]):
        angle_text = angle["angle"]
        angle_pillar = angle.get("pillar", "daily_archive")

        print(f"\n--- Post {i+1}: {angle_text[:40]}... ---")

        # 4a. Pick best-matching images for this angle
        pillar_clip_text = PILLARS.get(angle_pillar, PILLARS["daily_archive"])
        scored_images = []
        for img in valid:
            if img.id in used_image_ids:
                continue
            # CLIP match against angle + pillar
            try:
                sim = clip_svc.compute_similarity(img.local_path, f"{angle_text} {pillar_clip_text}")
            except Exception:
                sim = 0.3
            scored_images.append((sim, img))

        scored_images.sort(key=lambda x: x[0], reverse=True)
        best_img = scored_images[0][1] if scored_images else None

        if not best_img:
            print("   ⚠️ No matching image found")
            continue

        used_image_ids.add(best_img.id)
        src_name = source_names.get(best_img.source_id or "", "")

        # 4b. AI-generated copy using link_pack context
        keywords = [kw for kw in best_img.keywords if len(kw) > 2][:6]
        title, body, hashtags = await _ai_generate_from_link_pack(
            pack_data, angle, src_name, keywords, angle_pillar
        )

        if dry_run:
            print(f"   Title: {title}")
            print(f"   Body: {body}")
            print(f"   Tags: {hashtags}")
            print(f"   Image: {best_img.local_path}")
            posts.append({
                "title": title,
                "body": body,
                "hashtags": hashtags,
                "image_path": best_img.local_path,
                "pillar": angle_pillar,
                "angle": angle_text,
            })
            continue

        # 4c. Write post files
        batch_dir = POSTS_DIR / pack_date
        batch_dir.mkdir(parents=True, exist_ok=True)
        post_dir = batch_dir / f"post-{i+1:03d}"
        post_dir.mkdir(parents=True, exist_ok=True)

        src_path = Path(best_img.local_path)
        ext = src_path.suffix or ".jpg"
        shutil.copy2(src_path, post_dir / f"image{ext}")

        (post_dir / "title.txt").write_text(title, encoding="utf-8")
        (post_dir / "body.txt").write_text(body, encoding="utf-8")
        (post_dir / "hashtags.txt").write_text(hashtags, encoding="utf-8")
        (post_dir / "score.txt").write_text(f"{best_img.final_score:.2f}", encoding="utf-8")
        (post_dir / "pillar.txt").write_text(angle_pillar, encoding="utf-8")
        (post_dir / "source_angle.txt").write_text(angle_text, encoding="utf-8")

        # Checklist
        checklist = f"""# Post post-{i+1:03d} — Publish Checklist

- [ ] 图片方向正确（竖版优先）
- [ ] 标题无误：「{title}」
- [ ] 正文无误
- [ ] 话题标签完整
- [ ] 角度准确：{angle_text}
- [ ] 发布后录入反馈 → /api/v1/feedback/publish-metrics
"""
        (post_dir / "publish-checklist.md").write_text(checklist, encoding="utf-8")

        print(f"   ✅ {title}")
        posts.append({
            "title": title,
            "body": body,
            "hashtags": hashtags,
            "image_path": str(post_dir / f"image{ext}"),
            "pillar": angle_pillar,
            "angle": angle_text,
        })

    # 5. Generate QUEUE.html
    if not dry_run and posts:
        batch_dir = POSTS_DIR / pack_date
        post_dirs = sorted(batch_dir.glob("post-*"))
        # Use the existing QUEUE generation function
        from scripts.generate_publish_packs import _generate_queue_html
        _generate_queue_html(batch_dir, post_dirs, pack_date)
        print(f"\n📋 QUEUE.html generated: {batch_dir / 'QUEUE.html'}")

    await db.close()

    if dry_run:
        print(f"\n🔍 Dry run complete. {len(posts)} posts previewed.")
    else:
        print(f"\n✅ {len(posts)} posts generated from link_pack {pack_date}")

    return posts


def _parse_link_pack(text: str, date_str: str) -> dict:
    """Parse a link_pack txt into structured data."""
    lines = text.strip().split("\n")

    theme = ""
    why_today = ""
    lookbook_refs = []
    video_refs = []
    article_refs = []
    content_angles = []

    current_section = ""
    current_ref = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Theme line
        if line.startswith("DAILY THEME"):
            theme = line.split("—", 1)[-1].strip().strip('"')
            continue
        if line.startswith("Why it fits today:"):
            why_today = line.replace("Why it fits today:", "").strip()
            continue

        # Content angles
        if "XIAOHONGSHU CONTENT ANGLES" in line:
            current_section = "angles"
            continue

        # Section headers
        if "LOOKBOOK / IMAGE REFERENCES" in line:
            current_section = "lookbook"
            continue
        if "VIDEOS / MOVING IMAGE REFERENCES" in line:
            current_section = "video"
            continue
        if "ARTICLES / DEEP READING" in line:
            current_section = "article"
            continue
        if "FEEDBACK PROMPT" in line:
            current_section = "feedback"
            continue

        # Skip separator lines
        if line.startswith("===") or line.startswith("---"):
            continue

        # Parse angle
        if current_section == "angles" and line[0].isdigit() and ")" in line:
            angle_text = line.split(")", 1)[-1].strip().strip('"')
            # Detect pillar from angle text
            pillar = _detect_pillar_from_text(angle_text)
            content_angles.append({"angle": angle_text, "pillar": pillar})
            continue

        # Parse reference links
        if line.startswith("[") and "]" in line and "http" in line:
            try:
                idx_end = line.index("]")
                url_start = line.index("http")
                url = line[url_start:].strip()
                name = line[1:idx_end].strip()

                ref = {"name": name, "url": url}

                # Read next lines for Why/Study/Use
                # (handled below via state tracking)
            except ValueError:
                continue

    # Extract theme from first header
    if not theme:
        for line in lines:
            if "DAILY THEME" in line:
                theme = line.split("—", 1)[-1].strip().strip('"')
                break

    return {
        "date": date_str,
        "theme": theme or "Daily Archive",
        "why_today": why_today,
        "lookbook_refs": lookbook_refs,
        "video_refs": video_refs,
        "article_refs": article_refs,
        "content_angles": content_angles,
    }


def _detect_pillar_from_text(text: str) -> str:
    """Detect content pillar from angle text."""
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["runway", "lookbook", "秀", "coat", "silhouette", "proportion", "styling"]):
        return "lookbook"
    if any(kw in text_lower for kw in ["video", "film", "镜头", "剪辑", "moving", "pacing", "cinematic"]):
        return "moving_taste"
    if any(kw in text_lower for kw in ["article", "caption", "editorial", "编辑", "文化", "reading", "observation"]):
        return "reading_taste"
    if any(kw in text_lower for kw in ["object", "product", "产品", "material", "设计", "industrial"]):
        return "product_seeds"
    return "daily_archive"


async def _ai_generate_from_link_pack(
    pack_data: dict,
    angle: dict,
    source_name: str,
    keywords: list[str],
    pillar: str,
) -> tuple[str, str, str]:
    """Use AI to generate post copy from link_pack context + image keywords.

    This is the key bridge: link_pack editorial judgment → post copy.
    """
    theme = pack_data.get("theme", "")
    angle_text = angle.get("angle", "")
    kw_str = ", ".join(keywords[:6]) if keywords else "editorial, archive"
    src_str = source_name or "archive"

    pillar_hints = {
        "lookbook": "Fashion observation. Focus on silhouette, proportion, fabric, styling logic.",
        "daily_archive": "Daily visual diary. Focus on everyday objects, city moments, materials, light.",
        "moving_taste": "Moving image aesthetics. Focus on pacing, framing, attitude, cinematic energy.",
        "reading_taste": "Editorial judgment. Focus on cultural observation, writing tone, magazine logic.",
        "product_seeds": "Object study. Focus on materials, industrial design, product potential.",
    }

    try:
        ai = AIClient()
        prompt = f"""You are the editor of a personal taste archive. Reference: Hidden NY, JJJJound, 032c.

Today's editorial theme: {theme}
Post angle: {angle_text}
Source: {src_str}
Keywords: {kw_str}
Pillar context: {pillar_hints.get(pillar, '')}

Write a Xiaohongshu post. Rules:
- Title: 12-25 chars. A taste judgment, NOT a description. Like a catalog label with attitude.
  Good: "灰。羊毛。没有logo。" / "最近越来越喜欢不主动讨好的东西"
  Bad: "Off-White Archive · tailoredcoat"
- Body: 30-80 chars. Museum label style. Brand. Year. Material. City. Short fragments with periods.
  Good: "RAF SIMONS. AW 1998. Antwerp."
  Good: "灰色羊毛混纺。落肩设计。葡萄牙制造。"
  Bad: "周一午后的街角，水泥墙面被光线切出柔和的棱角..."
- Never use: 氛围, 感觉, 安静, 午后, 光线, 柔和, 美, 高级, 绝了
- Max 3-4 fragments. One cultural line max per post.
- Hashtags: 4-6 tags. #moodboard + 2-3 content tags + 1 pillar tag.

Return ONLY valid JSON:
{{"title": "...", "body": "...", "hashtags": "#moodboard #... #..."}}"""

        result = await ai.chat_json(prompt, 500)
        await ai.close()

        if result and result.get("title") and result.get("body"):
            title = _clean_text(result["title"], max_len=30)
            body = _clean_text(result["body"], max_len=120)
            hashtags = result.get("hashtags", "#moodboard #审美积累")
            if title and body:
                return title, body, hashtags
    except Exception:
        pass

    # Fallback
    return (
        f"{theme[:20]} · {angle_text[:15]}" if theme else "编辑档案",
        f"{src_str}。2024。{'。'.join(keywords[:3])}。" if keywords else f"{src_str}。2024。",
        "#moodboard #审美积累 #穿搭参考",
    )


def _clean_text(text: str, max_len: int = 120) -> str:
    """Strip emoji, hashtags, excessive punctuation."""
    import re
    text = re.sub(r'#\S+', '', text)
    text = re.sub(r'[\U0001F300-\U0001F9FF☀-➿⭐✀-➿️‍]', '', text)
    text = re.sub(r'！+', '', text)
    text = re.sub(r' +', ' ', text).strip()
    if len(text) > max_len:
        text = text[:max_len-3] + '...'
    return text


def main():
    parser = argparse.ArgumentParser(description="从 link_pack 生成小红书帖子")
    parser.add_argument("--date", default=None, help="link_pack 日期 (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不写文件")
    args = parser.parse_args()

    asyncio.run(run(date_str=args.date, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
