#!/usr/bin/env python3
"""Periodic scraper: runs frequently to keep the image pool fresh.

Unlike the daily pipeline, this only scrapes images — no AI generation.
Designed to run every 2-3 hours via launchd.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from taste_graph_ai.config import ensure_dirs
from taste_graph_ai.infrastructure.db.connection import init_db, get_db
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.infrastructure.repos.sources import SourceRepository
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.images import ImageRepository
from taste_graph_ai.infrastructure.repos.feedback import FeedbackRepository
from taste_graph_ai.infrastructure.repos.scrape_failures import ScrapeFailureRepository
from taste_graph_ai.services.images import ImageFetchService


async def run():
    ensure_dirs()
    await init_db()

    db = await get_db()
    event_log = EventLog()

    try:
        source_repo = SourceRepository(db)
        pack_repo = PackRepository(db)
        image_repo = ImageRepository(db)
        feedback_repo = FeedbackRepository(db)
        failure_repo = ScrapeFailureRepository(db)
        img_service = ImageFetchService(image_repo, source_repo, pack_repo, feedback_repo, event_log, failure_repo)

        count = await img_service.scrape_approved_sources()
        print(f"Scraped {count} new images")
        event_log.append("scrape_cron.completed", {"images": count})

    finally:
        await db.close()

    print(f"Scrape cron done: {count} images")


if __name__ == "__main__":
    asyncio.run(run())
