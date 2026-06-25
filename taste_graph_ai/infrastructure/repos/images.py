import json
from typing import Optional

import aiosqlite

from taste_graph_ai.domain.enums import ImageStatus
from taste_graph_ai.domain.models import Image


class ImageRepository:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_by_id(self, id: str) -> Optional[Image]:
        cursor = await self.db.execute("SELECT * FROM images WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return self._row_to_image(row) if row else None

    async def save(self, image: Image) -> None:
        await self.db.execute(
            """INSERT OR REPLACE INTO images
            (id, source_id, url, page_url, local_path, thumbnail_path,
             keywords_json, graph_score, visual_score, final_score, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                image.id, image.source_id, image.url, image.page_url,
                image.local_path, image.thumbnail_path,
                json.dumps(image.keywords, ensure_ascii=False),
                image.graph_score, image.visual_score, image.final_score,
                image.status.value, image.created_at,
            ),
        )
        await self.db.commit()

    async def get_by_url(self, url: str) -> Optional[Image]:
        cursor = await self.db.execute("SELECT * FROM images WHERE url = ?", (url,))
        row = await cursor.fetchone()
        return self._row_to_image(row) if row else None

    async def delete(self, id: str) -> None:
        await self.db.execute("DELETE FROM images WHERE id = ?", (id,))
        await self.db.commit()

    async def list_by_status(self, status: ImageStatus, limit: int = 50) -> list[Image]:
        cursor = await self.db.execute(
            "SELECT * FROM images WHERE status = ? ORDER BY final_score DESC LIMIT ?",
            (status.value, limit),
        )
        return [self._row_to_image(r) for r in await cursor.fetchall()]

    async def list_by_source(self, source_id: str) -> list[Image]:
        cursor = await self.db.execute(
            "SELECT * FROM images WHERE source_id = ? ORDER BY final_score DESC",
            (source_id,),
        )
        return [self._row_to_image(r) for r in await cursor.fetchall()]

    async def find_similar(self, embedding: list[float], limit: int = 10) -> list[Image]:
        # Placeholder: will be replaced with real vector search when CLIP is integrated
        cursor = await self.db.execute(
            "SELECT * FROM images WHERE status != 'rejected' ORDER BY final_score DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_image(r) for r in await cursor.fetchall()]

    async def list_by_status_paginated(
        self, status: ImageStatus, page: int = 1, limit: int = 50
    ) -> tuple[list[Image], int]:
        offset = (page - 1) * limit
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM images WHERE status = ?", (status.value,)
        )
        total_row = await cursor.fetchone()
        total = total_row[0] if total_row else 0
        cursor = await self.db.execute(
            "SELECT * FROM images WHERE status = ? ORDER BY final_score DESC LIMIT ? OFFSET ?",
            (status.value, limit, offset),
        )
        images = [self._row_to_image(r) for r in await cursor.fetchall()]
        return images, total

    async def mark_many_status(self, ids: list[str], status: ImageStatus) -> None:
        """Batch update status for multiple images."""
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        await self.db.execute(
            f"UPDATE images SET status = ? WHERE id IN ({placeholders})",
            (status.value, *ids),
        )
        await self.db.commit()

    async def count_pending(self) -> int:
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM images WHERE status = 'pending'"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    @staticmethod
    def _row_to_image(row) -> Image:
        return Image(
            id=row["id"],
            source_id=row["source_id"],
            url=row["url"],
            page_url=row["page_url"],
            local_path=row["local_path"],
            thumbnail_path=row["thumbnail_path"],
            keywords=json.loads(row["keywords_json"] or "[]"),
            graph_score=row["graph_score"],
            visual_score=row["visual_score"],
            final_score=row["final_score"],
            status=ImageStatus(row["status"]),
            created_at=row["created_at"],
        )
