import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from taste_graph_ai.api import schemas
from taste_graph_ai.api.deps import get_event_log
from taste_graph_ai.config import BASE_DIR, LOGS_DIR
from taste_graph_ai.infrastructure.db.event_log import EventLog

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


def _start_ingestion(stage: str, event_log: EventLog) -> schemas.PipelineResult:
    """Start the canonical ingestion worker instead of running a second pipeline."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = "manual-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:4]
    log_path = LOGS_DIR / f"{run_id}.log"
    env = os.environ.copy()
    env["TASTEGRAPH_JOB_NAME"] = "manual_ingestion"
    env["TASTEGRAPH_JOB_LOG_PATH"] = str(log_path)
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [sys.executable, "-u", str(BASE_DIR / "scripts" / "daily_ingestion.py")]
    if stage == "all":
        cmd.append("--resume")
    cmd += ["--stage", stage]
    log_file = open(log_path, "ab")
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL,
            stdout=log_file, stderr=subprocess.STDOUT,
            start_new_session=True, env=env,
        )
    except OSError as exc:
        log_file.close()
        event_log.append("pipeline.ingestion_start_error", {"stage": stage, "error": str(exc)})
        return schemas.PipelineResult(success=False, message=f"采集任务启动失败: {exc}")
    log_file.close()
    event_log.append("pipeline.ingestion_started", {
        "stage": stage, "pid": proc.pid, "run_id": run_id, "log_path": str(log_path),
    })
    return schemas.PipelineResult(
        success=True,
        message="已启动统一采集任务；进度与结果写入运行状态。",
        data={"run_id": run_id, "pid": proc.pid, "stage": stage},
    )


@router.post("/discover", response_model=schemas.PipelineResult)
async def trigger_discover(
    event_log: EventLog = Depends(get_event_log),
):
    return _start_ingestion("discover", event_log)


@router.post("/scrape-images", response_model=schemas.PipelineResult)
async def trigger_scrape_images(
    event_log: EventLog = Depends(get_event_log),
):
    return _start_ingestion("ingest", event_log)


@router.post("/generate", response_model=schemas.PipelineResult)
async def trigger_generate(
    event_log: EventLog = Depends(get_event_log),
):
    return _start_ingestion("pack", event_log)


@router.post("/full", response_model=schemas.PipelineResult)
async def trigger_full(
    event_log: EventLog = Depends(get_event_log),
):
    return _start_ingestion("all", event_log)
