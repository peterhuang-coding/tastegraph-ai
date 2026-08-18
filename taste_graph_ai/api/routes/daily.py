import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

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
from taste_graph_ai.domain.enums import FeedbackLabel, FeedbackTargetType, ImageStatus
from taste_graph_ai.domain.models import PublishRecord
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.tasks import TaskRepository
from taste_graph_ai.infrastructure.repos.feedback import FeedbackRepository
from taste_graph_ai.infrastructure.repos.publish_history import PublishHistoryRepository
from taste_graph_ai.infrastructure.repos.images import ImageRepository
from taste_graph_ai.infrastructure.db.event_log import EventLog
from modules.xhs_publisher.composer import MoodboardComposer
from taste_graph_ai.services.feedback import FeedbackService

router = APIRouter(prefix="/api/v1/daily", tags=["daily"])

# Project root: .../taste_graph_ai/api/routes/daily.py → 4 levels up
BASE_DIR = Path(__file__).resolve().parents[3]
POSTS_DIR = BASE_DIR / "posts"


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

    # Fallback: if SQLite has no packs for today, scan posts/{today}/post-*/
    # (generate_publish_packs.py writes to filesystem, not DB)
    if not pack_responses:
        pack_responses = _load_packs_from_filesystem(today)

    return schemas.DailyTodayResponse(
        packs=pack_responses,
        tasks=[_task_to_response(t) for t in tasks],
    )


@router.get("/file-pack/{date_str}/{pack_id}/image")
async def get_file_pack_image(date_str: str, pack_id: str):
    """Serve image.jpg for file-based packs (posts/{date}/{pack_id}/image.jpg)."""
    image_path = POSTS_DIR / date_str / pack_id / "image.jpg"
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Pack image not found")
    return FileResponse(image_path)


@router.get("/candidates")
async def get_candidates(date_str: str = ""):
    """Return today's 100 manual-post candidates.

    Reads from data/today_candidates_{date}.json (built offline by
    pick_100_candidates.py from the historical pool). The home page
    renders these as a checkbox grid; user picks 30 → server clusters
    via CLIP → 3 series × 10 → user picks 5/series → 15 to publish.

    Falls back to today's date if date_str is empty.
    """
    from taste_graph_ai.config import DATA_DIR
    target = date_str or date.today().isoformat()
    json_path = DATA_DIR / f"today_candidates_{target}.json"
    if not json_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No candidates JSON for {target} (expected {json_path})",
        )
    import json as _json
    return _json.loads(json_path.read_text(encoding="utf-8"))


@router.post("/candidates/select")
async def select_candidates(body: dict):
    """Persist user's selection of 30 candidates for clustering.

    Body: {"date": "2026-08-18", "image_ids": [...]}
    Writes data/today_selection_{date}.json — used by the next step
    (CLIP clustering → 3 series × 10).
    """
    from taste_graph_ai.config import DATA_DIR
    target = body.get("date") or date.today().isoformat()
    image_ids = body.get("image_ids") or []
    if not isinstance(image_ids, list) or not image_ids:
        raise HTTPException(status_code=400, detail="image_ids must be a non-empty list")
    if len(image_ids) > 100:
        raise HTTPException(status_code=400, detail="Too many candidates selected (max 100)")
    payload = {
        "date": target,
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "image_ids": image_ids,
        "count": len(image_ids),
    }
    out_path = DATA_DIR / f"today_selection_{target}.json"
    out_path.write_text(
        __import__("json").dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"status": "ok", "saved": len(image_ids), "path": str(out_path)}


def _load_packs_from_filesystem(today: str) -> list[schemas.DailyPackResponse]:
    """Synthesize DailyPackResponse from posts/{today}/post-*/ directory layout.

    This is the fallback when generate_publish_packs.py wrote to filesystem
    instead of SQLite. Each pack directory has:
        title.txt / body.txt / pillar.txt / score.txt / hashtags.txt / image.jpg
    """
    day_dir = POSTS_DIR / today
    if not day_dir.exists() or not day_dir.is_dir():
        return []

    pack_dirs = sorted(
        [d for d in day_dir.iterdir() if d.is_dir() and d.name.startswith("post-")]
    )
    if not pack_dirs:
        return []

    responses = []
    for pack_dir in pack_dirs:
        def _read(name: str, _p: Path = pack_dir) -> str:
            target = day_dir / _p.name / name
            return target.read_text().strip() if target.exists() else ""

        title = _read("title.txt")
        body = _read("body.txt")
        pillar = _read("pillar.txt")
        try:
            score = float(_read("score.txt") or 0.0)
        except ValueError:
            score = 0.0
        hashtags = _read("hashtags.txt")

        image_path = pack_dir / "image.jpg"
        stat = image_path.stat() if image_path.exists() else None
        created_at = (
            datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            if stat else datetime.now(timezone.utc).isoformat()
        )

        img_dict = {
            "image_id": f"{pack_dir.name}-image",
            "position": 0,
            "user_action": "",
            "url": "",
            "page_url": "",
            "local_path": str(image_path),
            "image_url": f"/api/v1/daily/file-pack/{today}/{pack_dir.name}/image",
            "keywords": [],
            "source_name": pillar or "今日采样",
        }

        try:
            pack_resp = schemas.DailyPackResponse(
                id=pack_dir.name,
                date=today,
                theme=pillar or "",
                why_today="",
                title_options=[title] if title else [],
                caption=body + (f"\n\n{hashtags}" if hashtags else ""),
                taste_score=score,
                status="draft",
                images=[schemas.PackImageResponse(**img_dict)],
                created_at=created_at,
                selected_at=None,
            )
            responses.append(pack_resp)
        except Exception:
            # If schema validation fails, skip this pack rather than 500 the whole list
            continue

    return responses


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
    pack = await pack_repo.get_by_id(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")

    # First export
    images = await pack_repo.get_pack_images(pack_id)
    if not images:
        return schemas.AutoPublishResponse(success=False, error="No images in pack")

    image_paths = [img["local_path"] for img in images if img.get("local_path")]
    if not image_paths:
        return schemas.AutoPublishResponse(success=False, error="No local images available")

    composer = MoodboardComposer()
    title = pack.title_options[0] if pack.title_options else pack.theme
    export_path = composer.compose(
        image_paths=image_paths,
        theme=pack.theme,
        caption=pack.caption,
        title=title,
    )

    # Use CDP publisher (not Playwright — the shadow DOM fix is only in CDP)
    try:
        from taste_graph_ai.cdp_adapter import publish_via_cdp, is_chrome_ready

        if not is_chrome_ready():
            return schemas.AutoPublishResponse(
                success=False,
                error="Chrome 未在调试模式运行。请用 chrome --remote-debugging-port=9222 启动。",
            )

        result = publish_via_cdp(
            title=title,
            content=pack.caption or pack.theme,
            image_paths=image_paths,
        )

        if not result.get("success"):
            return schemas.AutoPublishResponse(
                success=False,
                error=f"CDP 发布失败: {result.get('message', 'unknown')}",
            )
        post_url = result.get("post_url", "")
    except ImportError as e:
        return schemas.AutoPublishResponse(
            success=False,
            error=f"CDP adapter 导入失败: {e}",
        )
    except Exception as e:
        event_log.append("publish.auto_failed", {"pack_id": pack_id, "error": str(e)})
        return schemas.AutoPublishResponse(
            success=False,
            error=f"自动发布失败: {e}。导出文件: /exports/{export_path.name}",
        )

    # Success
    pack.publish()
    await pack_repo.save(pack)

    now = datetime.now(timezone.utc).isoformat()
    record = PublishRecord(
        id=uuid.uuid4().hex[:12],
        pack_id=pack_id,
        published_at=now,
        platform="xiaohongshu",
        post_url=post_url,
    )
    await publish_repo.save(record)

    event_log.append("pack.auto_published", {
        "pack_id": pack_id,
        "post_url": post_url,
        "publish_record_id": record.id,
    })
    return schemas.AutoPublishResponse(success=True, post_url=post_url)


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
