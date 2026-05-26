from fastapi import Depends

from taste_graph_ai.infrastructure.db.connection import get_db as _get_db
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.infrastructure.repos import (
    SourceRepository,
    ImageRepository,
    PackRepository,
    FeedbackRepository,
    TaskRepository,
)
from taste_graph_ai.services.feedback import FeedbackService


async def get_db():
    db = await _get_db()
    try:
        yield db
    finally:
        await db.close()


async def get_source_repo(db=Depends(get_db)):
    return SourceRepository(db)


async def get_image_repo(db=Depends(get_db)):
    return ImageRepository(db)


async def get_pack_repo(db=Depends(get_db)):
    return PackRepository(db)


async def get_feedback_repo(db=Depends(get_db)):
    return FeedbackRepository(db)


async def get_task_repo(db=Depends(get_db)):
    return TaskRepository(db)


def get_event_log() -> EventLog:
    return EventLog()


def get_feedback_service(
    feedback_repo: FeedbackRepository = Depends(get_feedback_repo),
    event_log: EventLog = Depends(get_event_log),
) -> FeedbackService:
    return FeedbackService(feedback_repo, event_log)


from taste_graph_ai.services.tasks import TaskService


def get_task_service(
    source_repo: SourceRepository = Depends(get_source_repo),
    pack_repo: PackRepository = Depends(get_pack_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    event_log: EventLog = Depends(get_event_log),
) -> TaskService:
    return TaskService(source_repo, pack_repo, task_repo, event_log)
