from typing import Optional

import aiosqlite

from taste_graph_ai.domain.enums import FeedbackLabel, FeedbackTargetType
from taste_graph_ai.domain.models import Feedback


class FeedbackRepository:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_by_id(self, id: str) -> Optional[Feedback]:
        cursor = await self.db.execute("SELECT * FROM feedback_log WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return self._row_to_feedback(row) if row else None

    async def save(self, fb: Feedback) -> None:
        await self.db.execute(
            """INSERT INTO feedback_log (id, target_type, target_id, label, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (fb.id, fb.target_type.value, fb.target_id, fb.label.value, fb.note, fb.created_at),
        )
        await self.db.commit()

    async def delete(self, id: str) -> None:
        await self.db.execute("DELETE FROM feedback_log WHERE id = ?", (id,))
        await self.db.commit()

    async def list_by_target(self, target_type: FeedbackTargetType, target_id: str) -> list[Feedback]:
        cursor = await self.db.execute(
            "SELECT * FROM feedback_log WHERE target_type = ? AND target_id = ? ORDER BY created_at DESC",
            (target_type.value, target_id),
        )
        return [self._row_to_feedback(r) for r in await cursor.fetchall()]

    async def get_liked_image_ids(self) -> set[str]:
        """Return all image IDs ever marked '对味', for scoring bonuses."""
        cursor = await self.db.execute(
            "SELECT DISTINCT target_id FROM feedback_log "
            "WHERE target_type = 'image' AND label = '对味'"
        )
        rows = await cursor.fetchall()
        return {r["target_id"] for r in rows}

    async def list_recent(self, limit: int = 50) -> list[Feedback]:
        cursor = await self.db.execute(
            "SELECT * FROM feedback_log ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [self._row_to_feedback(r) for r in await cursor.fetchall()]

    @staticmethod
    def _row_to_feedback(row) -> Feedback:
        return Feedback(
            id=row["id"],
            target_type=FeedbackTargetType(row["target_type"]),
            target_id=row["target_id"],
            label=FeedbackLabel(row["label"]),
            note=row["note"] or "",
            created_at=row["created_at"],
        )
