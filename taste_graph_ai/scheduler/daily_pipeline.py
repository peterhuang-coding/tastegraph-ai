#!/usr/bin/env python3
"""Daily pipeline: discover sources, score content, generate packs, create tasks.

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
from taste_graph_ai.infrastructure.ai.client import AIClient
from taste_graph_ai.services.discovery import DiscoveryService
from taste_graph_ai.services.tasks import TaskService


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

        # 1. Discovery
        print("[1/3] Running discovery engine...")
        discovery = DiscoveryService(source_repo, event_log, ai)
        new_sources = await discovery.run_discovery()
        print(f"  Found {len(new_sources)} new sources")

        # 2. Generate daily tasks
        print("[2/3] Generating daily tasks...")
        task_service = TaskService(source_repo, pack_repo, task_repo, event_log)
        tasks = await task_service.persist_daily_tasks()
        print(f"  Generated {len(tasks)} tasks")

        # 3. Score/generate daily packs (placeholder until full pipeline)
        print("[3/3] Daily pack generation (placeholder)...")
        print("  Done. Check http://localhost:8787 for review.")

        event_log.append("pipeline.completed", {
            "new_sources": len(new_sources),
            "tasks": len(tasks),
        })

    finally:
        await ai.close()
        await db.close()

    print("Daily pipeline complete.")


if __name__ == "__main__":
    asyncio.run(run())
