import re
import uuid
from datetime import date, datetime, timezone

from taste_graph_ai.config import DAILY_PACK_COUNT, TASTE_SCORE_NORMALIZATION_FACTOR
from taste_graph_ai.domain.enums import PackStatus
from taste_graph_ai.domain.models import DailyPack
from taste_graph_ai.container import get_container
from taste_graph_ai.infrastructure.ai.client import AIClient
from taste_graph_ai.infrastructure.repos.packs import PackRepository
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.services.voice import build_messages


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
            # Normalize to 0.5-1.0 range.
            # score_content() returns raw scores (keyword matches × edge weights),
            # typically in 0-15 range. Divide by TASTE_SCORE_NORMALIZATION_FACTOR
            # (default 10.0) and clamp to [0.5, 1.0].
            taste_score = max(0.5, min(1.0, taste_score / TASTE_SCORE_NORMALIZATION_FACTOR))

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

        # 通过 voice.build_messages() 注入 system prompt + few-shot，
        # 不再依赖 generator 自己拼多行英文规则。
        user_input = (
            "Generate today's moodboard entry.\n"
            "Return ONLY valid JSON (no markdown, no ```json fences):\n"
            "{\n"
            '  "theme": "Chinese theme (2-6 chars, catalog-label style, e.g. 灰.羊毛.物 / 冷调 / 建筑内衬)",\n'
            '  "why_today": "One short deadpan line, English or Chinese, like \'Cotton study.\' / \'Archive find.\' / \'Dieter Rams.\'",\n'
            '  "title_options": ["Title 1 (short, catalog-like)", "Title 2", "Title 3"],\n'
            '  "caption": "30-80 chars museum label style: brands, cities, years, materials, objects separated by periods. No feelings. No weather. No time of day."\n'
            "}"
        )
        context = {
            "today_keywords": ", ".join(keywords[:10]),
            "published_themes_do_not_reuse": published_list,
            "recent_themes_avoid": recent_list,
            "angle_hint": angle_hint,
        }

        msgs = build_messages("prefill", user_input, context)
        # AIClient.chat/chat_json 仅接受单字符串 prompt；把 messages 平展成单一 prompt
        # （保留 role 标签以便模型看见 system / few-shot 分隔）
        prompt_text = "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in msgs)

        return await self.ai.chat_json(prompt_text, 600)

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
