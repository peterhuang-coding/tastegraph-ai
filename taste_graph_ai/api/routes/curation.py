import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from taste_graph_ai.api import schemas
from taste_graph_ai.api.deps import (
    get_image_repo,
    get_pack_repo,
    get_feedback_repo,
    get_feedback_service,
    get_event_log,
    get_source_repo,
    get_failure_repo,
)
from taste_graph_ai.domain.enums import (
    ImageStatus, PackStatus, FeedbackLabel, FeedbackTargetType, UserAction,
)
from taste_graph_ai.domain.models import DailyPack, PackImage
from taste_graph_ai.infrastructure.repos.images import ImageRepository
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.sources import SourceRepository
from taste_graph_ai.infrastructure.repos.feedback import FeedbackRepository
from taste_graph_ai.services.feedback import FeedbackService
from taste_graph_ai.infrastructure.repos.scrape_failures import ScrapeFailureRepository
from taste_graph_ai.infrastructure.db.event_log import EventLog

router = APIRouter(prefix="/api/v1", tags=["curation"])


@router.get("/scrape-failures")
async def list_scrape_failures(
    failure_repo: ScrapeFailureRepository = Depends(get_failure_repo),
):
    stats_source = await failure_repo.stats_by_source()
    stats_reason = await failure_repo.stats_by_reason()
    recent = await failure_repo.list_recent(50)
    total = await failure_repo.count_total()
    return {
        "total": total,
        "by_source": stats_source,
        "by_reason": stats_reason,
        "recent": [
            {"id": f.id, "source_name": f.source_name, "url": f.url, "reason": f.reason, "detail": f.detail, "created_at": f.created_at}
            for f in recent
        ],
    }


@router.get("/images/pending", response_model=schemas.PendingImagesResponse)
async def list_pending_images(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    image_repo: ImageRepository = Depends(get_image_repo),
    source_repo: SourceRepository = Depends(get_source_repo),
):
    # Only return images whose local files exist — DB may have stale records.
    images, total = await image_repo.list_by_status_paginated(
        ImageStatus.PENDING, page=page, limit=limit, require_local_file=True
    )
    # Batch lookup source names
    source_names = {}
    for img in images:
        if img.source_id and img.source_id not in source_names:
            source = await source_repo.get_by_id(img.source_id)
            source_names[img.source_id] = source.name if source else ""

    items = []
    for img in images:
        if not Path(img.local_path).is_file():
            continue
        fname = Path(img.local_path).name
        items.append(schemas.PendingImageResponse(
            image_id=img.id,
            url=img.url,
            local_path=img.local_path,
            image_url=f"/images/{fname}",
            keywords=img.keywords,
            final_score=img.final_score,
            page_url=img.page_url,
            source_name=source_names.get(img.source_id, ""),
        ))
    return schemas.PendingImagesResponse(
        images=items,
        total=total,
        page=page,
        limit=limit,
    )


@router.post("/packs/curated", response_model=schemas.DailyPackResponse)
async def create_curated_pack(
    body: schemas.CuratedPackRequest,
    image_repo: ImageRepository = Depends(get_image_repo),
    pack_repo: PackRepository = Depends(get_pack_repo),
    feedback_repo: FeedbackRepository = Depends(get_feedback_repo),
    feedback_service: FeedbackService = Depends(get_feedback_service),
    event_log: EventLog = Depends(get_event_log),
):
    if len(body.image_ids) != 9:
        raise HTTPException(status_code=400, detail="必须选择 9 张图片")

    images = []
    for img_id in body.image_ids:
        img = await image_repo.get_by_id(img_id)
        if not img:
            raise HTTPException(status_code=404, detail=f"图片 {img_id} 不存在")
        if img.status != ImageStatus.PENDING:
            raise HTTPException(
                status_code=400,
                detail=f"图片 {img_id} 不可用（状态: {img.status.value}）",
            )
        images.append(img)

    today = date.today().isoformat()
    pack = DailyPack(
        id=uuid.uuid4().hex[:12],
        date=today,
        theme=body.theme,
        title_options=[body.title] if body.title else [],
        caption=body.caption,
        taste_score=85.0,
        status=PackStatus.SELECTED,
        is_curated=True,
    )
    await pack_repo.save(pack)

    for i, img_id in enumerate(body.image_ids):
        pi = PackImage(
            pack_id=pack.id,
            image_id=img_id,
            position=i,
            user_action=UserAction.APPROVED,
        )
        await pack_repo.save_pack_image(pi)

    await image_repo.mark_many_status(body.image_ids, ImageStatus.SELECTED)

    for img_id in body.image_ids:
        await feedback_service.record(
            target_type=FeedbackTargetType.IMAGE,
            target_id=img_id,
            label=FeedbackLabel.DUI_WEI,
            note=f"手动策展: {body.theme}",
        )

    event_log.append("pack.curated", {
        "pack_id": pack.id,
        "theme": body.theme,
        "image_ids": body.image_ids,
    })

    pack_images = await pack_repo.get_pack_images(pack.id)
    return _curated_pack_to_response(pack, pack_images)


def _curated_pack_to_response(pack, images):
    enriched = []
    for img in images:
        local = img.get("local_path", "")
        if local:
            img["image_url"] = f"/images/{Path(local).name}"
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


@router.post("/prefill")
async def prefill_curation(payload: dict):
    """
    手动选图 → AI 预填 theme/title/caption 三个字段。

    payload = {"image_ids": [str x 9], "image_keywords": [str x 9]}
    返回:   {"theme": str, "title": str, "caption": str, "_error": str(可选)}
    """
    image_ids = payload.get("image_ids", []) or []
    image_keywords = payload.get("image_keywords", []) or []

    if len(image_ids) != 9:
        raise HTTPException(status_code=400, detail="需要恰好 9 张图")

    # 兜底：image_keywords 缺失时按 image_ids 长度补空串
    if len(image_keywords) < len(image_ids):
        image_keywords = list(image_keywords) + [""] * (len(image_ids) - len(image_keywords))

    # 拼接 user_input：9 张图各自关键词 + 综合主题引导
    keywords_lines = "\n".join(
        f"  - {kw if kw else '(无关键词)'}" for kw in image_keywords
    )
    user_input = (
        "9 张已选中图片，请综合它们的关键词生成 theme/title/caption 三个字段。\n\n"
        "9 张图各自关键词:\n"
        f"{keywords_lines}"
    )

    context = {
        "image_count": 9,
        "sources": "见 taste_graph.json graph nodes",
        "time": "now",
    }

    try:
        from taste_graph_ai.services.voice import build_messages
        from taste_graph_ai.infrastructure.ai.client import AIClient

        msgs = build_messages("prefill", user_input, context)
        # msgs[0] = system, msgs[1..N] = few-shot, msgs[-1] = user
        # chat_json 接受单字符串 prompt，把 messages 拼成 prompt
        prompt_text = "\n\n".join(
            f"[{m['role']}]\n{m['content']}" for m in msgs
        )

        ai = AIClient()
        try:
            result = await ai.chat_json(prompt_text, max_tokens=600)
        finally:
            await ai.close()
    except Exception as e:
        # fallback：返回占位
        return {
            "theme": "冷调日常",
            "title": "9 张图：冷一点的春天",
            "caption": "（AI 暂不可用，请手动填写）",
            "_error": str(e),
        }

    return {
        "theme": (result.get("theme", "") or "").strip(),
        "title": (result.get("title", "") or "").strip(),
        "caption": (result.get("caption", "") or "").strip(),
    }
