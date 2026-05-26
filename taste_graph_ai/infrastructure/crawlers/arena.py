import httpx

from taste_graph_ai.config import ARENA_ACCESS_TOKEN, DISCOVERY_REQUEST_DELAY
from taste_graph_ai.infrastructure.crawlers.base import Crawler, DiscoveredSource


class ArenaCrawler(Crawler):
    """Are.na API crawler for discovering channels and blocks."""

    BASE = "https://api.are.na/v2"

    def __init__(self, access_token: str = ARENA_ACCESS_TOKEN):
        self.token = access_token
        self.client = httpx.AsyncClient(
            base_url=self.BASE,
            headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
            timeout=30,
        )

    async def discover(self) -> list[DiscoveredSource]:
        if not self.token:
            return []

        results = []
        # Discover from known taste channels
        known_channels = [
            "brian-curran-jjjjound-full-archive",
            "lily-clempson-tfz8voo8tzo-editorial-fashion",
            "jeremy-turner-photography-editorial-lifestyle-fashion",
        ]

        for slug in known_channels:
            try:
                channel = await self._get_channel(slug)
                if channel:
                    # Get connected channels
                    connected = await self._get_connected_channels(slug)
                    for ch in connected[:5]:
                        results.append(DiscoveredSource(
                            url=f"https://www.are.na/{ch.get('slug', '')}",
                            name=f"are.na/{ch.get('title', ch.get('slug', ''))}",
                            source_type="lookbook",
                            discovered_from=f"are.na/{slug}",
                            preview_thumbnails=[],
                            raw_metadata=ch,
                        ))
            except Exception:
                continue

        return results

    async def fetch_images(self, source_url: str, limit: int = 15) -> list[dict]:
        if not self.token:
            return []
        slug = source_url.rstrip("/").split("/")[-1]
        try:
            blocks = await self._get_channel_contents(slug, per_page=limit)
            images = []
            for block in blocks:
                if block.get("class") == "Image":
                    images.append({
                        "url": block.get("image", {}).get("original", {}).get("url", ""),
                        "page_url": f"https://www.are.na/block/{block.get('id', '')}",
                        "title": block.get("title", "") or "untitled",
                        "source": source_url,
                    })
            return images
        except Exception:
            return []

    async def _get_channel(self, slug: str) -> dict | None:
        r = await self.client.get(f"/channels/{slug}")
        if r.status_code == 200:
            return r.json()
        return None

    async def _get_connected_channels(self, slug: str) -> list[dict]:
        r = await self.client.get(f"/channels/{slug}/connections")
        if r.status_code == 200:
            data = r.json()
            return data.get("channels", [])
        return []

    async def _get_channel_contents(self, slug: str, per_page: int = 15) -> list[dict]:
        r = await self.client.get(
            f"/channels/{slug}/contents",
            params={"per": per_page, "page": 1},
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("contents", [])
        return []

    async def close(self):
        await self.client.aclose()
