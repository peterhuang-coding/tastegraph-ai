import uuid
from datetime import datetime, timezone
from pathlib import Path

from taste_graph_ai.config import IMAGES_DIR, DAILY_IMAGES_PER_PACK
from taste_graph_ai.domain.enums import ImageStatus, SourceStatus, UserAction
from taste_graph_ai.domain.models import Image, PackImage, ScrapeFailure
from taste_graph_ai.infrastructure.repos.images import ImageRepository
from taste_graph_ai.infrastructure.repos.sources import SourceRepository
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.repos.feedback import FeedbackRepository
from taste_graph_ai.infrastructure.repos.scrape_failures import ScrapeFailureRepository
from taste_graph_ai.infrastructure.crawlers.web import WebCrawler
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.container import get_container

import random


class ImageFetchService:
    """Scrapes images from approved sources and matches them to daily packs."""

    def __init__(
        self,
        image_repo: ImageRepository,
        source_repo: SourceRepository,
        pack_repo: PackRepository,
        feedback_repo: FeedbackRepository,
        event_log: EventLog,
        failure_repo: ScrapeFailureRepository = None,
    ):
        self.image_repo = image_repo
        self.source_repo = source_repo
        self.pack_repo = pack_repo
        self.feedback_repo = feedback_repo
        self.event_log = event_log
        self.failure_repo = failure_repo
        self._enriched_sources: set[str] = set()  # Track which sources have been AI-enriched
        self._stale_tracker = self._load_stale_tracker()  # Track zero-yield streaks

    @staticmethod
    def _load_stale_tracker() -> dict:
        import json
        path = Path(__file__).resolve().parent.parent.parent / "data" / "source_yield.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    @staticmethod
    def _save_stale_tracker(tracker: dict) -> None:
        import json
        path = Path(__file__).resolve().parent.parent.parent / "data" / "source_yield.json"
        path.write_text(json.dumps(tracker, indent=2, ensure_ascii=False))

    async def scrape_approved_sources(
        self, limit_per_source: int = 50, concurrency: int = 5
    ) -> int:
        """Scrape images from all approved sources concurrently, then enrich graph."""
        approved = await self.source_repo.list_by_status(SourceStatus.APPROVED)
        if not approved:
            return 0

        # Auto-pause sources with 3+ consecutive zero yields
        paused_count = 0
        for s in approved:
            streak = self._stale_tracker.get(s.id, 0)
            if streak >= 3:
                paused_count += 1

        active_sources = [s for s in approved if self._stale_tracker.get(s.id, 0) < 3]
        if paused_count > 0:
            print(f"  ⏸  {paused_count} sources auto-paused (3+ zero-yield streaks). {len(active_sources)} active.")
        print(f"  Scraping {len(active_sources)} active sources ({concurrency} concurrent, {limit_per_source} img/source)...")

        import asyncio
        semaphore = asyncio.Semaphore(concurrency)
        total = 0
        all_failures: list[ScrapeFailure] = []

        async def scrape_one(source):
            nonlocal total
            async with semaphore:
                crawler = WebCrawler()
                images = []
                try:
                    # Phase A: BS4 static scraper (fast, works for most sites)
                    images = await crawler.scrape_and_download(
                        source_url=source.url,
                        source_name=source.name,
                        image_repo=self.image_repo,
                        limit=limit_per_source,
                        source_id=source.id,
                    )

                    # Phase B: If BS4 found < 3 images, try Playwright (JS-heavy sites)
                    if len(images) < 3:
                        try:
                            from taste_graph_ai.infrastructure.crawlers.playwright_crawler import PlaywrightCrawler
                            pw = PlaywrightCrawler()
                            pw_discovered = await pw.fetch_images(source.url, limit=limit_per_source)
                            if pw_discovered:
                                pw_images = await self._download_playwright_images(
                                    pw_discovered, source, crawler, limit_per_source
                                )
                                # Merge, avoiding URL duplicates
                                existing_urls = {img.url for img in images}
                                for img in pw_images:
                                    if img.url not in existing_urls:
                                        images.append(img)
                                        existing_urls.add(img.url)
                                if len(pw_images) > 0:
                                    print(f"    {source.name}: +{len(pw_images)} via Playwright")
                            await pw.close()
                        except Exception:
                            pass

                    n = len(images)
                    total += n
                    if n > 0:
                        print(f"    {source.name}: {n} images")
                    # Track zero-yield streaks for auto-pause
                    prev = self._stale_tracker.get(source.id, 0)
                    self._stale_tracker[source.id] = 0 if n > 0 else prev + 1
                    self.event_log.append("images.scraped", {
                        "source_id": source.id,
                        "source_name": source.name,
                        "count": n,
                        "failures": len(crawler.failures),
                        "zero_yield_streak": self._stale_tracker[source.id],
                    })
                    for f in crawler.failures:
                        all_failures.append(ScrapeFailure(
                            id=uuid.uuid4().hex[:12],
                            source_id=source.id,
                            source_name=source.name,
                            url=f["url"][:500],
                            reason=f["reason"],
                            detail=f["detail"][:300],
                        ))
                    return source, images
                except Exception as e:
                    self.event_log.append("images.scrape_error", {
                        "source_id": source.id,
                        "source_name": source.name,
                        "error": str(e),
                    })
                    return source, images
                finally:
                    await crawler.close()

        # Phase 1: Concurrent scraping (only active sources)
        results = await asyncio.gather(*[scrape_one(s) for s in active_sources])

        # Save stale tracker for next run
        self._save_stale_tracker(self._stale_tracker)

        # Phase 2: AI entity enrichment (sequential to respect API rate limits)
        from taste_graph_ai.infrastructure.ai.client import AIClient
        ai = AIClient()
        enrichment_crawler = WebCrawler()
        entities_added = 0

        for source, images in results:
            if not images or source.name in self._enriched_sources:
                continue
            try:
                page_meta = await enrichment_crawler.fetch_page_metadata(source.url)
                if page_meta.get("title"):
                    entities = await ai.extract_entities(
                        page_title=page_meta.get("title", ""),
                        page_description=page_meta.get("description", ""),
                        alt_texts=page_meta.get("alt_texts", []),
                    )
                    new_nodes = get_container().taste_graph.enrich_from_content(
                        source.name, entities
                    )
                    entities_added += new_nodes
                    self._enriched_sources.add(source.name)
                    if new_nodes > 0:
                        self.event_log.append("graph.enriched", {
                            "source_name": source.name,
                            "new_nodes": new_nodes,
                            "entities": entities,
                        })
            except Exception as e:
                self.event_log.append("graph.enrich_error", {
                    "source_name": source.name,
                    "error": str(e),
                })

        await enrichment_crawler.close()
        await ai.close()

        # Save all failures
        if self.failure_repo:
            for f in all_failures:
                await self.failure_repo.save(f)

        # Persist CLIP embeddings and graph after scrape + enrichment batch
        try:
            from taste_graph_ai.services.clip import get_clip
            get_clip().save()
            get_container().save_graph()
        except Exception:
            pass

        return total

    async def _download_playwright_images(
        self, discovered: list[dict], source, crawler, limit: int
    ) -> list[Image]:
        """Download images found by Playwright crawler and save to DB.
        Reuses the BS4 crawler's HTTP client for downloads."""
        import uuid as _uuid
        from taste_graph_ai.domain.models import Image as ImageModel
        from taste_graph_ai.domain.enums import ImageStatus
        from taste_graph_ai.config import IMAGES_DIR

        images = []
        for d in discovered[:limit]:
            url = d["url"]
            existing = await self.image_repo.get_by_url(url)
            if existing:
                continue

            img_id = _uuid.uuid4().hex[:12]
            ext = self._guess_ext(url)
            filename = f"{img_id}{ext}"
            filepath = IMAGES_DIR / filename
            local_path = ""

            try:
                r = await crawler.client.get(url)
                if r.status_code == 200:
                    filepath.write_bytes(r.content)
                    if self._check_dimensions_sync(filepath):
                        local_path = str(filepath)
                    else:
                        filepath.unlink(missing_ok=True)
                        continue
                else:
                    continue
            except Exception:
                continue

            img = ImageModel(
                id=img_id,
                source_id=source.id,
                url=url,
                page_url=d.get("page_url", source.url),
                local_path=local_path,
                thumbnail_path="",
                keywords=[],
                graph_score=0.5,
                visual_score=0.5,
                final_score=0.5,
                status=ImageStatus.PENDING,
            )
            await self.image_repo.save(img)

            # Pre-compute CLIP embedding
            try:
                from taste_graph_ai.services.clip import get_clip
                get_clip().embed_image(local_path)
            except Exception:
                pass

            images.append(img)

        return images

    @staticmethod
    def _guess_ext(url: str) -> str:
        from urllib.parse import urlparse
        path = urlparse(url).path.lower()
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            if path.endswith(ext):
                return ext
        return ".jpg"

    @staticmethod
    def _check_dimensions_sync(filepath) -> bool:
        try:
            from PIL import Image as PILImage
            with PILImage.open(filepath) as img:
                w, h = img.size
                return min(w, h) >= 200  # lowered for design archives
        except Exception:
            return True

    async def pick_for_pack(
        self, pack_id: str, theme: str, count: int = None, exclude_ids: set[str] = None
    ) -> list[Image]:
        """Pick diverse images from the pool, matching the theme."""
        if count is None:
            count = DAILY_IMAGES_PER_PACK
        if exclude_ids is None:
            exclude_ids = set()

        available = await self.image_repo.list_by_status(ImageStatus.PENDING, limit=200)
        if not available:
            return []

        # Exclude already-used images AND images without local file
        available = [img for img in available if img.id not in exclude_ids and img.local_path]
        if not available:
            return []

        # Load previously liked images for scoring bonus
        liked_ids = await self.feedback_repo.get_liked_image_ids()

        # Score each image against the theme
        scored = []
        for img in available:
            score = self._score_image_for_theme(img, theme, liked_ids)
            scored.append((score, img))

        # Sort by score, add noise for diversity
        random.seed(hash(pack_id))
        scored.sort(key=lambda x: (x[0], random.random()), reverse=True)

        # Pick top N unique-by-URL images
        seen_urls: set[str] = set()
        selected = []
        for _, img in scored:
            if img.url in seen_urls:
                continue
            seen_urls.add(img.url)
            selected.append(img)
            if len(selected) >= count:
                break

        # Link selected images to pack
        for i, img in enumerate(selected):
            pi = PackImage(
                pack_id=pack_id,
                image_id=img.id,
                position=i,
                user_action=UserAction.APPROVED,
            )
            await self.pack_repo.save_pack_image(pi)

        # Mark images as SELECTED so they won't re-appear in future picks
        await self.image_repo.mark_many_status(
            [img.id for img in selected], ImageStatus.SELECTED
        )

        return selected

    def _score_image_for_theme(self, img: Image, theme: str, liked_ids: set[str] = None) -> float:
        """Score an image against a theme string, with bonus for user-liked images,
        exploration bonus for new sources, and CLIP visual similarity."""
        text = f"{' '.join(img.keywords)} {img.url}"
        score = 0.0

        # 1) CLIP visual similarity (30% weight)
        clip_score = self._clip_visual_score(img, theme)
        score += 0.3 * clip_score

        # 2) Character-level overlap for Chinese themes (20% weight)
        theme_chars = set(theme)
        kw_chars = set(text)
        char_overlap = len(theme_chars & kw_chars)
        if char_overlap > 0:
            score += 0.2 * min(char_overlap / max(len(theme_chars), 1), 1.0)

        # 3) Quality markers (10% weight)
        quality_markers = ["photo", "image", "jpg", "editorial", "fashion",
                           "style", "runway", "lookbook", "magazine"]
        text_lower = text.lower()
        quality_hits = sum(1 for m in quality_markers if m in text_lower)
        score += 0.1 * min(quality_hits / 4, 1.0)

        # 4) User previously liked (15% bonus)
        if liked_ids and img.id in liked_ids:
            score += 0.15

        # 5) Exploration bonus: give new/underexplored sources visibility (15% max)
        score += 0.15 * (self._exploration_bonus(img) / 0.25) if self._exploration_bonus(img) > 0 else 0

        # 6) Graph-based taste score (10% weight)
        graph_score = self._graph_taste_score(img, theme)
        score += 0.1 * graph_score

        return score

    @staticmethod
    def _clip_visual_score(img: Image, theme: str) -> float:
        """Compute CLIP cosine similarity between image and theme text."""
        if not img.local_path:
            return 0.5
        try:
            from taste_graph_ai.services.clip import get_clip
            clip_svc = get_clip()
            return clip_svc.compute_similarity(img.local_path, theme)
        except Exception:
            return 0.5

    @staticmethod
    def _graph_taste_score(img: Image, theme: str) -> float:
        """Score image using taste graph concept matching."""
        try:
            from taste_graph_ai.container import get_container
            graph = get_container().taste_graph
            keywords = list(img.keywords) + [theme]
            raw = graph.score_content(
                keywords=keywords,
                source_id=getattr(img, 'source_id', '') or '',
            )
            return max(0.3, min(1.0, raw / 10))
        except Exception:
            return 0.5

    @staticmethod
    def _exploration_bonus(img: Image) -> float:
        """Sources with few or no taste-graph connections get a boost so
        newly-added sources (BranD, Dieter Rams, Saeki, etc.) aren't buried."""
        try:
            from taste_graph_ai.container import get_container
            graph = get_container().taste_graph
            source_name = getattr(img, 'source_name', '') or ''
            # Look up source node by name or source_id
            source_id = getattr(img, 'source_id', '') or ''
            node_id = source_id if source_id in graph else source_name

            if node_id and node_id in graph.graph:
                edge_count = sum(1 for _ in graph.graph.in_edges(node_id))
                if edge_count == 0:
                    return 0.25  # Pure exploration — never-seen source
                elif edge_count < 3:
                    return 0.10  # Underexplored source
                return 0.0
        except Exception:
            pass
        return 0.0

    async def close(self):
        pass
