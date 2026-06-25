"""Playwright-based crawler for JS-rendered pages (Vogue Runway, SSENSE, NOWNESS, etc.).

Used as a fallback when the BS4 WebCrawler returns 0 images from a source.
Extracts fully-rendered images including lazy-loaded and JS-injected content.
"""

import asyncio
from pathlib import Path
from urllib.parse import urljoin, urlparse

from taste_graph_ai.config import IMAGES_DIR
from taste_graph_ai.infrastructure.crawlers.base import Crawler, DiscoveredSource

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MIN_IMAGE_DIMENSION = 200  # lowered for design archives

# URL patterns that indicate tiny/low-quality images
_SKIP_URL_PATTERNS = [
    "logo", "icon", "avatar", "pixel", "1x1", "tracking",
    "thumbnail", "thumb-", "-thumb", "_thumb", "favicon",
    "button-", "banner-", "sidebar-",
]


class PlaywrightCrawler(Crawler):
    """Headless browser crawler for JS-heavy pages."""

    def __init__(self):
        self._playwright = None
        self._browser = None

    async def _ensure_browser(self):
        if self._browser is None:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )

    async def discover(self) -> list[DiscoveredSource]:
        return []

    async def fetch_images(self, page_url: str, limit: int = 50) -> list[dict]:
        """Open a page in headless Chromium, wait for rendering, extract all visible images."""
        await self._ensure_browser()

        try:
            context = await self._browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1440, "height": 900},
            )
            page = await context.new_page()

            try:
                await page.goto(page_url, wait_until="networkidle", timeout=30000)
            except Exception:
                # Some pages never reach networkidle — try domcontentloaded
                try:
                    await page.goto(page_url, wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    await context.close()
                    return []

            # Scroll to trigger lazy loading
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(0.5)
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1)

            # Extract images via JS evaluation (gets ALL rendered images including lazy-loaded)
            image_data = await page.evaluate("""() => {
                const images = [];
                const seen = new Set();

                // All <img> elements
                for (const img of document.querySelectorAll('img')) {
                    const src = img.src || img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || '';
                    const srcset = img.srcset || '';
                    if (!src && !srcset) continue;

                    // Pick best from srcset
                    let bestUrl = src;
                    if (srcset) {
                        const parts = srcset.split(',').map(p => p.trim().split(' '));
                        let bestW = 0;
                        for (const [url, w] of parts) {
                            const width = parseInt((w || '0').replace('w', ''));
                            if (url && width > bestW) { bestW = width; bestUrl = url; }
                        }
                    }
                    if (!bestUrl) continue;
                    if (bestUrl.startsWith('data:')) continue;

                    const naturalWidth = img.naturalWidth || 0;
                    const naturalHeight = img.naturalHeight || 0;

                    if (naturalWidth > 0 && naturalWidth < 200) continue;
                    if (naturalHeight > 0 && naturalHeight < 200) continue;

                    if (!seen.has(bestUrl)) {
                        seen.add(bestUrl);
                        images.push({url: bestUrl, width: naturalWidth, height: naturalHeight});
                    }
                }

                // Also check <picture> elements and <source> tags
                for (const source of document.querySelectorAll('source')) {
                    const srcset = source.srcset || '';
                    if (!srcset) continue;
                    const parts = srcset.split(',').map(p => p.trim().split(' '));
                    let bestUrl = '', bestW = 0;
                    for (const [url, w] of parts) {
                        const width = parseInt((w || '0').replace('w', ''));
                        if (url && width > bestW) { bestW = width; bestUrl = url; }
                    }
                    if (bestUrl && !bestUrl.startsWith('data:') && !seen.has(bestUrl)) {
                        seen.add(bestUrl);
                        images.push({url: bestUrl, width: 0, height: 0});
                    }
                }

                // Also check CSS background-images on key elements
                for (const el of document.querySelectorAll('[style*="background-image"]')) {
                    const style = el.getAttribute('style') || '';
                    const match = style.match(/url\\(["']?([^"')]+)["']?\\)/);
                    if (match && match[1] && !match[1].startsWith('data:') && !seen.has(match[1])) {
                        seen.add(match[1]);
                        images.push({url: match[1], width: 0, height: 0});
                    }
                }

                return images.slice(0, 60);
            }""")

            # Post-process: filter, normalize, dedup
            results = []
            seen_urls = set()
            for item in image_data:
                url = self._normalize_url(item["url"], page_url)
                if not url or url in seen_urls:
                    continue
                if self._is_bad_url(url):
                    continue

                seen_urls.add(url)
                results.append({
                    "url": url,
                    "thumbnail": "",
                    "keywords": [],
                    "width": item.get("width", 0),
                    "height": item.get("height", 0),
                })

                if len(results) >= limit:
                    break

            await context.close()
            return results

        except Exception:
            return []

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

    def _is_bad_url(self, url: str) -> bool:
        lower = url.lower()
        for pat in _SKIP_URL_PATTERNS:
            if pat in lower:
                return True
        return False

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None
