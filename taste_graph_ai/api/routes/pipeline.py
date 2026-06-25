from fastapi import APIRouter, Depends

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

        # 5. Optional auto-publish (best-scoring pack)
        auto_pub_result = ""
        if auto_publish and packs:
            best = max(packs, key=lambda p: p.taste_score)
            try:
                from modules.xhs_publisher.composer import MoodboardComposer
                composer = MoodboardComposer()
                imgs = await pack_repo.get_pack_images(best.id)
                paths = [i["local_path"] for i in imgs if i.get("local_path")]
                if paths:
                    title = best.title_options[0] if best.title_options else best.theme
                    export_path = composer.compose(
                        image_paths=paths, theme=best.theme, caption=best.caption, title=title,
                    )
                    from modules.xhs_publisher.publisher import XiaohongshuPublisher
                    from taste_graph_ai.config import XHS_COOKIES_FILE
                    async with XiaohongshuPublisher(cookies_path=XHS_COOKIES_FILE) as publisher:
                        post_url = await publisher.publish(str(export_path), title, best.caption)
                    best.publish()
                    await pack_repo.save(best)
                    auto_pub_result = f" | Auto-published: {post_url}"
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
