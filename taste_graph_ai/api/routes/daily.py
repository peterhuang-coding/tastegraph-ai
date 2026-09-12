import uuid
from pathlib import Path
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

async def _require_editorial_approval(pack_id, db):
    table = await (await db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pack_editorial'")).fetchone()
    review = await (await db.execute("SELECT status FROM pack_editorial WHERE pack_id=?", (pack_id,))).fetchone() if table else None
    if not review or review[0] != "approved":
        raise HTTPException(409, "请先在 /editorial.html 完成命题、角色与顺序审核")


class ManualPublicationEvidence(schemas.PackPublishRequest):
    publication_status: str = "unknown"
    published_at: str | None = None
    observed_at: str | None = None



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
    await _require_editorial_approval(pack_id, pack_repo.db)
    if pack.status.value == "published":
        raise HTTPException(409, "已发布图集保留原记录；请到 /editorial.html 查看")
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
    # A group decision cannot rewrite platform history or become image taste.
    submitted = pack.status.value == "published"
    if not submitted:
        history = await (await pack_repo.db.execute(
            "SELECT 1 FROM publish_history WHERE pack_id=? LIMIT 1", (pack_id,),
        )).fetchone()
        submitted = bool(history)
    table = await (await pack_repo.db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_observations'",
    )).fetchone()
    if table and not submitted:
        observation = await (await pack_repo.db.execute(
            "SELECT 1 FROM publication_observations WHERE pack_id=? AND "
            "publication_status IN ('under_review','published','removed','rejected') LIMIT 1",
            (pack_id,),
        )).fetchone()
        submitted = bool(observation)
    if submitted:
        raise HTTPException(409, "已提交或已发布图集保留原记录；请到 /editorial.html 查看")
    from taste_graph_ai.config import DB_FILE
    from taste_graph_ai.services.editorial import get_pack_review, save_pack_review
    current = get_pack_review(DB_FILE, pack_id)
    try:
        save_pack_review(DB_FILE, pack_id, {**current, "status": "rejected"}, actor="operator")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    event_log.append("pack.editorial_rejected", {
        "pack_id": pack_id, "theme": pack.theme, "evidence_type": "editorial_decision",
    })
    return {"status": "ok", "editorial_status": "rejected"}


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


@router.post("/{pack_id}/export", response_model=schemas.ExportResponse)
async def export_pack(
    pack_id: str,
    pack_repo: PackRepository = Depends(get_pack_repo),
):
    pack = await pack_repo.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    await _require_editorial_approval(pack_id, pack_repo.db)
    from taste_graph_ai.api.routes import editorial
    from taste_graph_ai.config import EXPORTS_DIR
    import zipfile
    # Delegate ordering, review checks and original-file preservation to the
    # reviewed export. ZIP retains the old downloadable URL response contract.
    result = editorial.export(pack_id)
    folder = editorial.BASE_DIR / result["pack_path"]
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = EXPORTS_DIR / (folder.name + ".zip")
    if not output_path.exists():
        import tempfile
        import os
        descriptor, staged = tempfile.mkstemp(prefix=".reviewed-", suffix=".zip", dir=EXPORTS_DIR)
        os.close(descriptor)
        try:
            with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for file in sorted(folder.iterdir()):
                    if file.is_file():
                        bundle.write(file, arcname=file.name)
            os.replace(staged, output_path)
        finally:
            Path(staged).unlink(missing_ok=True)
    return schemas.ExportResponse(pack_id=pack_id, filename=output_path.name,
        url=f"/exports/{output_path.name}", theme=pack.theme, caption=pack.caption)


@router.post("/{pack_id}/publish")
async def publish_pack(
    pack_id: str,
    body: ManualPublicationEvidence,
    pack_repo: PackRepository = Depends(get_pack_repo),
    publish_repo: PublishHistoryRepository = Depends(get_publish_repo),
    event_log: EventLog = Depends(get_event_log),
):
    pack = await pack_repo.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    status = getattr(body, "publication_status", "unknown")
    published_at = getattr(body, "published_at", None)
    observed_at = getattr(body, "observed_at", None)
    if status not in {"published", "under_review", "rejected", "removed"}:
        raise HTTPException(400, "请明确实际发布状态与证据时间；不会自动使用当前时间")
    required_time = published_at if status == "published" else observed_at
    if required_time in (None, "", "unknown"):
        raise HTTPException(400, "已发布记录需要实际发布时间；其他状态需要实际观测时间")
    from taste_graph_ai.services.publication_records import record_publication_observation
    try:
        observation = await record_publication_observation(pack_repo.db, pack_id, {
            "platform": body.platform, "post_url": body.post_url,
            "publication_status": status, "published_at": published_at,
            "observed_at": observed_at, "source": "legacy_manual_registration",
            "observation_key": "manual_registration",
        }, score=0)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if observation["inserted"]:
        event_log.append("pack.publication_observed", {
            "pack_id": pack_id, "platform": body.platform,
            "publication_status": status, "record_id": observation["record_id"],
        })
    return {"status": "ok", "record_id": observation["record_id"],
            "publication_status": status, "duplicate": not observation["inserted"]}


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


@router.post("/{pack_id}/auto-publish", response_model=schemas.AutoPublishResponse)
async def auto_publish_pack(
    pack_id: str,
    pack_repo: PackRepository = Depends(get_pack_repo),
    publish_repo: PublishHistoryRepository = Depends(get_publish_repo),
    event_log: EventLog = Depends(get_event_log),
):
    raise HTTPException(405, "自动发布已禁用。请在 /editorial.html 审核并导出后手工发布，再登记实际状态。")
