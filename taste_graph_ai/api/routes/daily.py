import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from taste_graph_ai.api import schemas
from taste_graph_ai.api.deps import (
    get_pack_repo,
    get_task_repo,
    get_feedback_repo,
    get_feedback_service,
    get_event_log,
    get_publish_repo,
    get_image_repo,
)
from taste_graph_ai.domain.enums import FeedbackLabel, FeedbackTargetType, ImageStatus, UserAction
from taste_graph_ai.domain.models import PackImage, PublishRecord
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.tasks import TaskRepository
from taste_graph_ai.infrastructure.repos.feedback import FeedbackRepository
from taste_graph_ai.infrastructure.repos.publish_history import PublishHistoryRepository
from taste_graph_ai.infrastructure.repos.images import ImageRepository
from taste_graph_ai.infrastructure.db.event_log import EventLog
from modules.xhs_publisher.composer import MoodboardComposer
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
    image_repo: ImageRepository = Depends(get_image_repo),
    event_log: EventLog = Depends(get_event_log),
):
    pack = await pack_repo.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    pack.reject()
    await pack_repo.save(pack)

    # Release images back to the pending pool
    images = await pack_repo.get_pack_images(pack_id)
    if images:
        await image_repo.mark_many_status(
            [img["id"] for img in images], ImageStatus.PENDING
        )

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
    image_repo: ImageRepository = Depends(get_image_repo),
    event_log: EventLog = Depends(get_event_log),
):
    # 契约 §1 PackImage：换图原子同步 pack_images 的真实 image_id/位置/来源。
    # 旧图标记 replaced，新图标记 selected；图注由前端随选图同步。
    rows = await pack_repo.find_pack_images_by_image(image_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Image not referenced by any pack")

    affected = []
    for row in rows:
        conflict = await pack_repo.get_pack_image(row["pack_id"], body.new_image_id)
        if conflict and conflict["position"] != row["position"]:
            raise HTTPException(
                status_code=409,
                detail=f"新图已在 pack {row['pack_id']} 的第 {conflict['position']} 位",
            )
        affected.append(row["pack_id"])

    for row in rows:
        await pack_repo.save_pack_image(PackImage(
            pack_id=row["pack_id"],
            image_id=body.new_image_id,
            position=row["position"],
            user_action=UserAction.REPLACED,
        ))
        await pack_repo.delete_pack_image(row["pack_id"], image_id)

    await image_repo.mark_many_status([image_id], ImageStatus.REPLACED)
    await image_repo.mark_many_status([body.new_image_id], ImageStatus.SELECTED)

    event_log.append("image.replaced", {
        "old_image_id": image_id,
        "new_image_id": body.new_image_id,
        "affected_packs": affected,
    })
    return {"status": "ok", "new_image_id": body.new_image_id, "affected_packs": affected}


@router.post("/{pack_id}/export", response_model=schemas.ExportResponse)
async def export_pack(
    pack_id: str,
    pack_repo: PackRepository = Depends(get_pack_repo),
):
    pack = await pack_repo.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    images = await pack_repo.get_pack_images(pack_id)
    if not images:
        raise HTTPException(status_code=400, detail="No images in pack")

    image_paths = [img["local_path"] for img in images if img.get("local_path")]
    if not image_paths:
        raise HTTPException(status_code=400, detail="No local images available")

    composer = MoodboardComposer()
    title = pack.title_options[0] if pack.title_options else pack.theme
    output_path = composer.compose(
        image_paths=image_paths,
        theme=pack.theme,
        caption=pack.caption,
        title=title,
    )

    return schemas.ExportResponse(
        pack_id=pack_id,
        filename=output_path.name,
        url=f"/exports/{output_path.name}",
        theme=pack.theme,
        caption=pack.caption,
    )


@router.post("/{pack_id}/publish")
async def publish_pack(
    pack_id: str,
    body: schemas.PackPublishRequest,
    pack_repo: PackRepository = Depends(get_pack_repo),
    publish_repo: PublishHistoryRepository = Depends(get_publish_repo),
    event_log: EventLog = Depends(get_event_log),
):
    pack = await pack_repo.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    pack.publish()
    await pack_repo.save(pack)

    now = datetime.now(timezone.utc).isoformat()
    record = PublishRecord(
        id=uuid.uuid4().hex[:12],
        pack_id=pack_id,
        published_at=now,
        platform=body.platform,
        post_url=body.post_url,
    )
    await publish_repo.save(record)

    event_log.append("pack.published", {
        "pack_id": pack_id,
        "platform": body.platform,
        "post_url": body.post_url,
        "publish_record_id": record.id,
    })
    return {"status": "ok"}


@router.post("/{pack_id}/auto-publish", response_model=schemas.AutoPublishResponse)
async def auto_publish_pack(
    pack_id: str,
    pack_repo: PackRepository = Depends(get_pack_repo),
    publish_repo: PublishHistoryRepository = Depends(get_publish_repo),
    event_log: EventLog = Depends(get_event_log),
):
    # LEGACY / DISABLED — 老板于 2026-07-29 关停全部 XHS 自动发布（账号封禁）。
    # 工作台按钮已移除（2026-09-08）；此端点保留占位，任何调用一律拒绝，
    # 防止旧脚本/缓存页面误触发真实发布。
    raise HTTPException(
        status_code=403,
        detail="自动发布已永久禁用（2026-07-29 老板关停）。请在工作台导出发布包后人工发布。",
    )


def _pack_to_response(pack, images: list[dict]) -> schemas.DailyPackResponse:
    from pathlib import Path
    enriched = []
    for img in images:
        local = img.get("local_path", "")
        if local:
            fname = Path(local).name
            img["image_url"] = f"/images/{fname}"
        else:
            img["image_url"] = ""
        enriched.append(img)
    return schemas.DailyPackResponse(
        id=pack.id,
        date=pack.date,
        theme=pack.theme,
        why_today=pack.why_today,
        title_options=pack.title_options,
        caption=pack.caption,
        taste_score=pack.taste_score,
        status=pack.status.value,
        images=[schemas.PackImageResponse(**img) for img in enriched],
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
