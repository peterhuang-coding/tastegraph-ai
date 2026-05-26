import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from taste_graph_ai.api import schemas
from taste_graph_ai.domain.enums import SourceStatus
from taste_graph_ai.infrastructure.repos.sources import SourceRepository
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.api.deps import get_source_repo, get_event_log

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


@router.get("/pending", response_model=list[schemas.SourceResponse])
async def list_pending(
    status: str = "pending",
    page: int = 0,
    limit: int = 50,
    repo: SourceRepository = Depends(get_source_repo),
):
    st = SourceStatus(status)
    return await repo.list_by_status(st, limit=limit, offset=page * limit)


@router.get("/stats", response_model=schemas.SourceStatsResponse)
async def source_stats(repo: SourceRepository = Depends(get_source_repo)):
    stats = await repo.stats()
    return schemas.SourceStatsResponse(
        pending=stats.get("pending", 0),
        approved=stats.get("approved", 0),
        rejected=stats.get("rejected", 0),
        deferred=stats.get("deferred", 0),
    )


@router.post("/{source_id}/approve", response_model=schemas.SourceResponse)
async def approve_source(
    source_id: str,
    body: schemas.SourceActionRequest = schemas.SourceActionRequest(),
    repo: SourceRepository = Depends(get_source_repo),
    event_log: EventLog = Depends(get_event_log),
):
    source = await repo.get_by_id(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.approve(body.note)
    await repo.save(source)
    event_log.append("source.approved", {"id": source_id, "url": source.url, "note": body.note})
    return _to_response(source)


@router.post("/{source_id}/reject", response_model=schemas.SourceResponse)
async def reject_source(
    source_id: str,
    body: schemas.SourceActionRequest = schemas.SourceActionRequest(),
    repo: SourceRepository = Depends(get_source_repo),
    event_log: EventLog = Depends(get_event_log),
):
    source = await repo.get_by_id(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.reject(body.note)
    await repo.save(source)
    event_log.append("source.rejected", {"id": source_id, "url": source.url, "reason": body.note})
    return _to_response(source)


@router.post("/{source_id}/defer", response_model=schemas.SourceResponse)
async def defer_source(
    source_id: str,
    repo: SourceRepository = Depends(get_source_repo),
    event_log: EventLog = Depends(get_event_log),
):
    source = await repo.get_by_id(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.defer()
    await repo.save(source)
    event_log.append("source.deferred", {"id": source_id, "url": source.url})
    return _to_response(source)


def _to_response(source) -> schemas.SourceResponse:
    return schemas.SourceResponse(
        id=source.id,
        url=source.url,
        name=source.name,
        source_type=source.source_type.value,
        discovered_from=source.discovered_from,
        preview_thumbnails=source.preview_thumbnails,
        ai_score=source.ai_score,
        ai_reason=source.ai_reason,
        ai_risk=source.ai_risk,
        status=source.status.value,
        reviewer_note=source.reviewer_note,
        created_at=source.created_at,
        reviewed_at=source.reviewed_at,
    )
