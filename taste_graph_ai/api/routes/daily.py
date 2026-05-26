from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from taste_graph_ai.api import schemas
from taste_graph_ai.api.deps import (
    get_pack_repo,
    get_task_repo,
    get_feedback_repo,
    get_feedback_service,
    get_event_log,
)
from taste_graph_ai.domain.enums import FeedbackLabel, FeedbackTargetType
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.tasks import TaskRepository
from taste_graph_ai.infrastructure.repos.feedback import FeedbackRepository
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.services.feedback import FeedbackService

router = APIRouter(prefix="/api/v1/daily", tags=["daily"])


@router.get("/today", response_model=schemas.DailyTodayResponse)
async def get_today(
    pack_repo: PackRepository = Depends(get_pack_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
):
    today = date.today().isoformat()
    packs = await pack_repo.get_today_packs(today)
    tasks = await task_repo.list_today(today)

    pack_responses = []
    for p in packs:
        images = await pack_repo.get_pack_images(p.id)
        pack_responses.append(_pack_to_response(p, images))

    return schemas.DailyTodayResponse(
        packs=pack_responses,
        tasks=[_task_to_response(t) for t in tasks],
    )


@router.get("/{pack_id}", response_model=schemas.DailyPackResponse)
async def get_pack(
    pack_id: str,
    pack_repo: PackRepository = Depends(get_pack_repo),
):
    pack = await pack_repo.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    images = await pack_repo.get_pack_images(pack_id)
    return _pack_to_response(pack, images)


@router.post("/{pack_id}/select", response_model=schemas.DailyPackResponse)
async def select_pack(
    pack_id: str,
    pack_repo: PackRepository = Depends(get_pack_repo),
    event_log: EventLog = Depends(get_event_log),
):
    pack = await pack_repo.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    pack.select()
    await pack_repo.save(pack)
    event_log.append("pack.selected", {"pack_id": pack_id, "theme": pack.theme})
    images = await pack_repo.get_pack_images(pack_id)
    return _pack_to_response(pack, images)


@router.post("/{pack_id}/reject")
async def reject_pack(
    pack_id: str,
    pack_repo: PackRepository = Depends(get_pack_repo),
    event_log: EventLog = Depends(get_event_log),
):
    pack = await pack_repo.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    pack.reject()
    await pack_repo.save(pack)
    event_log.append("pack.rejected", {"pack_id": pack_id, "theme": pack.theme})
    return {"status": "ok"}


@router.post("/images/{image_id}/feedback")
async def image_feedback(
    image_id: str,
    body: schemas.ImageFeedbackRequest,
    feedback_repo: FeedbackRepository = Depends(get_feedback_repo),
    event_log: EventLog = Depends(get_event_log),
    feedback_service: FeedbackService = Depends(get_feedback_service),
):
    label = FeedbackLabel(body.label)
    fb = await feedback_service.record(
        target_type=FeedbackTargetType.IMAGE,
        target_id=image_id,
        label=label,
        note=body.note,
    )
    return {"status": "ok", "feedback_id": fb.id}


@router.post("/images/{image_id}/replace")
async def replace_image(
    image_id: str,
    body: schemas.ImageReplaceRequest,
    pack_repo: PackRepository = Depends(get_pack_repo),
    event_log: EventLog = Depends(get_event_log),
):
    event_log.append("image.replaced", {
        "old_image_id": image_id,
        "new_image_id": body.new_image_id,
    })
    return {"status": "ok", "new_image_id": body.new_image_id}


@router.post("/{pack_id}/publish")
async def publish_pack(
    pack_id: str,
    body: schemas.PackPublishRequest,
    pack_repo: PackRepository = Depends(get_pack_repo),
    event_log: EventLog = Depends(get_event_log),
):
    pack = await pack_repo.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    pack.publish()
    await pack_repo.save(pack)
    event_log.append("pack.published", {
        "pack_id": pack_id,
        "platform": body.platform,
        "post_url": body.post_url,
    })
    return {"status": "ok"}


def _pack_to_response(pack, images: list[dict]) -> schemas.DailyPackResponse:
    return schemas.DailyPackResponse(
        id=pack.id,
        date=pack.date,
        theme=pack.theme,
        why_today=pack.why_today,
        title_options=pack.title_options,
        caption=pack.caption,
        taste_score=pack.taste_score,
        status=pack.status.value,
        images=[schemas.PackImageResponse(**img) for img in images],
        created_at=pack.created_at,
        selected_at=pack.selected_at,
    )


def _task_to_response(task) -> schemas.TaskResponse:
    return schemas.TaskResponse(
        id=task.id,
        task_type=task.task_type.value,
        title=task.title,
        body=task.body,
        priority=task.priority.value,
        action_url=task.action_url,
        status=task.status.value,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )
