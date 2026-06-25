import re
import uuid
from datetime import date, datetime, timezone

from taste_graph_ai.config import DAILY_PACK_COUNT
from taste_graph_ai.domain.enums import PackStatus
from taste_graph_ai.domain.models import DailyPack
from taste_graph_ai.container import get_container
from taste_graph_ai.infrastructure.ai.client import AIClient
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.db.event_log import EventLog


class PackGenerationService:
    """Generates daily moodboard packs using AI + taste graph + image pool."""

    def __init__(
        self,
        pack_repo: PackRepository,
        event_log: EventLog,
        ai: AIClient = None,
        img_service = None,
    ):
        self.pack_repo = pack_repo
        self.event_log = event_log
        self.ai = ai or AIClient()
        self.img_service = img_service

    async def generate_daily_packs(self) -> list[DailyPack]:
        today = date.today().isoformat()
        existing = await self.pack_repo.get_today_packs(today)
        if existing:
            return existing

        graph = get_container().taste_graph

        # Extract keywords from graph: top concept nodes by edge weight
        keywords = self._extract_trending_keywords(graph)

        # Get ALL published themes to avoid repetition (not just recent 10)
        published_themes = await self.pack_repo.get_published_themes()
        recent = await self.pack_repo.get_latest_packs(10)
        recent_themes = [p.theme for p in recent if p.theme]

        packs = []
        used_image_ids: set[str] = set()
        for i in range(DAILY_PACK_COUNT):
            try:
                theme_data = await self._generate_single_theme(
                    keywords, recent_themes, published_themes, variation=i
                )
            except Exception as e:
                self.event_log.append("generator.theme_error", {"error": str(e)})
                continue

            if not theme_data.get("theme"):
                continue

            # Post-process caption to ensure cool/terse style
            if theme_data.get("caption"):
                theme_data["caption"] = self._polish_caption(theme_data["caption"])

            # Score the theme against the taste graph
            taste_score = graph.score_content(
                keywords[:5] + theme_data.get("theme", "").split(),
            )
            # Normalize to 0.5-1.0 range
            taste_score = max(0.5, min(1.0, taste_score / 10))

            pack = DailyPack(
                id=uuid.uuid4().hex[:12],
                date=today,
                theme=theme_data.get("theme", ""),
                why_today=theme_data.get("why_today", ""),
                title_options=theme_data.get("title_options", []),
                caption=theme_data.get("caption", ""),
                taste_score=round(taste_score, 2),
                status=PackStatus.DRAFT,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            await self.pack_repo.save(pack)
            packs.append(pack)
            recent_themes.append(pack.theme)

            # Pick matching images from the pool (avoid duplicates across packs)
            if self.img_service:
                try:
                    picked = await self.img_service.pick_for_pack(
                        pack.id, pack.theme, exclude_ids=used_image_ids
                    )
                    used_image_ids.update(img.id for img in picked)
                    self.event_log.append("generator.images_picked", {
                        "pack_id": pack.id,
                        "count": len(picked),
                        "exclude_count": len(used_image_ids),
                    })
                except Exception as e:
                    self.event_log.append("generator.pick_error", {
                        "pack_id": pack.id,
                        "error": str(e),
                    })

            self.event_log.append("generator.pack_created", {
                "id": pack.id,
                "theme": pack.theme,
                "score": pack.taste_score,
            })

        return packs

    async def _generate_single_theme(
        self, keywords: list[str], recent_themes: list[str], published_themes: list[str] = None, variation: int = 0
    ) -> dict:
        angles = ["object catalog", "material study", "proportion note", "archive find", "deadpan observation"]
        angle_hint = angles[variation % len(angles)]

        published_list = ", ".join(published_themes[:50]) if published_themes else "暂无"
        recent_list = ", ".join(recent_themes[:5]) if recent_themes else "暂无"

        prompt = f"""You are the editor of a personal taste archive. Your references: Hidden NY, JJJJound, 032c, ABI (A Barely International), The Society Archive. You are NOT a content creator. You are a visual archivist.

Your caption style is NOT Chinese social media style. It is international moodboard style:
  — Museum label, not diary entry.
  — Facts only: brand, year, city, material, object name.
  — If you MUST write a sentence: deadpan, cultural reference, no adjectives.
  — Like JJJJound: "Heavy cotton twill. Montreal. 2024."
  — Like Hidden NY: "RAF SIMONS. AW 1998. Antwerp."
  — Like ABI: a list of objects with no commentary.
  — Never explain why something is good. Never describe a feeling.
  — Never use: light, shadow, mood, vibe, quiet afternoon, soft, beautiful, elegant.
  — Never use: 氛围, 感觉, 安静, 柔和, 光线, 午后, 美, 高级.
  — Use periods. Not commas. Not ellipses. Not em dashes.
  — Max 3 short fragments. Not sentences. Not paragraphs.

TERRIBLE (never write this):
  "周一午后的街角，水泥墙面被光线切出柔和的棱角..."
  "灰色羊毛混纺长大衣。落肩设计。安静的午后..."
  "今天整理了几件深灰色单品。都是最近很喜欢的..."

GOOD (write like this):
  "RAF SIMONS. AW 1998. Antwerp."
  "Cotton twill. Made in Portugal. 420gsm."
  "灰色。羊毛。没有 logo。"
  "Lemaire shirt. JJJJound socks. Cold black coffee."
  "Concrete. Steel. Glass. No decoration."
  "1999 Helmut Lang backstage. archive.org."
  "Virgil 用 3% 的改变让整个系统重新呼吸。"  ← only one cultural line per post, if any

Account tone: cold, editorial, archival, low-saturation, city-grey.
Avoid: cute, influencer, luxury logo, neon, stock photo, pastel, pink, warm, cozy.

Today's image keywords: {', '.join(keywords[:10])}
Previously published themes (DO NOT REUSE): {published_list}
Recently generated themes (avoid): {recent_list}
Angle hint: {angle_hint}

Generate a moodboard entry. Return ONLY valid JSON (no markdown, no ```json):
{{"theme": "Chinese theme (2-6 chars, like a catalog label. e.g. 灰.羊毛.物 or 冷调 or 建筑内衬)", "why_today": "One short line, English or Chinese, deadpan. Like 'Cotton study.' or 'Archive find.' or 'Dieter Rams.'", "title_options": ["Title 1 (short, catalog-like)", "Title 2", "Title 3"], "caption": "30-80 chars total. Museum label style. Brands. Cities. Years. Materials. Objects. No feelings. No weather. No time of day. Periods between fragments."}}"""
        return await self.ai.chat_json(prompt, 600)

    @staticmethod
    def _polish_caption(text: str) -> str:
        """Strip hashtags, emoji, excessive punctuation, and enforce terseness."""
        # Strip hashtags
        text = re.sub(r'#\S+', '', text)
        # Strip emoji
        text = re.sub(r'[\U0001F300-\U0001F9FF☀-➿⭐✀-➿️‍]', '', text)
        # Collapse spaces and trim
        text = re.sub(r' +', ' ', text).strip()
        # Hard cap at 120 chars
        if len(text) > 120:
            text = text[:117] + '...'
        return text

    def _extract_trending_keywords(self, graph) -> list[str]:
        """Extract top-weighted concept nodes as keywords."""
        scored = []
        for node_id, data in graph.graph.nodes(data=True):
            if data["type"].value not in ("concept", "visual_element", "mood"):
                continue
            total_weight = 0.0
            edge_count = 0
            for _, __, edge_data in graph.graph.out_edges(node_id, data=True):
                total_weight += abs(edge_data.get("weight", 0))
                edge_count += 1
            for __, ___, edge_data in graph.graph.in_edges(node_id, data=True):
                total_weight += abs(edge_data.get("weight", 0))
                edge_count += 1
            if edge_count > 0:
                scored.append((data["label"], total_weight / edge_count))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [kw for kw, _ in scored[:20]]

    async def close(self):
        await self.ai.close()
