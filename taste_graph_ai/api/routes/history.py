import uuid
import json

from fastapi import APIRouter, Depends

from taste_graph_ai.api import schemas
from taste_graph_ai.api.deps import get_pack_repo
from taste_graph_ai.infrastructure.repos.packs import PackRepository

router = APIRouter(prefix="/api/v1/history", tags=["history"])


@router.get("/list", response_model=list[schemas.HistoryItemResponse])
async def list_history(
    page: int = 0,
    limit: int = 20,
    pack_repo: PackRepository = Depends(get_pack_repo),
):
    packs = await pack_repo.get_latest_packs(limit=limit)
    # Filter to published only
    published = [p for p in packs if p.status.value == "published"]
    return [
        schemas.HistoryItemResponse(
            id=uuid.uuid4().hex[:12],
            pack_id=p.id,
            published_at=p.published_at or p.created_at,
            platform="xiaohongshu",
            theme=p.theme,
        )
        for p in published
    ]


@router.get("/stats", response_model=schemas.HistoryStatsResponse)
async def get_stats(pack_repo: PackRepository = Depends(get_pack_repo)):
    packs = await pack_repo.get_latest_packs(limit=100)
    published = [p for p in packs if p.status.value == "published"]

    # Count themes
    theme_counts = {}
    for p in published:
        theme_counts[p.theme] = theme_counts.get(p.theme, 0) + 1

    top_themes = sorted(
        [{"name": k, "count": v} for k, v in theme_counts.items()],
        key=lambda x: x["count"], reverse=True,
    )[:5]

    return schemas.HistoryStatsResponse(
        total_published=len(published),
        avg_engagement=0.0,
        top_themes=top_themes,
        recent_trend="暂无足够数据",
    )
