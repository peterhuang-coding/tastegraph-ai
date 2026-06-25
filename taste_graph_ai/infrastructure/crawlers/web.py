import re
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from PIL import Image as PILImage

from taste_graph_ai.config import IMAGES_DIR
from taste_graph_ai.domain.enums import ImageStatus
from taste_graph_ai.domain.models import Image
from taste_graph_ai.infrastructure.crawlers.base import Crawler, DiscoveredSource
from taste_graph_ai.infrastructure.repos.images import ImageRepository

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MIN_IMAGE_DIMENSION = 200  # minimum width or height in pixels (lowered for design archives)

# URL patterns that indicate tiny/low-quality images
_SKIP_URL_PATTERNS = [
    "logo", "icon", "avatar", "pixel", "1x1", "tracking",
    "thumbnail", "thumb-", "-thumb", "_thumb", "favicon",
    "button-", "banner-", "sidebar-",
]

# CDN resizing patterns — strip to get original/full-size
_CDN_SIZE_PATTERNS = [
    (re.compile(r"\.width-\d+", re.I), ""),          # .width-30 → remove
    (re.compile(r"\.fill-\d+x\d+", re.I), ""),        # .fill-30x12 → remove
    (re.compile(r"\.fit-\d+x\d+", re.I), ""),         # .fit-100x100 → remove
    (re.compile(r"w_\d+,"), "w_1200,"),               # Cloudinary w_100 → w_1200
    (re.compile(r"h_\d+,"), ""),                      # Cloudinary h_100 → remove
    (re.compile(r"c_limit,"), "c_limit,"),            # keep
]


class WebCrawler(Crawler):
    """Scrapes images from specific web pages (Vogue, SSENSE, magazines, etc.)."""

    def __init__(self):
        self.client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=30,
            follow_redirects=True,
        )
        self.failures: list[dict] = []

    async def discover(self) -> list[DiscoveredSource]:
        return []

    async def fetch_images(self, source_url: str, limit: int = 20) -> list[dict]:
        """Visit a page and extract all images."""
        try:
            html = await self._fetch_page(source_url)
            if not html:
                return []
            return self._extract_images(html, source_url, limit)
        except Exception:
            return []

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
                links = await self._discover_article_links(listing_url, max_pages - len(all_article_urls))
                for link in links:
                    if link not in all_article_urls:
                        all_article_urls.append(link)
            except Exception:
                continue

        if not all_article_urls:
            all_article_urls = [source_url]

        # Phase 2: scrape images from each article
        all_discovered = []
        for article_url in all_article_urls:
            if len(all_discovered) >= limit:
                break
            try:
                page_images = await self.fetch_images(article_url, limit=limit - len(all_discovered))
                for d in page_images:
                    d["page_url"] = article_url
                all_discovered.extend(page_images)
            except Exception:
                continue

        images = []

        for i, d in enumerate(all_discovered):
            # Skip if this URL already exists in the database
            existing = await image_repo.get_by_url(d["url"])
            if existing:
                continue

            img_id = uuid.uuid4().hex[:12]
            ext = self._guess_ext(d["url"])
            filename = f"{img_id}{ext}"
            filepath = IMAGES_DIR / filename

            local_path = ""
            try:
                r = await self.client.get(d["url"])
                if r.status_code == 200:
                    filepath.write_bytes(r.content)
                    if self._check_dimensions(filepath):
                        local_path = str(filepath)
                    else:
                        filepath.unlink(missing_ok=True)
                        self._add_failure(d["url"], "image_too_small", f"dimensions < {MIN_IMAGE_DIMENSION}px")
                        continue
                else:
                    self._add_failure(d["url"], "image_download_failed", f"HTTP {r.status_code}")
                    continue
            except Exception as e:
                self._add_failure(d["url"], "image_download_failed", str(e)[:200])
                continue

            img = Image(
                id=img_id,
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
            except Exception:
                pass

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
        except Exception:
            return {}

    @staticmethod
    def _generate_pagination_urls(base_url: str, depth: int = 5) -> list[str]:
        """Generate potential pagination URLs from a base listing URL.
        Handles common patterns: /page/2, ?page=2, &page=2, ?paged=2, etc."""
        urls = [base_url]
        parsed = urlparse(base_url)

        for n in range(2, depth + 2):
            # Pattern: /page/N/
            if not parsed.path.endswith(f"/{n}") and not parsed.path.endswith(f"/{n}/"):
                path = parsed.path.rstrip("/")
                # Try appending /page/N
                urls.append(urljoin(base_url, f"{path}/page/{n}/"))
                # Try ?page=N
                if not parsed.query:
                    urls.append(f"{base_url}?page={n}")
                else:
                    urls.append(f"{base_url}&page={n}")

        return urls

    async def _discover_article_links(self, page_url: str, max_links: int = 15) -> list[str]:
        """From a listing/index page, discover article/story links to scrape deeper.

        Uses heuristics: same-domain links with descriptive paths (not /about, /contact, etc).
        Returns unique, deduplicated article URLs.
        """
        html = await self._fetch_page(page_url)
        if not html:
            return []

        try:
            soup = BeautifulSoup(html, "html.parser")
            base_domain = urlparse(page_url).netloc
            links = []

            # Skip patterns for non-article pages
            skip_patterns = [
                "about", "contact", "login", "signup", "subscribe",
                "privacy", "terms", "policy", "faq", "cart", "search",
                "account", "wishlist", "newsletter",
            ]

            for a in soup.find_all("a", href=True):
                href = self._normalize_url(a["href"], page_url)
                if not href or not href.startswith("http"):
                    continue

                parsed = urlparse(href)
                # Same domain only
                if parsed.netloc != base_domain:
                    continue

                path = parsed.path.strip("/").lower()
                # Skip homepage, short paths, admin pages
                if not path or len(path) < 4:
                    continue
                if any(skp in path for skp in skip_patterns):
                    continue
                # Skip query-heavy / filter URLs
                if parsed.query and len(parsed.query) > 100:
                    continue

                # Prefer article-like paths
                if "/" in path or any(kw in path for kw in ["article", "story", "post", "news", "fashion", "style"]):
                    links.append(href)
                    if len(links) >= max_links * 2:
                        break

            # If not enough article-like links, take any reasonable path
            if len(links) < 5:
                for a in soup.find_all("a", href=True):
                    href = self._normalize_url(a["href"], page_url)
                    if not href or not href.startswith("http"):
                        continue
                    parsed = urlparse(href)
                    if parsed.netloc != base_domain:
                        continue
                    path = parsed.path.strip("/").lower()
                    if not path or len(path) < 4:
                        continue
                    if any(skp in path for skp in skip_patterns):
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
        except Exception:
            return []

    async def _fetch_page(self, url: str) -> str | None:
        import random, asyncio
        # Small random delay for politeness / anti-bot
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
                self._add_failure(url, "page_fetch_forbidden", f"HTTP 403 (anti-bot)")
            elif r.status_code >= 400:
                self._add_failure(url, "page_fetch_failed", f"HTTP {r.status_code}")
        except Exception as e:
            self._add_failure(url, "page_fetch_failed", str(e)[:200])
        return None

    def _extract_images(self, html: str, page_url: str, limit: int) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        images = []
        seen = set()

        # 1. og:image (highest priority — usually the main editorial image)
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            url = self._normalize_url(og_img["content"], page_url)
            if url and url not in seen and not self._is_bad_url(url):
                seen.add(url)
                images.append({"url": self._upgrade_url(url), "thumbnail": "", "keywords": []})

        # 2. twitter:image
        tw_img = soup.find("meta", attrs={"name": "twitter:image"})
        if tw_img and tw_img.get("content"):
            url = self._normalize_url(tw_img["content"], page_url)
            if url and url not in seen and not self._is_bad_url(url):
                seen.add(url)
                images.append({"url": self._upgrade_url(url), "thumbnail": "", "keywords": []})

        # 3. All <img> tags, sorted by likely quality
        for img in soup.find_all("img"):
            if len(images) >= limit:
                break
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            if not src:
                continue
            src = self._normalize_url(src, page_url)
            if not src or src in seen:
                continue
            # Skip tiny icons, tracking pixels, logos, thumbnails
            if self._is_bad_url(src):
                self._add_failure(src, "bad_url_skipped", "matches low-quality pattern")
                continue
            seen.add(src)

            # Try to upgrade CDN URL to full resolution
            src = self._upgrade_url(src)

            alt = img.get("alt", "")
            images.append({
                "url": src,
                "thumbnail": "",
                "keywords": [alt] if alt else [],
            })

        # 4. srcset for higher-res versions
        for img in soup.find_all("img"):
            srcset = img.get("srcset", "")
            if srcset:
                best = self._best_srcset(srcset, page_url)
                if best and best not in seen and not self._is_bad_url(best):
                    seen.add(best)
                    best = self._upgrade_url(best)
                    images.append({"url": best, "thumbnail": "", "keywords": []})

        # 5. Picture > source elements
        for source in soup.find_all("source"):
            srcset = source.get("srcset", "")
            if srcset:
                best = self._best_srcset(srcset, page_url)
                if best and best not in seen and not self._is_bad_url(best):
                    seen.add(best)
                    best = self._upgrade_url(best)
                    images.append({"url": best, "thumbnail": "", "keywords": []})

        # Filter to direct image URLs
        for i in images:
            if not self._is_image_url(i["url"]):
                self._add_failure(i["url"], "not_image_url", "no image extension or photo in path")
        images = [i for i in images if self._is_image_url(i["url"])]
        return images[:limit]

    def _normalize_url(self, url: str, page_url: str) -> str:
        if not url:
            return ""
        url = url.strip()
        if url.startswith("data:"):
            return ""
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("/"):
            url = urljoin(page_url, url)
        return url

    def _is_image_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return any(path.endswith(ext) for ext in IMAGE_EXTENSIONS) or "photo" in path

    def _best_srcset(self, srcset: str, page_url: str) -> str | None:
        candidates = []
        for part in srcset.split(","):
            part = part.strip()
            if not part:
                continue
            tokens = part.rsplit(" ", 1)
            url = tokens[0].strip()
            if len(tokens) == 2:
                try:
                    w = int(tokens[1].rstrip("w").strip())
                except ValueError:
                    w = 0
            else:
                w = 0
            url = self._normalize_url(url, page_url)
            if url:
                candidates.append((w, url))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def _guess_ext(self, url: str) -> str:
        path = urlparse(url).path.lower()
        for ext in IMAGE_EXTENSIONS:
            if path.endswith(ext):
                return ext
        return ".jpg"

    def _is_bad_url(self, url: str) -> bool:
        """Reject URLs that are clearly thumbnails, icons, or low-quality."""
        lower = url.lower()
        for pat in _SKIP_URL_PATTERNS:
            if pat in lower:
                return True
        return False

    def _upgrade_url(self, url: str) -> str:
        """Strip CDN resizing params to get the largest available version."""
        for pattern, replacement in _CDN_SIZE_PATTERNS:
            url = pattern.sub(replacement, url)
        return url

    def _add_failure(self, url: str, reason: str, detail: str = "") -> None:
        self.failures.append({"url": url, "reason": reason, "detail": detail})

    def _check_dimensions(self, filepath: Path) -> bool:
        """Returns True if the image meets minimum dimension requirements."""
        try:
            with PILImage.open(filepath) as img:
                w, h = img.size
                return min(w, h) >= MIN_IMAGE_DIMENSION
        except Exception:
            return True  # Keep the image if we can't check dimensions

    async def close(self):
        await self.client.aclose()
