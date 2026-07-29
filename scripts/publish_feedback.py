"""发布反馈闭环 — 手动录入小红书帖子互动数据，自动回灌 taste graph 调权重。

API:
  POST /api/v1/feedback/publish-metrics  — 录入单帖互动数据
  GET  /api/v1/feedback/weekly-report    — 获取本周「什么管用」报告
  POST /api/v1/feedback/batch-metrics    — 批量录入（JSON 粘贴）

Usage:
  python scripts/publish_feedback.py report   # 命令行周报
  python scripts/publish_feedback.py record   # 交互式录入
"""

import json
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ── Project root ──────────────────────────────────────────────
# 必须在所有 taste_graph_ai.* import 之前，否则 ModuleNotFoundError。
# 与 pipeline.py / daemon_scheduler.py 同样的 sys.path 引导习惯。
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import aiosqlite

from taste_graph_ai.config import DATA_DIR
from taste_graph_ai.container import get_container
from taste_graph_ai.domain.enums import FeedbackLabel, FeedbackTargetType, NodeType
from taste_graph_ai.domain.models import PublishRecord
from taste_graph_ai.infrastructure.db.connection import get_db
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.publish_history import PublishHistoryRepository
from taste_graph_ai.infrastructure.repos.feedback import FeedbackRepository
from taste_graph_ai.services.feedback import FeedbackService


ENGAGEMENT_WEIGHTS = {
    "save": 3.0,      # 收藏最值钱——说明真的有用
    "comment": 2.0,   # 评论第二——触发了互动欲望
    "like": 1.0,      # 点赞——基础好感
    "share": 4.0,     # 分享最值钱——愿意传播
}


def compute_engagement_score(likes: int, saves: int, comments: int, shares: int = 0) -> float:
    """综合互动分（0-10），相对于小红书同类内容的基准线。

    小红书 moodboard/审美类笔记的参考基准：
    - 1000+ 小眼睛 ≈ 正常曝光
    - 赞藏比 3-5% 算不错
    """
    weighted = (
        likes * ENGAGEMENT_WEIGHTS["like"]
        + saves * ENGAGEMENT_WEIGHTS["save"]
        + comments * ENGAGEMENT_WEIGHTS["comment"]
        + shares * ENGAGEMENT_WEIGHTS["share"]
    )
    # 对数归一化：100 weighted points → 5 分, 500 → 8 分, 1000 → 10 分
    import math
    if weighted <= 0:
        return 0.0
    raw = math.log(weighted + 1) * 2.5
    return round(min(10.0, max(0.0, raw)), 2)


def engagement_label(score: float) -> str:
    """互动质量标签。"""
    if score >= 7:
        return "爆款级"
    elif score >= 5:
        return "不错"
    elif score >= 3:
        return "一般"
    elif score >= 1:
        return "偏低"
    return "无互动"


async def record_publish_metrics(
    pack_id: str,
    likes: int = 0,
    saves: int = 0,
    comments: int = 0,
    shares: int = 0,
    post_url: str = "",
) -> dict:
    """录入帖子互动数据 → 更新 publish_history → 回灌 taste graph。

    调权逻辑：
    - 高互动（engagement >= 5）→ boost 该 pack 关联的 images → 对应 concept/source 权重 +2
    - 低互动（engagement < 1）→ 降权 -2
    - 中等互动 → 不做调整（保持稳定）
    """
    db = await get_db()
    pack_repo = PackRepository(db)
    publish_repo = PublishHistoryRepository(db)
    feedback_repo = FeedbackRepository(db)
    event_log = EventLog()

    # 1. 查找或创建 publish record
    pack = await pack_repo.get_by_id(pack_id)
    existing = await publish_repo.get_by_pack_id(pack_id)

    score = compute_engagement_score(likes, saves, comments, shares)
    label = engagement_label(score)
    now = datetime.now(timezone.utc).isoformat()

    if existing:
        # 更新已有记录
        record_id = existing["id"]
        await db.execute(
            """UPDATE publish_history
            SET likes=?, saves=?, comments=?, engagement_rate=?
            WHERE id=?""",
            (likes, saves, comments, score, record_id),
        )
    else:
        # 新建记录
        record_id = uuid.uuid4().hex[:12]
        record = PublishRecord(
            id=record_id,
            pack_id=pack_id,
            published_at=now,
            platform="xiaohongshu",
            post_url=post_url,
            likes=likes,
            saves=saves,
            comments=comments,
            engagement_rate=score,
        )
        await publish_repo.save(record)

    await db.commit()

    # 2. 回灌 taste graph（仅在高/低互动时调整）
    theme = pack.theme if pack else ""
    delta = 0
    feedback_label = None

    if score >= 5:
        delta = +2
        feedback_label = FeedbackLabel.DUI_WEI
    elif score < 1:
        delta = -2
        feedback_label = FeedbackLabel.BU_DUI_WEI

    affected_images = []
    if delta != 0 and pack:
        container = get_container()
        graph = container.taste_graph
        feedback_service = FeedbackService(feedback_repo, event_log)

        # 获取 pack 关联的图片
        images = await pack_repo.get_pack_images(pack_id)
        for img in images:
            img_id = img["image_id"]
            affected_images.append({
                "image_id": img_id,
                "keywords": img.get("keywords", []),
            })

            # 通过 feedback service 精准调整 image → concept 边权重
            if feedback_label:
                try:
                    await feedback_service.record(
                        target_type=FeedbackTargetType.IMAGE,
                        target_id=img_id,
                        label=feedback_label,
                        note=f"发布反馈: engagement={score} ({label}), likes={likes} saves={saves}",
                    )
                except Exception:
                    pass

        # 如果 theme 不是空，也调整 theme concept 的权重
        if theme:
            concept_id = f"concept:{theme.lower().replace(' ', '_')}"
            # 确保 concept 节点存在
            if concept_id not in graph:
                graph.add_node(theme, NodeType.CONCEPT, node_id=concept_id, source="publish_feedback")
            from taste_graph_ai.domain.enums import RelationType
            ns_id = "concept:north_star"
            if ns_id in graph:
                try:
                    if graph.has_edge(ns_id, concept_id):
                        graph.adjust_weight(ns_id, concept_id, delta)
                    else:
                        graph.add_edge(ns_id, concept_id,
                                     RelationType.PREFERS if delta > 0 else RelationType.AVOIDS,
                                     weight=abs(delta))
                except Exception:
                    pass

        container.save_graph()

    event_log.append("feedback.publish_metrics", {
        "pack_id": pack_id,
        "theme": theme,
        "likes": likes,
        "saves": saves,
        "comments": comments,
        "engagement_score": score,
        "delta": delta,
    })

    await db.close()
    return {
        "pack_id": pack_id,
        "theme": theme,
        "engagement_score": score,
        "label": label,
        "delta": delta,
        "affected_images": len(affected_images),
        "record_id": record_id,
    }


async def generate_weekly_report() -> dict:
    """生成本周发布效果周报：什么管用、什么不行、建议方向。"""
    db = await get_db()
    publish_repo = PublishHistoryRepository(db)
    pack_repo = PackRepository(db)

    # 最近 7 天
    recent = await publish_repo.list_recent(50)

    if not recent:
        await db.close()
        return {"message": "暂无发布数据。先手动发布并录入互动数据。", "top_concepts": [], "top_sources": [], "suggestions": []}

    # 分类统计
    high_performers = [r for r in recent if r.get("engagement_rate", 0) >= 5]
    low_performers = [r for r in recent if r.get("engagement_rate", 0) < 1]
    all_scored = [r for r in recent if r.get("engagement_rate", 0) > 0]

    avg_engagement = (
        sum(r["engagement_rate"] for r in all_scored) / len(all_scored)
        if all_scored else 0
    )

    # 按 theme 聚合
    theme_stats = {}
    for r in recent:
        theme = r.get("theme", "未命名")
        if theme not in theme_stats:
            theme_stats[theme] = {"count": 0, "total_score": 0, "likes": 0, "saves": 0}
        theme_stats[theme]["count"] += 1
        theme_stats[theme]["total_score"] += r.get("engagement_rate", 0)
        theme_stats[theme]["likes"] += r.get("likes", 0)
        theme_stats[theme]["saves"] += r.get("saves", 0)

    top_themes = sorted(
        [{"theme": k, "avg_score": round(v["total_score"] / max(v["count"], 1), 2),
          "count": v["count"], "total_likes": v["likes"], "total_saves": v["saves"]}
         for k, v in theme_stats.items()],
        key=lambda x: x["avg_score"], reverse=True
    )[:5]

    # 生成 AI 建议方向
    suggestions = []
    if high_performers:
        high_themes = list(set(r.get("theme", "") for r in high_performers))
        suggestions.append(f"✅ 高强度方向（继续做）：{', '.join(high_themes[:5])}")
    if low_performers:
        low_themes = list(set(r.get("theme", "") for r in low_performers))
        suggestions.append(f"⚠️ 低互动方向（调整或放弃）：{', '.join(low_themes[:5])}")
    if avg_engagement > 0:
        if avg_engagement < 2:
            suggestions.append("📊 整体互动偏低，建议：换标题风格、尝试更具体的选题（物件/材质而非 mood）、加互动话术")
        elif avg_engagement < 5:
            suggestions.append("📊 整体互动中等，建议：强化一种固定栏目感（如「每周3件」），读者知道你下次会发什么")
        else:
            suggestions.append("📊 整体互动不错，建议：固定发布节奏，尝试小产品/PDF/Zine 方向变现")

    if len(recent) < 7:
        suggestions.append("🗓 发布频率偏低，建议每周至少 3 篇保持账号活跃")

    await db.close()
    return {
        "period": f"最近 7 天（共 {len(recent)} 条数据）",
        "avg_engagement": round(avg_engagement, 2),
        "high_performers_count": len(high_performers),
        "low_performers_count": len(low_performers),
        "top_themes": top_themes,
        "suggestions": suggestions,
    }


async def batch_record(entries: list[dict]) -> list[dict]:
    """批量录入互动数据。

    entries: [{"pack_id": "xxx", "likes": 10, "saves": 3, "comments": 2, "shares": 0, "post_url": ""}]
    """
    results = []
    for entry in entries:
        result = await record_publish_metrics(
            pack_id=entry.get("pack_id", ""),
            likes=entry.get("likes", 0),
            saves=entry.get("saves", 0),
            comments=entry.get("comments", 0),
            shares=entry.get("shares", 0),
            post_url=entry.get("post_url", ""),
        )
        results.append(result)
    return results


# ── CLI ─────────────────────────────────────────────────────────

async def cli_report():
    """命令行周报。"""
    import asyncio
    report = await generate_weekly_report()
    print("\n" + "=" * 50)
    print("📊 发布效果周报")
    print("=" * 50)
    print(f"\n{report.get('period', '')}")
    print(f"平均互动分: {report.get('avg_engagement', 0)}/10")
    print(f"🔥 高强度帖: {report.get('high_performers_count', 0)} 篇")
    print(f"❄️ 低互动帖: {report.get('low_performers_count', 0)} 篇")

    top = report.get("top_themes", [])
    if top:
        print("\n🏆 Top 主题:")
        for t in top:
            bar = "█" * int(t["avg_score"])
            print(f"  {t['avg_score']:.1f} {bar} {t['theme']}（{t['count']}篇, {t['total_likes']}赞 {t['total_saves']}藏）")

    suggestions = report.get("suggestions", [])
    if suggestions:
        print("\n💡 建议:")
        for s in suggestions:
            print(f"  {s}")

    print("=" * 50)


async def cli_record():
    """交互式录入。"""
    print("\n📝 录入小红书帖子互动数据")
    print("（从小红书创作者后台 / 笔记数据 查看）\n")

    pack_id = input("Pack ID（在 QUEUE.html 或 DB 里查）: ").strip()
    if not pack_id:
        print("❌ pack_id 不能为空")
        return

    likes = int(input("❤️ 点赞数: ").strip() or "0")
    saves = int(input("⭐ 收藏数: ").strip() or "0")
    comments = int(input("💬 评论数: ").strip() or "0")
    shares = int(input("🔄 分享数: ").strip() or "0")

    result = await record_publish_metrics(
        pack_id=pack_id,
        likes=likes,
        saves=saves,
        comments=comments,
        shares=shares,
    )

    print(f"\n✅ 录入完成!")
    print(f"   互动分: {result['engagement_score']}/10 ({result['label']})")
    print(f"   图谱调权: {result['delta']:+d}")
    print(f"   影响图片: {result['affected_images']} 张")


if __name__ == "__main__":
    import asyncio
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "report":
        asyncio.run(cli_report())
    elif len(sys.argv) > 1 and sys.argv[1] == "record":
        asyncio.run(cli_record())
    else:
        print("Usage:")
        print("  python scripts/publish_feedback.py report   # 查看周报")
        print("  python scripts/publish_feedback.py record   # 录入互动数据")
