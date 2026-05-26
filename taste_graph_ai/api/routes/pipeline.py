from fastapi import APIRouter, Depends

from taste_graph_ai.api import schemas
from taste_graph_ai.api.deps import (
    get_source_repo,
    get_pack_repo,
    get_task_repo,
    get_event_log,
)
from taste_graph_ai.infrastructure.repos.sources import SourceRepository
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.tasks import TaskRepository
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.infrastructure.ai.client import AIClient
from taste_graph_ai.services.discovery import DiscoveryService
from taste_graph_ai.services.tasks import TaskService

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


@router.post("/generate", response_model=schemas.PipelineResult)
async def trigger_generate(
    pack_repo: PackRepository = Depends(get_pack_repo),
    event_log: EventLog = Depends(get_event_log),
):
    try:
        ai = AIClient()
        # Placeholder: full theme generation will come later
        await ai.close()
        return schemas.PipelineResult(
            success=True,
            message="Daily pack generation triggered (placeholder).",
            data={"packs": 0},
        )
    except Exception as e:
        return schemas.PipelineResult(
            success=False,
            message=f"Generation failed: {e}",
        )


@router.post("/full", response_model=schemas.PipelineResult)
async def trigger_full(
    source_repo: SourceRepository = Depends(get_source_repo),
    pack_repo: PackRepository = Depends(get_pack_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    event_log: EventLog = Depends(get_event_log),
):
    try:
        ai = AIClient()

        # 1. Discovery
        discovery = DiscoveryService(source_repo, event_log, ai)
        new_sources = await discovery.run_discovery()

        # 2. Tasks
        task_service = TaskService(source_repo, pack_repo, task_repo, event_log)
        tasks = await task_service.persist_daily_tasks()

        await ai.close()

        return schemas.PipelineResult(
            success=True,
            message=f"Pipeline complete: {len(new_sources)} sources, {len(tasks)} tasks",
            data={
                "new_sources": len(new_sources),
                "tasks": len(tasks),
            },
        )
    except Exception as e:
        event_log.append("pipeline.error", {"error": str(e)})
        return schemas.PipelineResult(
            success=False,
            message=f"Pipeline failed: {e}",
        )
