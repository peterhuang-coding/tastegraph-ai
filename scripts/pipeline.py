#!/usr/bin/env python3
"""
TasteGraph AI — 一键全流程管道
===============================
从爬虫到发布审稿，完整闭环。

流程：
  1. 爬取：从 link_sources / link_packs / manifests / DB 抓取新内容
  2. 选图：CLIP + 知识图谱打分，选 Top-N 图片
  3. 生成：AI 生成小红书文案（标题+正文+标签）
  4. 工作台：生成 QUEUE.html 审稿，启动本地服务
  5. 反馈：发布后录入互动数据 → 回灌 taste graph

用法：
  python3 scripts/pipeline.py              # 全流程运行
  python3 scripts/pipeline.py --crawl      # 只爬取
  python3 scripts/pipeline.py --publish    # 只生成发布包
  python3 scripts/pipeline.py --serve      # 只启动 QUEUE 服务
  python3 scripts/pipeline.py --feedback   # 查看发布效果周报
"""

import argparse
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ── Project root ───────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from taste_graph_ai.config import ensure_dirs, DATA_DIR
from taste_graph_ai.container import get_container
from taste_graph_ai.infrastructure.db.connection import init_db, get_db
from taste_graph_ai.infrastructure.repos.images import ImageRepository
from taste_graph_ai.infrastructure.repos.sources import SourceRepository
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.feedback import FeedbackRepository
from taste_graph_ai.domain.enums import ImageStatus
from taste_graph_ai.services.clip import get_clip


# ═══════════════════════════════════════════════════════════════
# Step 1: Crawl — 从多源爬取内容
# ═══════════════════════════════════════════════════════════════

def step_crawl(duration_hours: float = 1, max_items: int = 50) -> int:
    """运行爬虫循环。"""
    print("\n" + "=" * 60)
    print("  Step 1: 爬取 — 多源内容发现")
    print("=" * 60)

    from scripts.crawl_loop_6h import main as crawl_main
    # 保存并恢复 sys.argv，避免污染其他模块
    import sys
    _saved_argv = sys.argv
    sys.argv = [
        "crawl_loop_6h.py",
        "--duration-hours", str(duration_hours),
        "--rate-limit", "200",
        "--max-discovered", "50",
    ]
    try:
        return crawl_main()
    except SystemExit as e:
        return e.code if e.code is not None else 0
    finally:
        sys.argv = _saved_argv


# ═══════════════════════════════════════════════════════════════
# Step 2: 图谱管理 — 加载/更新知识图谱
# ═══════════════════════════════════════════════════════════════

def step_graph() -> None:
    """加载知识图谱并打印统计。"""
    print("\n" + "=" * 60)
    print("  Step 2: 图谱 — 加载知识图谱")
    print("=" * 60)

    ensure_dirs()
    container = get_container()
    graph = container.taste_graph

    print(f"  Nodes: {graph.node_count}")
    print(f"  Edges: {graph.edge_count}")
    print(f"  Graph file: {graph.data_path}")


# ═══════════════════════════════════════════════════════════════
# Step 3: 选图 — CLIP + 图谱打分，选 Top-N 图片
# ═══════════════════════════════════════════════════════════════

async def step_select_images(count: int = 6) -> list:
    """从数据库选图，CLIP + 图谱打分，返回 Top-N。"""
    print("\n" + "=" * 60)
    print(f"  Step 3: 选图 — CLIP + 图谱打分（选 {count} 张）")
    print("=" * 60)

    await init_db()
    db = await get_db()
    image_repo = ImageRepository(db)
    source_repo = SourceRepository(db)
    feedback_repo = FeedbackRepository(db)
    pack_repo = PackRepository(db)

    all_sources = await source_repo.list_all()
    source_names = {s.id: s.name for s in all_sources}
    liked_ids = set()
    try:
        liked_ids = set(await feedback_repo.get_liked_image_ids())
    except Exception:
        pass

    # 获取候选图片
    candidates = []
    try:
        candidates = await image_repo.list_by_status(ImageStatus.SELECTED, limit=100)
    except Exception:
        pass
    if len(candidates) < count:
        try:
            pending = await image_repo.list_by_status(ImageStatus.PENDING, limit=200)
            candidates.extend(pending)
        except Exception:
            pass

    valid = [img for img in candidates if img.local_path and Path(img.local_path).exists()]
    if not valid:
        print("  ❌ 没有可用图片。先运行爬取。")
        await db.close()
        return []

    print(f"  Found {len(valid)} valid images")

    clip_svc = get_clip()
    graph = get_container().taste_graph

    PILLARS = [
        {"name": "lookbook", "clip_text": "editorial fashion runway silhouette tailored coat proportion"},
        {"name": "daily_archive", "clip_text": "city walking coffee table hotel lobby concrete shadow everyday"},
        {"name": "reading_taste", "clip_text": "magazine editorial design cultural observation"},
        {"name": "product_seeds", "clip_text": "object still life industrial design notebook minimal product"},
    ]

    # 获取最近用过的 pillar
    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()
    recent_packs = []
    try:
        recent_packs = await pack_repo.get_latest_packs(20)
    except Exception:
        pass
    recent_pillars = set()
    for rp in recent_packs:
        if hasattr(rp, 'date') and rp.date >= week_ago:
            t = rp.theme.lower() if hasattr(rp, 'theme') else ""
            for p in PILLARS:
                words = p["clip_text"].split()[:3]
                if any(w in t for w in words):
                    recent_pillars.add(p["name"])

    active_pillars = [p for p in PILLARS if p["name"] not in recent_pillars] or PILLARS

    scored = []
    for img in valid:
        score = 0.0

        # 图谱分 (25%)
        try:
            graph_score = graph.score_content(keywords=list(img.keywords or []), source_id=img.source_id or "")
            score += min(1.0, graph_score / 10) * 0.25
        except Exception:
            score += 0.10

        # CLIP 分 (25%)
        try:
            clip_sim = clip_svc.compute_similarity(
                img.local_path,
                "editorial fashion low-saturation brutalist archive quiet minimal"
            )
            score += min(1.0, max(0.0, clip_sim)) * 0.25
        except Exception:
            score += 0.15

        # 多样性 (15%)
        src_name = source_names.get(img.source_id or "", "").lower()
        runway_indicators = ["vogue", "runway", "off-white", "louis vuitton", "dior", "prada"]
        is_runway = any(ind in src_name for ind in runway_indicators)
        if not is_runway:
            score += 0.15

        # Pillar 匹配 (15%)
        best_pillar = 0.0
        for pillar in active_pillars:
            try:
                sim = clip_svc.compute_similarity(img.local_path, pillar["clip_text"])
                best_pillar = max(best_pillar, sim * 0.15)
            except Exception:
                pass
        score += best_pillar

        # 喜欢标记 bonus (10%)
        if img.id in liked_ids:
            score += 0.10

        # 时间衰减 (10%) — 越新的图分越高
        if hasattr(img, 'created_at') and img.created_at:
            try:
                img_date = img.created_at.date() if hasattr(img.created_at, 'date') else today
                days_old = (today - img_date).days
                score += max(0, 0.10 - days_old * 0.005)
            except Exception:
                pass

        scored.append((score, img, is_runway))

    scored.sort(key=lambda x: x[0], reverse=True)

    # 选图：来源多样性
    picked = []
    used_sources = set()
    runway_count = 0
    max_runway = max(count // 2, 2)

    for score, img, is_runway in scored:
        src = img.source_id or ""
        if src in used_sources:
            continue
        if is_runway and runway_count >= max_runway:
            continue
        picked.append((score, img))
        used_sources.add(src)
        if is_runway:
            runway_count += 1
        if len(picked) >= count:
            break

    # 不够就放松限制
    if len(picked) < count:
        for score, img, is_runway in scored:
            src = img.source_id or ""
            if src in used_sources:
                continue
            picked.append((score, img))
            used_sources.add(src)
            if len(picked) >= count:
                break

    print(f"  Selected {len(picked)} images:")
    for i, (score, img) in enumerate(picked):
        src_name = source_names.get(img.source_id or "", "?")
        print(f"    #{i+1}: score={score:.2f} src={src_name[:20]}")

    await db.close()
    return picked


# ═══════════════════════════════════════════════════════════════
# Step 4: 生成 — 创建发布包 + QUEUE.html
# ═══════════════════════════════════════════════════════════════

async def step_generate_packs(picked: list, date_str: str = None) -> Path:
    """为选中的图片生成发布包和 QUEUE.html。"""
    print("\n" + "=" * 60)
    print("  Step 4: 生成 — 发布包 + 文案")
    print("=" * 60)

    if not picked:
        print("  ❌ 没有图片，跳过生成。")
        return None

    from scripts.generate_publish_packs import (
        _generate_queue_html, _generate_post_metadata,
        _detect_image_pillar, _clean_keywords,
    )

    if date_str is None:
        date_str = date.today().isoformat()

    # 初始化所有服务
    await init_db()
    db = await get_db()
    source_repo = SourceRepository(db)
    all_sources = await source_repo.list_all()
    source_names = {s.id: s.name for s in all_sources}

    clip_svc = get_clip()

    batch_dir = Path(str(BASE_DIR / "posts" / date_str))
    batch_dir.mkdir(parents=True, exist_ok=True)

    post_dirs = []
    for i, (score, img) in enumerate(picked):
        post_num = f"post-{i+1:03d}"
        post_dir = batch_dir / post_num
        post_dir.mkdir(parents=True, exist_ok=True)

        # 复制图片
        src_path = Path(img.local_path)
        ext = src_path.suffix or ".jpg"
        shutil.copy2(src_path, post_dir / f"image{ext}")

        # 生成元数据
        src_name = source_names.get(img.source_id or "", "")
        keywords = _clean_keywords(list(img.keywords)) if img.keywords else []
        pillar = _detect_image_pillar(img, src_name, clip_svc)

        title, body, hashtags = _generate_post_metadata(img, score, src_name, keywords, pillar)

        # 写文件
        (post_dir / "title.txt").write_text(title, encoding="utf-8")
        (post_dir / "body.txt").write_text(body, encoding="utf-8")
        (post_dir / "hashtags.txt").write_text(hashtags, encoding="utf-8")
        (post_dir / "score.txt").write_text(f"{score:.2f}", encoding="utf-8")
        (post_dir / "pillar.txt").write_text(pillar, encoding="utf-8")

        # 发布清单
        checklist = f"""# Post {post_num} — Publish Checklist

- [ ] 图片方向正确（竖版优先）
- [ ] 标题无误：「{title}」
- [ ] 正文无误
- [ ] 话题标签完整：{hashtags}
- [ ] 发布后录入反馈 → 点击 QUEUE.html 的 📊 按钮
"""
        (post_dir / "publish-checklist.md").write_text(checklist, encoding="utf-8")

        post_dirs.append(post_dir)
        print(f"  ✅ {post_num}: {title} (score={score:.2f})")

    # 生成 QUEUE.html
    _generate_queue_html(batch_dir, post_dirs, date_str)
    print(f"\n  📋 QUEUE.html: {batch_dir / 'QUEUE.html'}")

    await db.close()
    return batch_dir


# ═══════════════════════════════════════════════════════════════
# Step 5: 启动审稿服务
# ═══════════════════════════════════════════════════════════════

def step_serve(port: int = 8765) -> None:
    """启动 QUEUE 审稿服务 + FastAPI 图谱服务。"""
    print("\n" + "=" * 60)
    print("  Step 5: 启动服务")
    print("=" * 60)

    # 先启动 FastAPI 图谱服务（后台）
    server_pid = None
    try:
        server_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "taste_graph_ai.server:app",
             "--host", "0.0.0.0", "--port", "8787"],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        server_pid = server_proc.pid
        print(f"  ✅ 图谱服务: http://localhost:8787 (PID {server_pid})")
        time.sleep(1.5)
    except Exception as e:
        print(f"  ⚠️ 图谱服务启动失败: {e}")

    # 找到最新的 QUEUE.html
    posts_dir = BASE_DIR / "posts"
    date_dirs = sorted(posts_dir.glob("20*"), reverse=True)
    if not date_dirs:
        print("  ❌ 没有发布包，先运行 --publish")
        return

    latest = date_dirs[0]
    queue_html = latest / "QUEUE.html"
    if not queue_html.exists():
        print(f"  ❌ 没有 QUEUE.html 在 {latest}")
        return

    print(f"\n  🎯 你的编辑工作台已就绪！")
    print(f"  ──────────────────────────────────")
    print(f"  📅 今日发布包: {latest.name}")
    print(f"  🔗 打开审稿: http://localhost:{port}/posts/{latest.name}/QUEUE.html")
    print(f"  📋 操作指南:")
    print(f"     1. 浏览器打开上面的链接")
    print(f"     2. 双击图片 → Preview 打开")
    print(f"     3. 从 Preview 拖图片到小红书")
    print(f"     4. 复制文案 → 粘贴到小红书")
    print(f"     5. 发布后点 📊 录入反馈")
    print(f"  ──────────────────────────────────")
    print(f"  Press Ctrl+C to stop all services\n")

    # 启动 QUEUE 服务（前台）
    from scripts.queue_server import main as queue_main
    _saved_argv = sys.argv
    sys.argv = ["queue_server.py"]
    try:
        queue_main()
    except KeyboardInterrupt:
        print("\n  服务已停止。")
    finally:
        sys.argv = _saved_argv
        if server_pid:
            os.kill(server_pid, signal.SIGTERM)


# ═══════════════════════════════════════════════════════════════
# Step 6: 反馈 — 查看发布效果周报
# ═══════════════════════════════════════════════════════════════

async def step_feedback() -> None:
    """查看发布效果周报。"""
    from scripts.publish_feedback import generate_weekly_report
    report = await generate_weekly_report()
    print("\n" + "=" * 60)
    print("  Step 6: 反馈 — 发布效果周报")
    print("=" * 60)
    print(f"\n  {report.get('period', '')}")
    print(f"  平均互动分: {report.get('avg_engagement', 0)}/10")
    print(f"  🔥 高强度: {report.get('high_performers_count', 0)} 篇")
    print(f"  ❄️ 低互动: {report.get('low_performers_count', 0)} 篇")

    top = report.get("top_themes", [])
    if top:
        print("\n  🏆 Top 主题:")
        for t in top:
            bar = "█" * int(t["avg_score"])
            print(f"    {t['avg_score']:.1f} {bar} {t['theme']}（{t['count']}篇）")

    suggestions = report.get("suggestions", [])
    if suggestions:
        print("\n  💡 建议:")
        for s in suggestions:
            print(f"    {s}")
    print("=" * 60)


# ═══════════════════════════════════════════════════════════════
# 全流程
# ═══════════════════════════════════════════════════════════════

async def full_pipeline(
    crawl_hours: float = 1,
    image_count: int = 6,
    skip_crawl: bool = False,
    date_str: str = None,
    start_serve: bool = True,
) -> None:
    """执行完整 pipeline：爬取 → 选图 → 生成 → 启动服务。"""
    start_time = time.time()

    print(f"\n{'='*60}")
    print(f"  TasteGraph AI — 全流程管道")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    if date_str is None:
        date_str = date.today().isoformat()

    # Step 1: 爬取
    if not skip_crawl:
        step_crawl(duration_hours=crawl_hours)
    else:
        print("  ⏭️ 跳过爬取（使用已有数据）")

    # Step 2: 图谱
    step_graph()

    # Step 3: 选图
    picked = await step_select_images(count=image_count)
    if not picked:
        print("\n  ❌ 没有可用的图片。请先运行爬取，或启用 --skip-crawl 使用已有数据。")
        print(f"    试试: python3 scripts/pipeline.py --skip-crawl\n")
        return

    # Step 4: 生成发布包
    await step_generate_packs(picked, date_str=date_str)

    elapsed = time.time() - start_time
    print(f"\n  ⏱ 全部用时: {elapsed:.0f}s")

    # Step 5: 启动服务（阻塞）
    if start_serve:
        step_serve()
    else:
        print(f"\n  💡 运行 'bash start.sh serve' 启动审稿服务")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="TasteGraph AI — 一键全流程管道",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 scripts/pipeline.py                    # 全流程（爬取1h + 选图 + 生成 + 启动服务）
  python3 scripts/pipeline.py --skip-crawl       # 跳过爬取，用已有数据
  python3 scripts/pipeline.py --crawl-only       # 只爬取
  python3 scripts/pipeline.py --publish-only     # 只生成发布包
  python3 scripts/pipeline.py --serve-only       # 只启动 QUEUE 服务
  python3 scripts/pipeline.py --feedback         # 查看发布效果周报
  python3 scripts/pipeline.py --count 9          # 生成 9 篇
  python3 scripts/pipeline.py --crawl-hours 2    # 爬取 2 小时
        """,
    )
    parser.add_argument("--skip-crawl", action="store_true", help="跳过爬取")
    parser.add_argument("--crawl-only", action="store_true", help="只运行爬取")
    parser.add_argument("--publish-only", action="store_true", help="只生成发布包")
    parser.add_argument("--serve-only", action="store_true", help="只启动 QUEUE 服务")
    parser.add_argument("--feedback", action="store_true", help="查看发布效果周报")
    parser.add_argument("--crawl-hours", type=float, default=1, help="爬取时长（小时）")
    parser.add_argument("--count", type=int, default=6, help="生成几篇帖子")
    parser.add_argument("--date", default=None, help="日期 (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.crawl_only:
        step_crawl(duration_hours=args.crawl_hours)
    elif args.publish_only:
        asyncio.run(full_pipeline(
            image_count=args.count,
            skip_crawl=True,
            date_str=args.date,
            start_serve=False,
        ))
    elif args.serve_only:
        step_serve()
    elif args.feedback:
        asyncio.run(step_feedback())
    else:
        asyncio.run(full_pipeline(
            crawl_hours=args.crawl_hours,
            image_count=args.count,
            skip_crawl=args.skip_crawl,
            date_str=args.date,
        ))


if __name__ == "__main__":
    main()