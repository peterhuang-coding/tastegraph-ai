"""Publish feedback API — 手动录入互动数据 + 周报。

POST /api/v1/feedback/publish-metrics  — 录入单帖互动数据
POST /api/v1/feedback/batch-metrics    — 批量录入
GET  /api/v1/feedback/weekly-report    — 获取本周「什么管用」报告

All DB operations use server's injected connections — no separate DB open.
"""

import math
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from taste_graph_ai.api import schemas as api_schemas
from taste_graph_ai.api.deps import (
    get_pack_repo, get_publish_repo, get_event_log,
    get_feedback_repo, get_feedback_service,
)
from taste_graph_ai.container import get_container
from taste_graph_ai.domain.enums import (
    FeedbackLabel, FeedbackTargetType, NodeType, RelationType,
)
from taste_graph_ai.domain.models import PublishRecord
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.publish_history import PublishHistoryRepository
from taste_graph_ai.infrastructure.repos.feedback import FeedbackRepository
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.services.feedback import FeedbackService

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


# ── Schemas ─────────────────────────────────────────────────────

class PublishMetricsRequest(api_schemas.BaseModel):
    pack_id: str
    likes: int = 0
    saves: int = 0
    comments: int = 0
    shares: int = 0
    post_url: str = ""


class BatchMetricsRequest(api_schemas.BaseModel):
    entries: list[PublishMetricsRequest]


class WeeklyReportResponse(api_schemas.BaseModel):
    period: str = ""
    avg_engagement: float = 0.0
    high_performers_count: int = 0
    low_performers_count: int = 0
    top_themes: list[dict] = []
    suggestions: list[str] = []
    message: str = ""


class PublishMetricsResponse(api_schemas.BaseModel):
    pack_id: str
    theme: str = ""
    engagement_score: float = 0.0
    label: str = ""
    delta: int = 0
    affected_images: int = 0
    record_id: str = ""


# ── Engagement scoring ──────────────────────────────────────────

ENGAGEMENT_WEIGHTS = {
    "save": 3.0,
    "comment": 2.0,
    "like": 1.0,
    "share": 4.0,
}


def compute_engagement_score(likes: int, saves: int, comments: int, shares: int = 0) -> float:
    weighted = (
        likes * ENGAGEMENT_WEIGHTS["like"]
        + saves * ENGAGEMENT_WEIGHTS["save"]
        + comments * ENGAGEMENT_WEIGHTS["comment"]
        + shares * ENGAGEMENT_WEIGHTS["share"]
    )
    if weighted <= 0:
        return 0.0
    raw = math.log(weighted + 1) * 2.5
    return round(min(10.0, max(0.0, raw)), 2)


def engagement_label(score: float) -> str:
    if score >= 7:
        return "爆款级"
    elif score >= 5:
        return "不错"
    elif score >= 3:
        return "一般"
    elif score >= 1:
        return "偏低"
    return "无互动"


# ── Routes ──────────────────────────────────────────────────────

@router.post("/publish-metrics", response_model=PublishMetricsResponse)
async def record_publish_metrics(
    body: PublishMetricsRequest,
    pack_repo: PackRepository = Depends(get_pack_repo),
    publish_repo: PublishHistoryRepository = Depends(get_publish_repo),
    feedback_repo: FeedbackRepository = Depends(get_feedback_repo),
    feedback_service: FeedbackService = Depends(get_feedback_service),
    event_log: EventLog = Depends(get_event_log),
):
    """录入单篇帖子的互动数据，自动回灌 taste graph 调整权重。"""
    pack = await pack_repo.get_by_id(body.pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail=f"Pack {body.pack_id} 不存在。先生成 publish pack。")

    score = compute_engagement_score(body.likes, body.saves, body.comments, body.shares)
    label = engagement_label(score)
    now = datetime.now(timezone.utc).isoformat()

    # Upsert publish record
    existing = await publish_repo.get_by_pack_id(body.pack_id)
    if existing:
        record_id = existing["id"]
        # Update via raw SQL through pack_repo's db
        await pack_repo.db.execute(
            """UPDATE publish_history
            SET likes=?, saves=?, comments=?, engagement_rate=?
            WHERE id=?""",
            (body.likes, body.saves, body.comments, score, record_id),
        )
        await pack_repo.db.commit()
    else:
        record_id = uuid.uuid4().hex[:12]
        record = PublishRecord(
            id=record_id,
            pack_id=body.pack_id,
            published_at=now,
            platform="xiaohongshu",
            post_url=body.post_url,
            likes=body.likes,
            saves=body.saves,
            comments=body.comments,
            engagement_rate=score,
        )
        await publish_repo.save(record)

    # Feed back to taste graph (high/low engagement only)
    delta = 0
    feedback_label = None
    if score >= 5:
        delta = +2
        feedback_label = FeedbackLabel.DUI_WEI
    elif score < 1:
        delta = -2
        feedback_label = FeedbackLabel.BU_DUI_WEI

    affected = 0
    if delta != 0:
        container = get_container()
        graph = container.taste_graph

        # Adjust pack images' concept weights
        images = await pack_repo.get_pack_images(body.pack_id)
        for img in images:
            img_id = img["image_id"]
            affected += 1
            if feedback_label:
                try:
                    await feedback_service.record(
                        target_type=FeedbackTargetType.IMAGE,
                        target_id=img_id,
                        label=feedback_label,
                        note=f"发布反馈: engagement={score} ({label}), likes={body.likes} saves={body.saves}",
                    )
                except Exception:
                    pass

        # Adjust theme concept weight
        theme = pack.theme
        if theme:
            concept_id = f"concept:{theme.lower().replace(' ', '_')}"
            if concept_id not in graph:
                graph.add_node(theme, NodeType.CONCEPT, node_id=concept_id, source="publish_feedback")
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
        "pack_id": body.pack_id,
        "theme": pack.theme,
        "engagement_score": score,
        "delta": delta,
    })

    return {
        "pack_id": body.pack_id,
        "theme": pack.theme,
        "engagement_score": score,
        "label": label,
        "delta": delta,
        "affected_images": affected,
        "record_id": record_id,
    }


@router.post("/batch-metrics", response_model=list[PublishMetricsResponse])
async def batch_record_metrics(
    body: BatchMetricsRequest,
    pack_repo: PackRepository = Depends(get_pack_repo),
    publish_repo: PublishHistoryRepository = Depends(get_publish_repo),
    feedback_repo: FeedbackRepository = Depends(get_feedback_repo),
    feedback_service: FeedbackService = Depends(get_feedback_service),
    event_log: EventLog = Depends(get_event_log),
):
    """批量录入互动数据。"""
    results = []
    for entry in body.entries:
        # Reuse the single-record logic
        try:
            r = await record_publish_metrics(
                body=entry,
                pack_repo=pack_repo,
                publish_repo=publish_repo,
                feedback_repo=feedback_repo,
                feedback_service=feedback_service,
                event_log=event_log,
            )
        except HTTPException:
            r = {"pack_id": entry.pack_id, "theme": "", "engagement_score": 0.0,
                 "label": "error", "delta": 0, "affected_images": 0, "record_id": ""}
        results.append(r)
    return results


@router.get("/weekly-report", response_model=WeeklyReportResponse)
async def get_weekly_report(
    publish_repo: PublishHistoryRepository = Depends(get_publish_repo),
):
    """获取本周发布效果报告。"""
    recent = await publish_repo.list_recent(50)

    if not recent:
        return {"message": "暂无发布数据。先手动发布并录入互动数据。", "top_themes": [], "suggestions": []}

    high = [r for r in recent if r.get("engagement_rate", 0) >= 5]
    low = [r for r in recent if r.get("engagement_rate", 0) < 1]
    all_scored = [r for r in recent if r.get("engagement_rate", 0) > 0]
    avg_eng = sum(r["engagement_rate"] for r in all_scored) / len(all_scored) if all_scored else 0

    # By theme
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

    suggestions = []
    if high:
        high_themes = list(set(r.get("theme", "") for r in high))
        suggestions.append(f"✅ 高强度方向（继续做）：{', '.join(high_themes[:5])}")
    if low:
        low_themes = list(set(r.get("theme", "") for r in low))
        suggestions.append(f"⚠️ 低互动方向（调整或放弃）：{', '.join(low_themes[:5])}")
    if avg_eng > 0:
        if avg_eng < 2:
            suggestions.append("📊 整体互动偏低，建议：换标题风格、尝试更具体的选题（物件/材质而非 mood）、加互动话术")
        elif avg_eng < 5:
            suggestions.append("📊 整体互动中等，建议：强化一种固定栏目感（如「每周3件」），读者知道你下次会发什么")
        else:
            suggestions.append("📊 整体互动不错，建议：固定发布节奏，尝试小产品/PDF/Zine 方向变现")
    if len(recent) < 7:
        suggestions.append("🗓 发布频率偏低，建议每周至少 3 篇保持账号活跃")

    return {
        "period": f"最近 7 天（共 {len(recent)} 条数据）",
        "avg_engagement": round(avg_eng, 2),
        "high_performers_count": len(high),
        "low_performers_count": len(low),
        "top_themes": top_themes,
        "suggestions": suggestions,
        "message": "",
    }
