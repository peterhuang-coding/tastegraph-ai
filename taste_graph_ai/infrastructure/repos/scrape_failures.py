import aiosqlite

from taste_graph_ai.domain.models import ScrapeFailure


class ScrapeFailureRepository:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def save(self, f: ScrapeFailure) -> None:
        await self.db.execute(
            """INSERT INTO scrape_failures (id, source_id, source_name, url, reason, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (f.id, f.source_id, f.source_name, f.url, f.reason, f.detail, f.created_at),
        )
        await self.db.commit()

    async def list_recent(self, limit: int = 100) -> list[ScrapeFailure]:
        cursor = await self.db.execute(
            "SELECT * FROM scrape_failures ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_failure(r) for r in await cursor.fetchall()]

    async def list_by_source(self, source_id: str, limit: int = 50) -> list[ScrapeFailure]:
        cursor = await self.db.execute(
            "SELECT * FROM scrape_failures WHERE source_id = ? ORDER BY created_at DESC LIMIT ?",
            (source_id, limit),
        )
        return [self._row_to_failure(r) for r in await cursor.fetchall()]

    async def stats_by_source(self) -> list[dict]:
        """Group failures by source for dashboard."""
        cursor = await self.db.execute(
            """SELECT s.name as source_name, sf.source_id, sf.reason, COUNT(*) as cnt
            FROM scrape_failures sf
            LEFT JOIN sources s ON sf.source_id = s.id
            GROUP BY sf.source_id, sf.reason
            ORDER BY cnt DESC"""
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def stats_by_reason(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT reason, COUNT(*) as cnt FROM scrape_failures GROUP BY reason ORDER BY cnt DESC"
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def count_total(self) -> int:
        cursor = await self.db.execute("SELECT COUNT(*) FROM scrape_failures")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def delete_old(self, before_days: int = 30) -> int:
        cursor = await self.db.execute(
            "DELETE FROM scrape_failures WHERE created_at < datetime('now', ?)",
            (f"-{before_days} days",),
        )
        await self.db.commit()
        return cursor.rowcount

    @staticmethod
    def _row_to_failure(row) -> ScrapeFailure:
        return ScrapeFailure(
            id=row["id"],
            source_id=row["source_id"] or "",
            source_name=row["source_name"] or "",
            url=row["url"] or "",
            reason=row["reason"],
            detail=row["detail"] or "",
            created_at=row["created_at"],
        )
