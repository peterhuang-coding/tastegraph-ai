import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from taste_graph_ai.config import BASE_DIR, DB_FILE, IMAGES_DIR, DAILY_IMAGES_PER_PACK
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


def _load_published_image_ids() -> set[str]:
    """Read registered/submitted images from the configured log and DB, without writes."""
    import json
    import sqlite3
    from contextlib import closing
    from taste_graph_ai.services.publication_records import canonical_pack_path

    ids, pack_ids = set(), set()
    log_path = Path(DB_FILE).parent / "publish_log.json"
    if log_path.is_file():
        entries = json.loads(log_path.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise ValueError("publish_log.json must contain a list")
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("pack_id"):
                pack_ids.add(entry["pack_id"])
            pack_ref = entry.get("pack") or entry.get("pack_path") or ""
            if not pack_ref:
                continue
            if "/" not in pack_ref and "\\" not in pack_ref:
                pack_ids.add(pack_ref)
                continue
            try:
                directory, _ = canonical_pack_path(pack_ref, BASE_DIR)
            except ValueError:
                continue
            metadata_path = directory / "curation.json"
            if metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                ids.update(metadata.get("image_ids", []))
                if metadata.get("pack_id"):
                    pack_ids.add(metadata["pack_id"])

    if Path(DB_FILE).is_file():
        uri = Path(DB_FILE).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            # Confirmation rows are deleted by undo-publish; every remaining
            # row records an image the operator has confirmed as published.
            if "image_post_log" in tables:
                ids.update(row[0] for row in db.execute("SELECT DISTINCT image_id FROM image_post_log"))
            if "daily_packs" in tables:
                pack_ids.update(row[0] for row in db.execute("SELECT id FROM daily_packs WHERE status='published'"))
            if "publish_history" in tables:
                pack_ids.update(row[0] for row in db.execute("SELECT pack_id FROM publish_history"))
            if "publication_observations" in tables:
                pack_ids.update(row[0] for row in db.execute(
                    "SELECT pack_id FROM publication_observations WHERE publication_status IN ('published','under_review')"))
            if "pack_images" in tables and pack_ids:
                ids.update(image_id for pack_id, image_id in db.execute(
                    "SELECT pack_id,image_id FROM pack_images") if pack_id in pack_ids)
    return ids


def _image_content_hash(img: Image) -> str | None:
    if not img.local_path:
        return None
    try:
        return hashlib.sha256(Path(img.local_path).read_bytes()).hexdigest()
    except OSError:
        return None


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
        """Link one topic/page candidate group, awaiting the operator's review.

        `theme` remains accepted for callers; candidates are grouped by evidence
        and annotations instead of character overlap with a generated title.
        `count` is a maximum, never a reason to add unrelated images.
        """
        from taste_graph_ai.services.editorial import (
            choose_candidate_groups, load_annotations, score_candidate,
        )

        if count is None:
            count = DAILY_IMAGES_PER_PACK
        if count <= 0:
            return []
        excluded = set(exclude_ids or ()) | _load_published_image_ids()
        excluded_urls, excluded_hashes = set(), set()
        # Resolve excluded IDs independently of candidate status: a published
        # original may be rejected/archived while a second ID has identical bytes.
        for image_id in excluded:
            used = await self.image_repo.get_by_id(image_id)
            if used is None:
                continue
            if used.url:
                excluded_urls.add(used.url)
            digest = _image_content_hash(used)
            if digest is not None:
                excluded_hashes.add(digest)
        available = []
        for status in (ImageStatus.PENDING, ImageStatus.SELECTED):
            page = 1
            while True:
                batch, total = await self.image_repo.list_by_status_paginated(
                    status, page=page, limit=500, require_local_file=True,
                )
                for img in batch:
                    if (img.id in excluded or img.url in excluded_urls
                            or not img.local_path or not Path(img.local_path).is_file()):
                        continue
                    if excluded_hashes:
                        digest = _image_content_hash(img)
                        if digest is None or digest in excluded_hashes:
                            continue
                    available.append(img)
                if not batch or page * 500 >= total:
                    break
                page += 1
        if not available:
            return []

        annotations = load_annotations(DB_FILE)
        liked_ids = await self.feedback_repo.get_liked_image_ids()
        graph = get_container().taste_graph
        scored = [
            {"img": img, **score_candidate(img, graph, annotations.get(img.id), liked_ids)}
            for img in available
        ]
        groups = choose_candidate_groups(
            scored, count=1, pack_size=count, annotations=annotations, exclude_ids=excluded,
        )
        selected = [item["img"] for item in groups[0]] if groups else []
        for position, img in enumerate(selected):
            await self.pack_repo.save_pack_image(PackImage(
                pack_id=pack_id,
                image_id=img.id,
                position=position,
                user_action=UserAction.UNREVIEWED,
            ))
        if selected:
            await self.image_repo.mark_many_status(
                [img.id for img in selected], ImageStatus.SELECTED,
            )
        return selected

    def _score_image_for_theme(self, img: Image, theme: str, liked_ids: set[str] = None) -> float:
        """Compatibility wrapper for the shared candidate score."""
        from taste_graph_ai.services.editorial import score_candidate
        return score_candidate(img, get_container().taste_graph, liked_ids=liked_ids)["total"]

    async def close(self):
        pass
