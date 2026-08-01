from pydantic import BaseModel

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from taste_graph_ai.api import schemas
from taste_graph_ai.api.deps import (
    get_source_repo,
    get_pack_repo,
    get_task_repo,
    get_image_repo,
    get_feedback_repo,
    get_event_log,
)
from taste_graph_ai.infrastructure.repos.sources import SourceRepository
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.tasks import TaskRepository
from taste_graph_ai.infrastructure.repos.images import ImageRepository
from taste_graph_ai.infrastructure.repos.feedback import FeedbackRepository
from taste_graph_ai.infrastructure.repos.scrape_failures import ScrapeFailureRepository
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.infrastructure.ai.client import AIClient
from taste_graph_ai.services.discovery import DiscoveryService
from taste_graph_ai.services.tasks import TaskService
from taste_graph_ai.services.generator import PackGenerationService
from taste_graph_ai.services.images import ImageFetchService

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


@router.post("/discover", response_model=schemas.PipelineResult)
async def trigger_discover(
    source_repo: SourceRepository = Depends(get_source_repo),
    event_log: EventLog = Depends(get_event_log),
):
    try:
        ai = AIClient()
        discovery = DiscoveryService(source_repo, event_log, ai)
        new_sources = await discovery.run_discovery()
        await ai.close()
        return schemas.PipelineResult(
            success=True,
            message=f"Found {len(new_sources)} new sources",
            data={"new_sources": len(new_sources)},
        )
    except Exception as e:
        event_log.append("pipeline.discovery_error", {"error": str(e)})
        return schemas.PipelineResult(
            success=False,
            message=f"Discovery failed: {e}",
        )


@router.post("/scrape-images", response_model=schemas.PipelineResult)
async def trigger_scrape_images(
    source_repo: SourceRepository = Depends(get_source_repo),
    image_repo: ImageRepository = Depends(get_image_repo),
    pack_repo: PackRepository = Depends(get_pack_repo),
    event_log: EventLog = Depends(get_event_log),
    feedback_repo: FeedbackRepository = Depends(get_feedback_repo),
):
    try:
        img_service = ImageFetchService(image_repo, source_repo, pack_repo, feedback_repo, event_log, ScrapeFailureRepository(image_repo.db))
        count = await img_service.scrape_approved_sources()
        return schemas.PipelineResult(
            success=True,
            message=f"Scraped {count} images from approved sources",
            data={"images": count},
        )
    except Exception as e:
        event_log.append("pipeline.scrape_error", {"error": str(e)})
        return schemas.PipelineResult(
            success=False,
            message=f"Scrape failed: {e}",
        )


@router.post("/generate", response_model=schemas.PipelineResult)
async def trigger_generate(
    source_repo: SourceRepository = Depends(get_source_repo),
    pack_repo: PackRepository = Depends(get_pack_repo),
    image_repo: ImageRepository = Depends(get_image_repo),
    event_log: EventLog = Depends(get_event_log),
    feedback_repo: FeedbackRepository = Depends(get_feedback_repo),
):
    try:
        ai = AIClient()
        img_service = ImageFetchService(image_repo, source_repo, pack_repo, feedback_repo, event_log, ScrapeFailureRepository(image_repo.db))
        gen = PackGenerationService(pack_repo, event_log, ai, img_service)
        packs = await gen.generate_daily_packs()
        await ai.close()
        return schemas.PipelineResult(
            success=True,
            message=f"Generated {len(packs)} daily packs",
            data={"packs": len(packs)},
        )
    except Exception as e:
        return schemas.PipelineResult(
            success=False,
            message=f"Generation failed: {e}",
        )


@router.post("/full", response_model=schemas.PipelineResult)
async def trigger_full(
    auto_publish: bool = False,
    source_repo: SourceRepository = Depends(get_source_repo),
    pack_repo: PackRepository = Depends(get_pack_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    image_repo: ImageRepository = Depends(get_image_repo),
    event_log: EventLog = Depends(get_event_log),
    feedback_repo: FeedbackRepository = Depends(get_feedback_repo),
):
    try:
        ai = AIClient()
        img_service = ImageFetchService(image_repo, source_repo, pack_repo, feedback_repo, event_log, ScrapeFailureRepository(image_repo.db))

        # 1. Discovery
        discovery = DiscoveryService(source_repo, event_log, ai)
        new_sources = await discovery.run_discovery()

        # 2. Scrape approved sources for images
        img_count = await img_service.scrape_approved_sources()

        # 3. Tasks
        task_service = TaskService(source_repo, pack_repo, task_repo, event_log)
        tasks = await task_service.persist_daily_tasks()

        # 4. Daily packs
        gen = PackGenerationService(pack_repo, event_log, ai, img_service)
        packs = await gen.generate_daily_packs()

        await ai.close()

        # 5. Optional auto-publish (best-scoring pack) via CDP
        auto_pub_result = ""
        if auto_publish and packs:
            from taste_graph_ai.cdp_adapter import publish_via_cdp
            best = max(packs, key=lambda p: p.taste_score)
            try:
                imgs = await pack_repo.get_pack_images(best.id)
                paths = [i["local_path"] for i in imgs if i.get("local_path")]
                if paths:
                    title = best.title_options[0] if best.title_options else best.theme
                    caption = best.caption or best.theme
                    result = publish_via_cdp(title=title, content=caption, image_paths=paths)
                    if result.get("success"):
                        post_url = result.get("post_url", "")
                        best.publish()
                        await pack_repo.save(best)
                        auto_pub_result = f" | CDP published: {post_url}"
                    else:
                        auto_pub_result = f" | CDP publish failed: {result.get('message', 'unknown')}"
            except Exception as e:
                auto_pub_result = f" | Auto-publish failed: {e}"
                event_log.append("pipeline.auto_publish_error", {"error": str(e)})

        return schemas.PipelineResult(
            success=True,
            message=f"Pipeline complete: {len(new_sources)} sources, {img_count} images, {len(tasks)} tasks, {len(packs)} packs{auto_pub_result}",
            data={
                "new_sources": len(new_sources),
                "images": img_count,
                "tasks": len(tasks),
                "packs": len(packs),
            },
        )
    except Exception as e:
        event_log.append("pipeline.error", {"error": str(e)})
        return schemas.PipelineResult(
            success=False,
            message=f"Pipeline failed: {e}",
        )


class CDPPublishRequest(BaseModel):
    pack_id: str = ""
    title: str = ""
    content: str = ""
    image_paths: list[str] = []


@router.post("/cdp-publish", response_model=schemas.PipelineResult)
async def trigger_cdp_publish(
    body: CDPPublishRequest,
    request: Request,
    pack_repo: PackRepository = Depends(get_pack_repo),
    event_log: EventLog = Depends(get_event_log),
):
    """Publish directly via CDP browser automation.

    Two modes:
    1. Provide pack_id — loads title/content/images from the pack in DB.
    2. Provide title/content/image_paths directly (for manual / curated packs).

    SAFETY (2026-07-29): If config/schedule.json has _publish_disabled=true,
    this endpoint refuses with 403 unless caller sends header:
        X-Publish-Override: I-UNDERSTAND-RISK
    Defense against accidental API calls / old scripts / leftover cron.
    """
    # ── safety gate ─────────────────────────────────────────
    import json
    from pathlib import Path as _Path
    schedule_file = _Path(__file__).resolve().parents[3] / "config" / "schedule.json"
    if schedule_file.exists():
        try:
            cfg = json.loads(schedule_file.read_text())
            if cfg.get("_publish_disabled") is True:
                override = request.headers.get("X-Publish-Override", "")
                if override != "I-UNDERSTAND-RISK":
                    reason = cfg.get("_publish_disabled_reason", "publishing disabled")
                    raise HTTPException(
                        status_code=403,
                        detail=f"XHS publish blocked: {reason}. "
                               f"To override, send header X-Publish-Override: I-UNDERSTAND-RISK",
                    )
        except HTTPException:
            raise
        except Exception:
            pass

    from taste_graph_ai.cdp_adapter import publish_via_cdp, is_chrome_ready

    if not is_chrome_ready():
        raise HTTPException(
            status_code=503,
            detail="Chrome with remote debugging (port 9222) is not running. "
                   "Start Chrome with: chrome --remote-debugging-port=9222",
        )

    pack_id = body.pack_id
    title = body.title
    content = body.content
    image_paths = body.image_paths

    if pack_id:
        pack = await pack_repo.get_by_id(pack_id)
        if not pack:
            raise HTTPException(status_code=404, detail="Pack not found")
        imgs = await pack_repo.get_pack_images(pack_id)
        paths = [i["local_path"] for i in imgs if i.get("local_path")]
        if not paths:
            raise HTTPException(status_code=400, detail="Pack has no local images")
        title = pack.title_options[0] if pack.title_options else pack.theme
        content = pack.caption or pack.theme
    else:
        if not title or not content or not image_paths:
            raise HTTPException(
                status_code=400,
                detail="Provide pack_id or (title + content + image_paths)",
            )
        paths = image_paths

    result = publish_via_cdp(title=title, content=content, image_paths=paths)

    if result.get("success"):
        if pack_id:
            pack = await pack_repo.get_by_id(pack_id)
            if pack:
                pack.publish()
                await pack_repo.save(pack)
        event_log.append("pipeline.cdp_publish_ok", {
            "pack_id": pack_id,
            "post_url": result.get("post_url", ""),
        })
    else:
        event_log.append("pipeline.cdp_publish_error", {
            "pack_id": pack_id,
            "error": result.get("message", "unknown"),
        })

    return schemas.PipelineResult(
        success=result.get("success", False),
        message=result.get("message", ""),
        data={"post_url": result.get("post_url", "")},
    )
