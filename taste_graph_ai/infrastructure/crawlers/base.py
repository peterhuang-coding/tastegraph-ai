from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class DiscoveredSource:
    url: str
    name: str
    source_type: str
    discovered_from: str
    preview_thumbnails: list[str] = field(default_factory=list)
    raw_metadata: dict = field(default_factory=dict)


class Crawler(ABC):
    @abstractmethod
    async def discover(self) -> list[DiscoveredSource]:
        ...

    @abstractmethod
    async def fetch_images(self, source_url: str, limit: int = 15) -> list[dict]:
        ...
