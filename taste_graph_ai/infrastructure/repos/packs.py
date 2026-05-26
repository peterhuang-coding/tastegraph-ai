import json
from typing import Optional

import aiosqlite

from taste_graph_ai.domain.enums import PackStatus, UserAction
from taste_graph_ai.domain.models import DailyPack, PackImage


class PackRepository:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_by_id(self, id: str) -> Optional[DailyPack]:
        cursor = await self.db.execute("SELECT * FROM daily_packs WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return self._row_to_pack(row) if row else None

    async def save(self, pack: DailyPack) -> None:
        await self.db.execute(
            """INSERT OR REPLACE INTO daily_packs
            (id, date, theme, why_today, title_options_json, caption,
             taste_score, status, created_at, selected_at, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pack.id, pack.date, pack.theme, pack.why_today,
                json.dumps(pack.title_options, ensure_ascii=False),
                pack.caption, pack.taste_score, pack.status.value,
                pack.created_at, pack.selected_at, pack.published_at,
            ),
        )
        await self.db.commit()

    async def delete(self, id: str) -> None:
        await self.db.execute("DELETE FROM daily_packs WHERE id = ?", (id,))
        await self.db.commit()

    async def get_today_packs(self, date_str: str) -> list[DailyPack]:
        cursor = await self.db.execute(
            "SELECT * FROM daily_packs WHERE date = ? ORDER BY taste_score DESC",
            (date_str,),
        )
        return [self._row_to_pack(r) for r in await cursor.fetchall()]

    async def get_pack_images(self, pack_id: str) -> list[dict]:
        cursor = await self.db.execute(
            """SELECT pi.*, i.url, i.page_url, i.local_path, i.keywords_json
            FROM pack_images pi
            JOIN images i ON pi.image_id = i.id
            WHERE pi.pack_id = ?
            ORDER BY pi.position""",
            (pack_id,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "image_id": r["image_id"],
                "position": r["position"],
                "user_action": r["user_action"],
                "url": r["url"],
                "page_url": r["page_url"],
                "local_path": r["local_path"],
                "keywords": json.loads(r["keywords_json"] or "[]"),
            }
            for r in rows
        ]

    async def save_pack_image(self, pi: PackImage) -> None:
        await self.db.execute(
            """INSERT OR REPLACE INTO pack_images (pack_id, image_id, position, user_action)
            VALUES (?, ?, ?, ?)""",
            (pi.pack_id, pi.image_id, pi.position, pi.user_action.value),
        )
        await self.db.commit()

    async def get_latest_packs(self, limit: int = 20) -> list[DailyPack]:
        cursor = await self.db.execute(
            "SELECT * FROM daily_packs ORDER BY date DESC LIMIT ?", (limit,)
        )
        return [self._row_to_pack(r) for r in await cursor.fetchall()]

    async def get_top_theme(self, days: int = 7) -> Optional[dict]:
        cursor = await self.db.execute(
            """SELECT theme, COUNT(*) as cnt, AVG(taste_score) as avg_score
            FROM daily_packs
            WHERE status = 'published'
            AND date >= date('now', ? || ' days')
            GROUP BY theme
            ORDER BY cnt DESC LIMIT 1""",
            (f"-{days}",),
        )
        row = await cursor.fetchone()
        if row:
            return {"name": row["theme"], "count": row["cnt"], "avg_score": row["avg_score"]}
        return None

    @staticmethod
    def _row_to_pack(row) -> DailyPack:
        return DailyPack(
            id=row["id"],
            date=row["date"],
            theme=row["theme"],
            why_today=row["why_today"],
            title_options=json.loads(row["title_options_json"] or "[]"),
            caption=row["caption"],
            taste_score=row["taste_score"],
            status=PackStatus(row["status"]),
            created_at=row["created_at"],
            selected_at=row["selected_at"],
            published_at=row["published_at"],
        )
