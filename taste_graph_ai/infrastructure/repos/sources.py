import json
from typing import Optional

import aiosqlite

from taste_graph_ai.domain.enums import SourceType, SourceStatus
from taste_graph_ai.domain.models import Source


class SourceRepository:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_by_id(self, id: str) -> Optional[Source]:
        cursor = await self.db.execute("SELECT * FROM sources WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return self._row_to_source(row) if row else None

    async def save(self, source: Source) -> None:
        await self.db.execute(
            """INSERT OR REPLACE INTO sources
            (id, url, name, source_type, discovered_from, preview_thumbnails,
             ai_score, ai_reason, ai_risk, status, reviewer_note, created_at, reviewed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source.id, source.url, source.name, source.source_type.value,
                source.discovered_from, json.dumps(source.preview_thumbnails, ensure_ascii=False),
                source.ai_score, source.ai_reason, source.ai_risk, source.status.value,
                source.reviewer_note, source.created_at, source.reviewed_at,
            ),
        )
        await self.db.commit()

    async def delete(self, id: str) -> None:
        await self.db.execute("DELETE FROM sources WHERE id = ?", (id,))
        await self.db.commit()

    async def list_by_status(self, status: SourceStatus, limit: int = 50, offset: int = 0) -> list[Source]:
        cursor = await self.db.execute(
            "SELECT * FROM sources WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (status.value, limit, offset),
        )
        return [self._row_to_source(r) for r in await cursor.fetchall()]

    async def count_by_status(self, status: SourceStatus) -> int:
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM sources WHERE status = ?", (status.value,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def count_pending(self) -> int:
        return await self.count_by_status(SourceStatus.PENDING)

    async def count_stale_deferred(self, days: int = 3) -> int:
        cursor = await self.db.execute(
            """SELECT COUNT(*) FROM sources
            WHERE status = 'deferred'
            AND reviewed_at < datetime('now', ? || ' days')""",
            (f"-{days}",),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def find_by_url(self, url: str) -> Optional[Source]:
        cursor = await self.db.execute("SELECT * FROM sources WHERE url = ?", (url,))
        row = await cursor.fetchone()
        return self._row_to_source(row) if row else None

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[Source]:
        cursor = await self.db.execute(
            "SELECT * FROM sources ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [self._row_to_source(r) for r in await cursor.fetchall()]

    async def stats(self) -> dict:
        cursor = await self.db.execute(
            "SELECT status, COUNT(*) as cnt FROM sources GROUP BY status"
        )
        rows = await cursor.fetchall()
        return {row["status"]: row["cnt"] for row in rows}

    @staticmethod
    def _row_to_source(row) -> Source:
        return Source(
            id=row["id"],
            url=row["url"],
            name=row["name"],
            source_type=SourceType(row["source_type"]),
            discovered_from=row["discovered_from"],
            preview_thumbnails=json.loads(row["preview_thumbnails"] or "[]"),
            ai_score=row["ai_score"],
            ai_reason=row["ai_reason"],
            ai_risk=row["ai_risk"],
            status=SourceStatus(row["status"]),
            reviewer_note=row["reviewer_note"] or "",
            created_at=row["created_at"],
            reviewed_at=row["reviewed_at"],
        )
