import uuid
from datetime import datetime

from taste_graph_ai.config import DISCOVERY_MAX_SOURCES_PER_RUN
from taste_graph_ai.domain.enums import SourceType, SourceStatus
from taste_graph_ai.domain.models import Source
from taste_graph_ai.infrastructure.crawlers.arena import ArenaCrawler
from taste_graph_ai.infrastructure.crawlers.unsplash import UnsplashCrawler
from taste_graph_ai.infrastructure.crawlers.base import DiscoveredSource
from taste_graph_ai.infrastructure.ai.claude import ClaudeClient
from taste_graph_ai.infrastructure.repos.sources import SourceRepository
from taste_graph_ai.infrastructure.db.event_log import EventLog


class DiscoveryService:
    """Orchestrates source discovery from multiple crawlers."""

    def __init__(
        self,
        source_repo: SourceRepository,
        event_log: EventLog,
        claude: ClaudeClient = None,
    ):
        self.source_repo = source_repo
        self.event_log = event_log
        self.claude = claude

    async def run_discovery(self) -> list[Source]:
        """Run all crawlers and return newly discovered sources."""
        crawlers = [ArenaCrawler(), UnsplashCrawler()]
        all_discovered: list[DiscoveredSource] = []

        for crawler in crawlers:
            try:
                results = await crawler.discover()
                all_discovered.extend(results)
            except Exception as e:
                self.event_log.append("discovery.crawler_error", {
                    "crawler": type(crawler).__name__,
                    "error": str(e),
                })
            finally:
                await crawler.close()

        # Filter duplicates and evaluate
        new_sources = []
        for ds in all_discovered[:DISCOVERY_MAX_SOURCES_PER_RUN]:
            existing = await self.source_repo.find_by_url(ds.url)
            if existing:
                continue

            # AI evaluation
            ai_score = 0.5
            ai_reason = ""
            ai_risk = ""
            if self.claude:
                try:
                    eval_result = await self.claude.evaluate_source(
                        ds.url, ds.name,
                        ds.raw_metadata.get("bio", "") or ds.raw_metadata.get("description", ""),
                    )
                    ai_score = eval_result.get("score", 0.5)
                    ai_reason = eval_result.get("reason", "")
                    ai_risk = eval_result.get("risk", "")
                except Exception:
                    pass

            source = Source(
                id=uuid.uuid4().hex[:12],
                url=ds.url,
                name=ds.name,
                source_type=SourceType(ds.source_type),
                discovered_from=ds.discovered_from,
                preview_thumbnails=ds.preview_thumbnails,
                ai_score=ai_score,
                ai_reason=ai_reason,
                ai_risk=ai_risk,
            )
            await self.source_repo.save(source)
            new_sources.append(source)
            self.event_log.append("discovery.source_found", {
                "id": source.id,
                "url": source.url,
                "name": source.name,
                "score": ai_score,
            })

        return new_sources
