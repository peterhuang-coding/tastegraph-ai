from fastapi import APIRouter, Depends, HTTPException

from taste_graph_ai.api import schemas
from taste_graph_ai.api.deps import get_task_repo, get_task_service, get_event_log
from taste_graph_ai.infrastructure.repos.tasks import TaskRepository
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.services.tasks import TaskService

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("/today", response_model=list[schemas.TaskResponse])
async def get_today_tasks(
    repo: TaskRepository = Depends(get_task_repo),
    task_service: TaskService = Depends(get_task_service),
):
    from datetime import date
    today = date.today().isoformat()
    existing = await repo.list_today(today)
    if not existing:
        existing = await task_service.persist_daily_tasks()
    return [_task_to_response(t) for t in existing]


@router.get("/pending", response_model=list[schemas.TaskResponse])
async def list_pending(repo: TaskRepository = Depends(get_task_repo)):
    return [_task_to_response(t) for t in await repo.list_pending()]


@router.get("/history", response_model=list[schemas.TaskResponse])
async def list_history(repo: TaskRepository = Depends(get_task_repo)):
    return [_task_to_response(t) for t in await repo.list_history()]


@router.post("/{task_id}/complete", response_model=schemas.TaskResponse)
async def complete_task(
    task_id: str,
    repo: TaskRepository = Depends(get_task_repo),
    event_log: EventLog = Depends(get_event_log),
):
    task = await repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.complete()
    await repo.save(task)
    event_log.append("task.completed", {"id": task_id, "type": task.task_type.value})
    return _task_to_response(task)


@router.post("/{task_id}/dismiss", response_model=schemas.TaskResponse)
async def dismiss_task(
    task_id: str,
    repo: TaskRepository = Depends(get_task_repo),
    event_log: EventLog = Depends(get_event_log),
):
    task = await repo.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.dismiss()
    await repo.save(task)
    event_log.append("task.dismissed", {"id": task_id, "type": task.task_type.value})
    return _task_to_response(task)


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
