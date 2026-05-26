import httpx

from taste_graph_ai.config import UNSPLASH_ACCESS_KEY
from taste_graph_ai.infrastructure.crawlers.base import Crawler, DiscoveredSource


class UnsplashCrawler(Crawler):
    """Unsplash API crawler for discovering photos and collections."""

    BASE = "https://api.unsplash.com"

    def __init__(self, access_key: str = UNSPLASH_ACCESS_KEY):
        self.access_key = access_key
        self.client = httpx.AsyncClient(
            base_url=self.BASE,
            headers={"Authorization": f"Client-ID {self.access_key}"} if self.access_key else {},
            timeout=30,
        )

    async def discover(self) -> list[DiscoveredSource]:
        if not self.access_key:
            return []

        results = []
        # Search for taste-relevant keywords
        search_queries = [
            "brutalist architecture shadow",
            "minimal coffee shop interior",
            "city street film photography",
            "quiet editorial fashion",
            "concrete texture neutral",
        ]

        for query in search_queries[:3]:
            try:
                photos = await self._search_photos(query, per_page=5)
                for photo in photos:
                    user = photo.get("user", {})
                    username = user.get("username", "")
                    if username:
                        results.append(DiscoveredSource(
                            url=f"https://unsplash.com/@{username}",
                            name=f"unsplash/@{username}",
                            source_type="photo",
                            discovered_from=f"search:{query}",
                            preview_thumbnails=[photo.get("urls", {}).get("thumb", "")],
                            raw_metadata={
                                "user_name": user.get("name", ""),
                                "bio": user.get("bio", ""),
                            },
                        ))
            except Exception:
                continue

        return results

    async def fetch_images(self, source_url: str, limit: int = 15) -> list[dict]:
        if not self.access_key:
            return []

        username = source_url.rstrip("/").split("@")[-1]
        try:
            photos = await self._get_user_photos(username, per_page=limit)
            return [
                {
                    "url": p.get("urls", {}).get("regular", ""),
                    "page_url": p.get("links", {}).get("html", ""),
                    "title": p.get("description") or p.get("alt_description") or "untitled",
                    "source": source_url,
                    "keywords": [tag.get("title", "") for tag in p.get("tags", [])[:5]],
                }
                for p in photos
            ]
        except Exception:
            return []

    async def _search_photos(self, query: str, per_page: int = 10) -> list[dict]:
        r = await self.client.get("/search/photos", params={"query": query, "per_page": per_page})
        if r.status_code == 200:
            return r.json().get("results", [])
        return []

    async def _get_user_photos(self, username: str, per_page: int = 15) -> list[dict]:
        r = await self.client.get(
            f"/users/{username}/photos",
            params={"per_page": per_page, "order_by": "latest"},
        )
        if r.status_code == 200:
            return r.json()
        return []

    async def close(self):
        await self.client.aclose()
