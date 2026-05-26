from fastapi import APIRouter

from taste_graph_ai.api import schemas

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


@router.post("/discover", response_model=schemas.PipelineResult)
async def trigger_discover():
    return schemas.PipelineResult(
        success=True,
        message="Discovery pipeline triggered. Check /api/v1/sources/pending for results.",
    )


@router.post("/generate", response_model=schemas.PipelineResult)
async def trigger_generate():
    return schemas.PipelineResult(
        success=True,
        message="Generation pipeline triggered. Check /api/v1/daily/today for results.",
    )


@router.post("/full", response_model=schemas.PipelineResult)
async def trigger_full():
    return schemas.PipelineResult(
        success=True,
        message="Full pipeline triggered.",
    )
