"""Anti-detection / stealth helpers for web crawling.

Provides UA rotation, header randomization, referrer chain simulation,
and domain-aware session management.

Usage:
    from taste_graph_ai.infrastructure.crawlers.stealth import StealthSession

    session = StealthSession()
    client = session.get_client("example.com")
    response = await client.get("https://example.com/page")
"""

import random
import time
from urllib.parse import urlparse

import httpx

# ── Expanded User-Agent pool (20+ entries) ────────────────────

_USER_AGENTS = [
    # Chrome on macOS (multiple versions)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    # Firefox on Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    # Edge on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
]

# ── Accept-Language pools ──────────────────────────────────────

_ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "en-GB,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "en-US,en;q=0.9,fr;q=0.8,ja;q=0.7",
    "en-US,en;q=0.9,de;q=0.8",
    "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
    "en-US,en;q=0.9,ko;q=0.8,ja;q=0.7",
    "en-US,en;q=0.9,es;q=0.8,fr;q=0.7",
    "en-AU,en;q=0.9,en-US;q=0.8",
    "en-CA,en;q=0.9,fr-CA;q=0.8,fr;q=0.7",
    "en-US,en;q=0.9,it;q=0.8,de;q=0.7",
    "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
]

# ── Sec-CH-UA headers (client hints) ──────────────────────────

_SEC_CH_UA_POOLS = [
    # Chrome
    '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
    '"Chromium";v="130", "Not_A Brand";v="24", "Google Chrome";v="130"',
    '"Chromium";v="129", "Not_A Brand";v="24", "Google Chrome";v="129"',
    # Edge
    '"Chromium";v="131", "Not_A Brand";v="24", "Microsoft Edge";v="131"',
]  # noqa: E501

# ── Referrer options ──────────────────────────────────────────

_REFERRERS = [
    "https://www.google.com/",
    "https://www.bing.com/",
    "https://duckduckgo.com/",
    "",  # Direct traffic
]


def _random_ua() -> str:
    return random.choice(_USER_AGENTS)


def _random_lang() -> str:
    return random.choice(_ACCEPT_LANGUAGES)


def _random_sec_ch_ua() -> str:
    return random.choice(_SEC_CH_UA_POOLS)


def _random_referer() -> str:
    return random.choice(_REFERRERS)


# ── Delay helpers ──────────────────────────────────────────────

def jittered_delay(base_seconds: float = 2.0, jitter: float = 1.0) -> float:
    """Return a sleep duration with random jitter around base.

    Uses uniform distribution: base ± jitter, clamped to min 0.5s.
    """
    delay = base_seconds + random.uniform(-jitter, jitter)
    return max(delay, 0.5)


# ── Session manager ────────────────────────────────────────────

class StealthSession:
    """Manages per-domain httpx clients with rotating fingerprints.

    Each domain gets its own httpx.AsyncClient with a consistent
    (but randomly assigned) set of headers. Cookies are isolated
    per domain to avoid cross-site tracking.
    """

    def __init__(self):
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._domain_headers: dict[str, dict] = {}

    def _make_headers(self, with_referer: str = "") -> dict[str, str]:
        """Generate a fresh set of realistic browser headers."""
        headers: dict[str, str] = {
            "User-Agent": _random_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": _random_lang(),
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Sec-CH-UA": _random_sec_ch_ua(),
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": random.choice(['"macOS"', '"Windows"', '"Linux"']),
        }
        if with_referer:
            headers["Referer"] = with_referer
        return headers

    def get_client(self, domain: str = "", referer_url: str = "") -> httpx.AsyncClient:
        """Get or create an httpx client for a given domain.

        Args:
            domain: The target domain (e.g. "example.com"). Clients are
                    cached per domain for cookie isolation.
            referer_url: If provided, used as the Referer header for
                         the first request. Subsequent requests use the
                         target URL as referer.
        """
        key = domain or "__default__"

        if key not in self._clients:
            headers = self._make_headers(with_referer=referer_url)
            self._domain_headers[key] = headers
            self._clients[key] = httpx.AsyncClient(
                headers=headers,
                timeout=30,
                follow_redirects=True,
            )

        return self._clients[key]

    def rotate_ua(self, domain: str = "") -> None:
        """Rotate User-Agent and related headers for a domain's client."""
        key = domain or "__default__"
        if key in self._clients:
            new_ua = _random_ua()
            self._clients[key].headers["User-Agent"] = new_ua
            self._clients[key].headers["Accept-Language"] = _random_lang()
            self._clients[key].headers["Sec-CH-UA"] = _random_sec_ch_ua()
            self._domain_headers[key]["User-Agent"] = new_ua

    async def close(self) -> None:
        """Close all managed clients."""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()
        self._domain_headers.clear()
