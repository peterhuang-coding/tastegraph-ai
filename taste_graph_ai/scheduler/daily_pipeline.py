#!/usr/bin/env python3
"""Daily pipeline: discover sources, scrape images, generate packs, create tasks.

Run this via launchd every morning at 08:00.
Can also be triggered manually via API.

Usage:
    python -m taste_graph_ai.scheduler.daily_pipeline
"""

import asyncio
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from taste_graph_ai.container import get_container
from taste_graph_ai.config import ensure_dirs
from taste_graph_ai.infrastructure.db.connection import init_db, get_db
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.infrastructure.repos.sources import SourceRepository
from taste_graph_ai.infrastructure.repos.tasks import TaskRepository
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.images import ImageRepository
from taste_graph_ai.infrastructure.repos.feedback import FeedbackRepository
from taste_graph_ai.infrastructure.repos.scrape_failures import ScrapeFailureRepository
from taste_graph_ai.infrastructure.ai.client import AIClient
from taste_graph_ai.services.discovery import DiscoveryService
from taste_graph_ai.services.tasks import TaskService
from taste_graph_ai.services.images import ImageFetchService
from taste_graph_ai.services.generator import PackGenerationService
from taste_graph_ai.services.source_sync import sync_seed_sources

# Batch constants
SCRAPE_CONCURRENCY = 5          # concurrent source scrapes
SCRAPE_LIMIT_PER_SOURCE = 50    # images to attempt per source
PACK_COUNT_OVERRIDE = 5         # generate more packs with more images


async def run():
    ensure_dirs()
    await init_db()
    get_container()  # Init graph

    db = await get_db()
    event_log = EventLog()
    ai = AIClient()

    try:
        source_repo = SourceRepository(db)
        task_repo = TaskRepository(db)
        pack_repo = PackRepository(db)
        image_repo = ImageRepository(db)
        feedback_repo = FeedbackRepository(db)
        failure_repo = ScrapeFailureRepository(db)
        img_service = ImageFetchService(image_repo, source_repo, pack_repo, feedback_repo, event_log, failure_repo)

        # 0. Sync seed sources from link_sources.json → DB
        print("[0/5] Syncing seed sources to DB...")
        synced = await sync_seed_sources(source_repo, event_log)
        print(f"  Synced {synced} new sources from link_sources.json")

        # 1. Discovery
        print("[1/5] Running discovery engine...")
        discovery = DiscoveryService(source_repo, event_log, ai)
        new_sources = await discovery.run_discovery()
        print(f"  Found {len(new_sources)} new sources")

        # 2. Scrape images from approved sources (concurrent)
        print(f"[2/5] Scraping images from approved sources (concurrency={SCRAPE_CONCURRENCY}, limit={SCRAPE_LIMIT_PER_SOURCE})...")
        img_count = await img_service.scrape_approved_sources(
            limit_per_source=SCRAPE_LIMIT_PER_SOURCE,
            concurrency=SCRAPE_CONCURRENCY,
        )
        print(f"  Scraped {img_count} new images")

        # 3. Generate daily packs
        print("[3/5] Generating daily packs...")
        gen = PackGenerationService(pack_repo, event_log, ai, img_service)
        packs = await gen.generate_daily_packs()
        for p in packs:
            print(f"  Pack: {p.theme} (score: {p.taste_score})")

        # 4. Generate daily tasks
        print("[4/5] Generating daily tasks...")
        task_service = TaskService(source_repo, pack_repo, task_repo, event_log)
        tasks = await task_service.persist_daily_tasks()
        for t in tasks:
            print(f"  Task: [{t.priority.value}] {t.title}")

        # 5. Optional auto-publish (if --auto-publish passed)
        if "--auto-publish" in sys.argv and packs:
            print("[5/5] Auto-publishing best pack...")
            try:
                from modules.xhs_publisher.composer import MoodboardComposer
                from modules.xhs_publisher.publisher import XiaohongshuPublisher
                from taste_graph_ai.config import XHS_COOKIES_FILE
                best = max(packs, key=lambda p: p.taste_score)
                imgs = await pack_repo.get_pack_images(best.id)
                paths = [i["local_path"] for i in imgs if i.get("local_path")]
                if paths:
                    composer = MoodboardComposer()
                    title = best.title_options[0] if best.title_options else best.theme
                    export_path = composer.compose(
                        image_paths=paths, theme=best.theme, caption=best.caption, title=title,
                    )
                    async with XiaohongshuPublisher(cookies_path=XHS_COOKIES_FILE) as publisher:
                        post_url = await publisher.publish(str(export_path), title, best.caption)
                    best.publish()
                    await pack_repo.save(best)
                    print(f"  Published: {post_url}")
            except Exception as e:
                print(f"  Auto-publish failed: {e}")

        event_log.append("pipeline.completed", {
            "new_sources": len(new_sources),
            "images": img_count,
            "packs": len(packs),
            "tasks": len(tasks),
        })

        # Persist taste graph to disk (auto-save after each pipeline run)
        get_container().save_graph()
        print("  Graph saved to disk.")

    finally:
        await ai.close()
        await db.close()

    print("\nDaily pipeline complete.")
    print(f"  Sources: {new_sources if 'new_sources' in dir() else 0}")
    print(f"  Images: {img_count if 'img_count' in dir() else 0}")
    print(f"  Packs: {len(packs) if 'packs' in dir() else 0}")
    print(f"  Tasks: {len(tasks) if 'tasks' in dir() else 0}")


if __name__ == "__main__":
    asyncio.run(run())
