"""BS4 + httpx web crawler for image scraping from any web page.

Scrapes images from fashion/design/editorial sites. Handles pagination
discovery, article-link extraction, image download with dimension validation,
and CLIP embedding pre-computation.

Uses shared utilities from .utils and stealth helpers from .stealth.
"""

import asyncio
import random
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from taste_graph_ai.config import IMAGES_DIR
from taste_graph_ai.domain.enums import ImageStatus
from taste_graph_ai.domain.models import Image
from taste_graph_ai.infrastructure.crawlers.base import Crawler, DiscoveredSource
from taste_graph_ai.infrastructure.crawlers.utils import (
    IMAGE_EXTENSIONS,
    MIN_IMAGE_DIMENSION,
    SKIP_PAGE_PATTERNS,
    best_srcset_url,
    check_dimensions,
    clean_alt_text,
    generate_image_filename,
    guess_ext,
    is_bad_url,
    is_image_url,
    is_likely_content_image,
    normalize_url,
    upgrade_cdn_url,
)
from taste_graph_ai.infrastructure.repos.images import ImageRepository
from taste_graph_ai.infrastructure.repos.scrape_failures import ScrapeFailureRepository

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class WebCrawler(Crawler):
    """Scrapes images from specific web pages (Vogue, SSENSE, magazines, etc.)."""

    def __init__(self, failure_repo: ScrapeFailureRepository | None = None):
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            },
            timeout=30,
            follow_redirects=True,
        )
        self.failures: list[dict] = []
        self._failure_repo = failure_repo

    async def discover(self) -> list[DiscoveredSource]:
        return []

    async def fetch_images(self, source_url: str, limit: int = 20) -> list[dict]:
        """Visit a page and extract all images."""
        html = await self._fetch_page(source_url)
        if not html:
            return []
        return self._extract_images(html, source_url, limit)

    async def scrape_and_download(
        self,
        source_url: str,
        source_name: str,
        image_repo: ImageRepository,
        limit: int = 50,
        source_id: str = "",
        max_pages: int = 15,
    ) -> list[Image]:
        """Scrape images from a source: discover article links from listing page(s),
        follow pagination, then scrape images from each article. Downloads and saves to DB."""
        # Phase 1: collect article URLs from listing page + pagination
        all_article_urls = []
        listing_urls = self._generate_pagination_urls(source_url, depth=5)

        for listing_url in listing_urls:
            if len(all_article_urls) >= max_pages:
                break
            try:
                links = await self._discover_article_links(
                    listing_url, max_pages - len(all_article_urls)
                )
                for link in links:
                    if link not in all_article_urls:
                        all_article_urls.append(link)
            except Exception as exc:
                self._add_failure(listing_url, "article_discovery_failed", str(exc)[:200])

        if not all_article_urls:
            all_article_urls = [source_url]

        # Phase 2: scrape images from each article
        all_discovered = []
        for article_url in all_article_urls:
            if len(all_discovered) >= limit:
                break
            try:
                page_images = await self.fetch_images(
                    article_url, limit=limit - len(all_discovered)
                )
                for d in page_images:
                    d["page_url"] = article_url
                all_discovered.extend(page_images)
            except Exception as exc:
                self._add_failure(article_url, "article_scrape_failed", str(exc)[:200])

        images = []

        for i, d in enumerate(all_discovered):
            # Skip if this URL already exists in the database
            existing = await image_repo.get_by_url(d["url"])
            if existing:
                continue

            filename = generate_image_filename(d["url"])
            filepath = IMAGES_DIR / filename

            local_path = ""
            try:
                r = await self.client.get(d["url"])
                if r.status_code == 200:
                    filepath.write_bytes(r.content)
                    if check_dimensions(filepath):
                        local_path = str(filepath)
                    else:
                        filepath.unlink(missing_ok=True)
                        self._add_failure(
                            d["url"], "image_too_small",
                            f"dimensions < {MIN_IMAGE_DIMENSION}px",
                        )
                        continue
                else:
                    self._add_failure(
                        d["url"], "image_download_failed",
                        f"HTTP {r.status_code}",
                    )
                    continue
            except Exception as exc:
                self._add_failure(d["url"], "image_download_failed", str(exc)[:200])

            img = Image(
                id=filename.split(".")[0],
                source_id=source_id,
                url=d["url"],
                page_url=d.get("page_url", source_url),
                local_path=local_path,
                thumbnail_path=d.get("thumbnail", ""),
                keywords=d.get("keywords", []),
                graph_score=0.5,
                visual_score=0.5,
                final_score=0.5,
                status=ImageStatus.PENDING,
            )
            await image_repo.save(img)

            # Pre-compute CLIP embedding for visual scoring
            try:
                from taste_graph_ai.services.clip import get_clip
                clip_svc = get_clip()
                clip_svc.embed_image(local_path)
            except Exception as exc:
                self._add_failure(d["url"], "clip_embed_failed", str(exc)[:200])

            images.append(img)

        return images

    async def fetch_page_metadata(self, url: str) -> dict:
        """Extract page title, description and image alt texts for AI entity extraction."""
        html = await self._fetch_page(url)
        if not html:
            return {}
        try:
            soup = BeautifulSoup(html, "html.parser")
            title = ""
            if soup.find("title"):
                title = soup.find("title").get_text(strip=True)
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"] or title

            description = ""
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                description = meta_desc["content"]
            og_desc = soup.find("meta", property="og:description")
            if og_desc and og_desc.get("content"):
                description = og_desc["content"] or description

            alt_texts = []
            for img in soup.find_all("img", alt=True):
                alt = img["alt"].strip()
                if alt and len(alt) > 2:
                    alt_texts.append(alt)

            return {"title": title, "description": description, "alt_texts": alt_texts}
        except Exception as exc:
            self._add_failure(url, "metadata_parse_failed", str(exc)[:200])
            return {}

    # ── Pagination ──────────────────────────────────────────────

    @staticmethod
    def _generate_pagination_urls(base_url: str, depth: int = 5) -> list[str]:
        """Generate potential pagination URLs from a base listing URL.

        Generates URLs for common patterns (/page/N, ?page=N, &page=N).
        The caller should probe these and skip 404s — this is just URL generation.
        Limited to 2 pages per pattern to reduce 404 waste.
        """
        urls = [base_url]
        parsed = urlparse(base_url)
        path = parsed.path.rstrip("/")

        for n in range(2, depth + 2):
            # Pattern: /page/N/
            urls.append(urljoin(base_url, f"{path}/page/{n}/"))
            # Pattern: ?page=N or &page=N
            if not parsed.query:
                urls.append(f"{base_url}?page={n}")
            else:
                urls.append(f"{base_url}&page={n}")

            # Stop after 2 pages of each pattern to reduce 404s
            if n > 3:
                break

        return urls

    # ── Article discovery ───────────────────────────────────────

    async def _discover_article_links(
        self, page_url: str, max_links: int = 15
    ) -> list[str]:
        """From a listing/index page, discover article/story links to scrape deeper.

        Uses heuristics: same-domain links with descriptive paths.
        """
        html = await self._fetch_page(page_url)
        if not html:
            return []

        try:
            soup = BeautifulSoup(html, "html.parser")
            base_domain = urlparse(page_url).netloc
            links = []

            # Pass 1: prefer article-like paths
            for a in soup.find_all("a", href=True):
                href = normalize_url(a["href"], page_url)
                if not href or not href.startswith("http"):
                    continue

                parsed = urlparse(href)
                if parsed.netloc != base_domain:
                    continue

                path = parsed.path.strip("/").lower()
                if not path or len(path) < 4:
                    continue
                if any(skp in path for skp in SKIP_PAGE_PATTERNS):
                    continue
                if parsed.query and len(parsed.query) > 100:
                    continue

                if "/" in path or any(
                    kw in path
                    for kw in ["article", "story", "post", "news", "fashion", "style"]
                ):
                    links.append(href)
                    if len(links) >= max_links * 2:
                        break

            # Pass 2: if not enough article-like links, take any reasonable path
            if len(links) < 5:
                for a in soup.find_all("a", href=True):
                    href = normalize_url(a["href"], page_url)
                    if not href or not href.startswith("http"):
                        continue
                    parsed = urlparse(href)
                    if parsed.netloc != base_domain:
                        continue
                    path = parsed.path.strip("/").lower()
                    if not path or len(path) < 4:
                        continue
                    if any(skp in path for skp in SKIP_PAGE_PATTERNS):
                        continue
                    if href not in links:
                        links.append(href)
                    if len(links) >= max_links * 2:
                        break

            # Dedup by path
            seen = set()
            unique = []
            for link in links:
                path = urlparse(link).path
                if path not in seen:
                    seen.add(path)
                    unique.append(link)
                if len(unique) >= max_links:
                    break

            return unique
        except Exception as exc:
            self._add_failure(page_url, "article_discovery_parse_failed", str(exc)[:200])
            return []

    # ── Page fetch ──────────────────────────────────────────────

    async def _fetch_page(self, url: str) -> str | None:
        """Fetch a page with polite random delay and error tracking."""
        await asyncio.sleep(random.uniform(0.3, 1.0))
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Referer": "https://www.google.com/",
        }
        try:
            r = await self.client.get(url, headers=headers)
            if r.status_code == 200:
                return r.text
            if r.status_code == 403:
                self._add_failure(url, "page_fetch_forbidden", "HTTP 403 (anti-bot)")
            elif r.status_code >= 400:
                self._add_failure(url, "page_fetch_failed", f"HTTP {r.status_code}")
        except Exception as exc:
            self._add_failure(url, "page_fetch_failed", str(exc)[:200])
        return None

    # ── Image extraction ────────────────────────────────────────

    def _extract_images(self, html: str, page_url: str, limit: int) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        images = []
        seen = set()

        # 1. og:image (highest priority — usually the main editorial image)
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            url = normalize_url(og_img["content"], page_url)
            if url and url not in seen and not is_bad_url(url):
                seen.add(url)
                images.append({
                    "url": upgrade_cdn_url(url), "thumbnail": "", "keywords": [],
                })

        # 2. twitter:image
        tw_img = soup.find("meta", attrs={"name": "twitter:image"})
        if tw_img and tw_img.get("content"):
            url = normalize_url(tw_img["content"], page_url)
            if url and url not in seen and not is_bad_url(url):
                seen.add(url)
                images.append({
                    "url": upgrade_cdn_url(url), "thumbnail": "", "keywords": [],
                })

        # 3. All <img> tags
        for img in soup.find_all("img"):
            if len(images) >= limit:
                break
            src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src")
                or ""
            )
            if not src:
                continue
            src = normalize_url(src, page_url)
            if not src or src in seen:
                continue
            if is_bad_url(src):
                self._add_failure(src, "bad_url_skipped", "matches low-quality pattern")
                continue
            seen.add(src)

            src = upgrade_cdn_url(src)
            alt = img.get("alt", "")
            keywords = clean_alt_text(alt)
            images.append({"url": src, "thumbnail": "", "keywords": keywords})

        # 4. srcset for higher-res versions
        for img in soup.find_all("img"):
            srcset = img.get("srcset", "")
            if srcset:
                best = best_srcset_url(srcset, page_url)
                if best and best not in seen and not is_bad_url(best):
                    seen.add(best)
                    best = upgrade_cdn_url(best)
                    images.append({"url": best, "thumbnail": "", "keywords": []})

        # 5. Picture > source elements
        for source in soup.find_all("source"):
            srcset = source.get("srcset", "")
            if srcset:
                best = best_srcset_url(srcset, page_url)
                if best and best not in seen and not is_bad_url(best):
                    seen.add(best)
                    best = upgrade_cdn_url(best)
                    images.append({"url": best, "thumbnail": "", "keywords": []})

        # Filter to direct image URLs
        for i in images:
            if not is_image_url(i["url"]):
                self._add_failure(
                    i["url"], "not_image_url", "no image extension or photo in path"
                )
        images = [i for i in images if is_image_url(i["url"])]
        return images[:limit]

    # ── Failure tracking ────────────────────────────────────────

    def _add_failure(self, url: str, reason: str, detail: str = "") -> None:
        """Record a scrape failure for later analysis and DB persistence."""
        self.failures.append({"url": url, "reason": reason, "detail": detail})

    # ── Cleanup ─────────────────────────────────────────────────

    async def close(self):
        await self.client.aclose()
