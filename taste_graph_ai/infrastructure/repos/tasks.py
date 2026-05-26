from typing import Optional

import aiosqlite

from taste_graph_ai.domain.enums import TaskType, TaskPriority, TaskStatus
from taste_graph_ai.domain.models import Task


class TaskRepository:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_by_id(self, id: str) -> Optional[Task]:
        cursor = await self.db.execute("SELECT * FROM tasks WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return self._row_to_task(row) if row else None

    async def save(self, task: Task) -> None:
        await self.db.execute(
            """INSERT OR REPLACE INTO tasks
            (id, task_type, title, body, priority, action_url, status, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.id, task.task_type.value, task.title, task.body,
                task.priority.value, task.action_url, task.status.value,
                task.created_at, task.completed_at,
            ),
        )
        await self.db.commit()

    async def delete(self, id: str) -> None:
        await self.db.execute("DELETE FROM tasks WHERE id = ?", (id,))
        await self.db.commit()

    async def list_pending(self, limit: int = 10) -> list[Task]:
        cursor = await self.db.execute(
            "SELECT * FROM tasks WHERE status = 'pending' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_task(r) for r in await cursor.fetchall()]

    async def list_today(self, date_str: str) -> list[Task]:
        cursor = await self.db.execute(
            "SELECT * FROM tasks WHERE created_at >= ? ORDER BY created_at DESC",
            (date_str,),
        )
        return [self._row_to_task(r) for r in await cursor.fetchall()]

    async def list_history(self, limit: int = 30) -> list[Task]:
        cursor = await self.db.execute(
            "SELECT * FROM tasks WHERE status != 'pending' ORDER BY completed_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_task(r) for r in await cursor.fetchall()]

    @staticmethod
    def _row_to_task(row) -> Task:
        return Task(
            id=row["id"],
            task_type=TaskType(row["task_type"]),
            title=row["title"],
            body=row["body"] or "",
            priority=TaskPriority(row["priority"]),
            action_url=row["action_url"] or "",
            status=TaskStatus(row["status"]),
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )
