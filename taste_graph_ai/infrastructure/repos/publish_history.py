from typing import Optional

import aiosqlite

from taste_graph_ai.domain.models import PublishRecord


class PublishHistoryRepository:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def save(self, record: PublishRecord) -> None:
        await self.db.execute(
            """INSERT OR REPLACE INTO publish_history
            (id, pack_id, published_at, platform, post_url, likes, saves, comments, engagement_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.id, record.pack_id, record.published_at,
                record.platform, record.post_url, record.likes,
                record.saves, record.comments, record.engagement_rate,
            ),
        )
        await self.db.commit()

    async def get_by_pack_id(self, pack_id: str) -> Optional[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM publish_history WHERE pack_id = ? ORDER BY published_at DESC LIMIT 1",
            (pack_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_recent(self, limit: int = 20) -> list[dict]:
        cursor = await self.db.execute(
            """SELECT ph.*, dp.theme
            FROM publish_history ph
            LEFT JOIN daily_packs dp ON ph.pack_id = dp.id
            ORDER BY ph.published_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in await cursor.fetchall()]
