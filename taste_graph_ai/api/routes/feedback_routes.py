"""Publish feedback API — 手动录入互动数据 + 周报。

POST /api/v1/feedback/publish-metrics  — 录入单帖互动数据
POST /api/v1/feedback/batch-metrics    — 批量录入
GET  /api/v1/feedback/weekly-report    — 获取本周「什么管用」报告

All DB operations use server's injected connections — no separate DB open.
"""

import math
import uuid
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

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


class WeeklySummaryResponse(api_schemas.BaseModel):
    """Current week 4-KPI snapshot for the weekly dashboard.

    Why a separate endpoint: weekly-report returns aggregate themes + suggestions,
    not the numeric KPIs the dashboard cards need (publish_count, total_reach,
    total_interactions, avg_engagement). Keeping summary as a focused 4-number
    payload lets the UI render KPIs without parsing themes.
    """
    week_start: str = ""
    week_end: str = ""
    publish_count: int = 0
    total_reach: int = 0            # proxy: sum(likes) * 8 (DB has no impressions)
    total_interactions: int = 0     # likes + saves + comments
    avg_engagement: float = 0.0     # 0-10 score (engagement_rate)
    reach_is_estimate: bool = True
    message: str = ""


class WeeklyTrendWeek(api_schemas.BaseModel):
    week_start: str = ""
    week_label: str = ""           # e.g. "W31"
    publish_count: int = 0
    avg_engagement: float = 0.0


class WeeklyTrendResponse(api_schemas.BaseModel):
    """Multi-week trend for bar charts (publish count + avg engagement per week).

    Why separate from weekly-report: report returns only a 7-day window; the
    dashboard needs N weeks of bucketed data to render sparkline/bar charts.
    Aggregated in Python to keep SQL portable.
    """
    weeks: int = 0
    series: list[WeeklyTrendWeek] = []


class TopPostItem(api_schemas.BaseModel):
    id: str
    pack_id: str
    theme: str = ""
    published_at: str = ""
    platform: str = ""
    post_url: str = ""
    likes: int = 0
    saves: int = 0
    comments: int = 0
    engagement_rate: float = 0.0
    total_interactions: int = 0


class TopPostsResponse(api_schemas.BaseModel):
    """Top N posts by engagement score for the dashboard table.

    Why separate from weekly-report: report returns aggregate themes, not
    individual post rows. Frontend table needs the raw post detail.
    """
    limit: int = 0
    posts: list[TopPostItem] = []


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


# ── Weekly dashboard helpers ──────────────────────────────────

def _parse_iso(dt_str: str) -> datetime:
    """Parse ISO timestamp from publish_history; tolerate trailing Z."""
    if not dt_str:
        return datetime.now(timezone.utc)
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        return datetime.fromisoformat(dt_str)
    except Exception:
        return datetime.now(timezone.utc)


def _week_start_utc(dt: datetime) -> datetime:
    """Return Monday 00:00 UTC of dt's week (ISO week)."""
    dt = dt.astimezone(timezone.utc)
    monday = dt - timedelta(days=dt.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/weekly-summary", response_model=WeeklySummaryResponse)
async def get_weekly_summary(
    publish_repo: PublishHistoryRepository = Depends(get_publish_repo),
):
    """本周（周一至今）4 KPI：发布数 / 曝光估算 / 总互动 / 平均互动率。

    Why needed: weekly-report 返回的是 themes+suggestions 聚合，没有当前周的
    4 个数字 KPI。KPI 卡片需要这些纯数字，避免前端解析 themes。

    Reach 是估算（DB 没有 impressions 字段）= sum(likes) * 8，
    这是 XHS 公开数据中典型的曝光/点赞比。响应里 reach_is_estimate=True。
    """
    recent = await publish_repo.list_recent(500)

    now = datetime.now(timezone.utc)
    week_start_dt = _week_start_utc(now)
    week_end_dt = now

    week_records = []
    for r in recent:
        published = _parse_iso(r.get("published_at", ""))
        if published >= week_start_dt:
            week_records.append(r)

    if not week_records:
        return {
            "week_start": week_start_dt.isoformat(),
            "week_end": week_end_dt.isoformat(),
            "publish_count": 0,
            "total_reach": 0,
            "total_interactions": 0,
            "avg_engagement": 0.0,
            "reach_is_estimate": True,
            "message": "本周暂无发布数据。先去「发布历史」录入本周互动数据。",
        }

    total_likes = sum(r.get("likes", 0) for r in week_records)
    total_saves = sum(r.get("saves", 0) for r in week_records)
    total_comments = sum(r.get("comments", 0) for r in week_records)
    total_interactions = total_likes + total_saves + total_comments

    # Reach proxy: DB 无 impressions，按 XHS 公开数据曝光/点赞比 ≈ 8x
    total_reach = total_likes * 8

    scored = [r.get("engagement_rate", 0) for r in week_records if r.get("engagement_rate", 0) > 0]
    avg_engagement = round(sum(scored) / len(scored), 2) if scored else 0.0

    return {
        "week_start": week_start_dt.isoformat(),
        "week_end": week_end_dt.isoformat(),
        "publish_count": len(week_records),
        "total_reach": total_reach,
        "total_interactions": total_interactions,
        "avg_engagement": avg_engagement,
        "reach_is_estimate": True,
        "message": "",
    }


@router.get("/weekly-trend", response_model=WeeklyTrendResponse)
async def get_weekly_trend(
    weeks: int = Query(8, ge=1, le=52),
    publish_repo: PublishHistoryRepository = Depends(get_publish_repo),
):
    """过去 N 周（默认 8）的发布数 + 平均互动率时间序列，用于柱状图。

    Why needed: weekly-report 只返回 7 天聚合，没有历史 bucket 数据。
    柱状图需要按 ISO 周分桶的多周数据。在 Python 层分桶以保证 SQL 兼容性。
    """
    now = datetime.now(timezone.utc)
    this_week_start = _week_start_utc(now)
    earliest = this_week_start - timedelta(weeks=weeks - 1)

    recent = await publish_repo.list_recent(1000)

    bucket_count: dict[datetime, int] = defaultdict(int)
    bucket_score_sum: dict[datetime, float] = defaultdict(float)
    bucket_score_n: dict[datetime, int] = defaultdict(int)

    for r in recent:
        published = _parse_iso(r.get("published_at", ""))
        ws = _week_start_utc(published)
        if ws < earliest or ws > this_week_start:
            continue
        bucket_count[ws] += 1
        score = r.get("engagement_rate", 0) or 0
        if score > 0:
            bucket_score_sum[ws] += score
            bucket_score_n[ws] += 1

    series = []
    for i in range(weeks):
        ws = earliest + timedelta(weeks=i)
        avg_eng = (
            round(bucket_score_sum[ws] / bucket_score_n[ws], 2)
            if bucket_score_n[ws] else 0.0
        )
        series.append({
            "week_start": ws.date().isoformat(),
            "week_label": f"W{ws.isocalendar()[1]}",
            "publish_count": bucket_count.get(ws, 0),
            "avg_engagement": avg_eng,
        })

    return {"weeks": weeks, "series": series}


@router.get("/top-posts", response_model=TopPostsResponse)
async def get_top_posts(
    limit: int = Query(10, ge=1, le=50),
    publish_repo: PublishHistoryRepository = Depends(get_publish_repo),
):
    """按 engagement_rate 排序的 Top N 帖子详情，用于周报表格。

    Why needed: weekly-report 只返回主题聚合，没有单帖行数据。
    Top 10 表格需要 pack_id/theme/url/likes/saves/comments 等明细。
    """
    recent = await publish_repo.list_recent(500)

    def _score(r: dict) -> float:
        return r.get("engagement_rate", 0) or 0

    sorted_records = sorted(recent, key=_score, reverse=True)[:limit]

    posts = []
    for r in sorted_records:
        posts.append({
            "id": r.get("id", ""),
            "pack_id": r.get("pack_id", ""),
            "theme": r.get("theme", "") or "未命名",
            "published_at": r.get("published_at", ""),
            "platform": r.get("platform", "") or "xiaohongshu",
            "post_url": r.get("post_url", "") or "",
            "likes": r.get("likes", 0),
            "saves": r.get("saves", 0),
            "comments": r.get("comments", 0),
            "engagement_rate": round(r.get("engagement_rate", 0) or 0, 2),
            "total_interactions": (
                r.get("likes", 0) + r.get("saves", 0) + r.get("comments", 0)
            ),
        })

    return {"limit": limit, "posts": posts}
