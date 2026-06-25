"""Sync seed sources from link_sources.json into the DB source table.

Ensures all sources defined in link_sources.json are present in the SQLite
sources table with APPROVED status, so the daily pipeline actually scrapes them.

Call sync_seed_sources() once at pipeline start — idempotent.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from taste_graph_ai.config import BASE_DIR
from taste_graph_ai.domain.enums import SourceType, SourceStatus
from taste_graph_ai.domain.models import Source


# Map link_sources.json categories to SourceType
CATEGORY_TYPE_MAP = {
    "lookbook_images": SourceType.LOOKBOOK,
    "videos": SourceType.VIDEO,
    "articles": SourceType.ARTICLE,
}


async def sync_seed_sources(source_repo, event_log) -> int:
    """Sync link_sources.json entries into DB. Returns count of newly added sources."""
    link_sources_path = BASE_DIR / "link_sources.json"
    if not link_sources_path.exists():
        return 0

    data = json.loads(link_sources_path.read_text(encoding="utf-8"))
    new_count = 0

    for category, sources in data.items():
        if not isinstance(sources, list):
            continue
        source_type = CATEGORY_TYPE_MAP.get(category, SourceType.MIXED)

        for src in sources:
            url = src.get("url", "")
            if not url:
                continue

            # Check if already in DB
            existing = await source_repo.find_by_url(url)
            if existing:
                # Ensure it's approved (might have been deferred/rejected before)
                if existing.status != SourceStatus.APPROVED:
                    existing.status = SourceStatus.APPROVED
                    existing.reviewed_at = datetime.now(timezone.utc).isoformat()
                    await source_repo.save(existing)
                    event_log.append("source.auto_approved", {
                        "name": existing.name,
                        "url": url,
                        "previous_status": existing.status.value,
                    })
                continue

            # New source — create as approved
            source = Source(
                id=uuid.uuid4().hex[:12],
                url=url,
                name=src.get("name", url),
                source_type=source_type,
                discovered_from="link_sources.json",
                preview_thumbnails=[],
                ai_score=1.0,
                ai_reason=src.get("why", "Seed source"),
                ai_risk="",
                status=SourceStatus.APPROVED,
                reviewer_note="Auto-approved from link_sources.json",
                created_at=datetime.now(timezone.utc).isoformat(),
                reviewed_at=datetime.now(timezone.utc).isoformat(),
            )
            await source_repo.save(source)
            new_count += 1
            event_log.append("source.synced", {
                "name": source.name,
                "url": url,
                "type": source_type.value,
            })

    return new_count
