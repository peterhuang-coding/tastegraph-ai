import uuid
from datetime import datetime
from typing import Optional

from taste_graph_ai.config import FEEDBACK_PROPAGATION_DEPTH, FEEDBACK_PROPAGATION_DECAY
from taste_graph_ai.container import get_container
from taste_graph_ai.domain.enums import (
    FeedbackLabel, FeedbackTargetType, NodeType, RelationType,
)
from taste_graph_ai.domain.models import Feedback
from taste_graph_ai.infrastructure.db.event_log import EventLog
from taste_graph_ai.infrastructure.repos.feedback import FeedbackRepository


# Maps feedback labels to graph weight adjustments
LABEL_DELTA_MAP = {
    FeedbackLabel.DUI_WEI: +2,
    FeedbackLabel.BU_DUI_WEI: -3,
    FeedbackLabel.TAI_PU_TONG: -1,
    FeedbackLabel.TAI_WANG_HONG: -3,
    FeedbackLabel.TAI_TIAN: -2,
    FeedbackLabel.TAI_SHANG_YE: -2,
    FeedbackLabel.GENG_LENG: +1,
    FeedbackLabel.GENG_KUANG: +1,
    FeedbackLabel.GENG_RI_CHANG: +1,
    FeedbackLabel.GENG_WEN_HUA: +1,
    FeedbackLabel.GENG_CHAN_PIN: +1,
    FeedbackLabel.SHI_HE_FA: +2,
    FeedbackLabel.ZHI_SHI_HE_CAN_KAO: +0,
    FeedbackLabel.YOU_CHAN_PIN_QIAN_LI: +3,
    FeedbackLabel.KE_YI_ZUO_LAN_MU: +2,
    FeedbackLabel.XIANG_WO: +3,
    FeedbackLabel.BU_XIANG_WO: -3,
}


class FeedbackService:
    def __init__(
        self,
        feedback_repo: FeedbackRepository,
        event_log: EventLog,
    ):
        self.feedback_repo = feedback_repo
        self.event_log = event_log

    async def record(
        self,
        target_type: FeedbackTargetType,
        target_id: str,
        label: FeedbackLabel,
        note: str = "",
    ) -> Feedback:
        fb = Feedback(
            id=uuid.uuid4().hex[:12],
            target_type=target_type,
            target_id=target_id,
            label=label,
            note=note,
        )
        await self.feedback_repo.save(fb)

        # Update graph weights — use AI reasoning if available for image targets
        delta = LABEL_DELTA_MAP.get(label, 0)
        if delta != 0:
            container = get_container()
            graph = container.taste_graph

            if target_type == FeedbackTargetType.IMAGE:
                # Precise adjustment: use CLIP to find which concepts the image matches,
                # then adjust THOSE specific edges instead of generic BFS propagation
                await self._precise_image_feedback(
                    graph, fb, target_id, delta, note, container
                )
            else:
                # Fallback: BFS propagation from concept node
                concept_id = f"concept:{target_id.lower().replace(' ', '_')}"
                if concept_id in graph:
                    graph.propagate_feedback(
                        concept_id,
                        delta,
                        depth=FEEDBACK_PROPAGATION_DEPTH,
                        decay=FEEDBACK_PROPAGATION_DECAY,
                    )

            container.save_graph()

        # Audit log
        self.event_log.append("feedback.recorded", {
            "feedback_id": fb.id,
            "target_type": target_type.value,
            "target_id": target_id,
            "label": label.value,
            "delta": delta,
        })

        return fb

    async def _precise_image_feedback(
        self,
        graph,
        fb: Feedback,
        target_id: str,
        delta: float,
        note: str,
        container,
    ) -> None:
        """Use CLIP + AI to identify WHY an image matches taste, and adjust
        the specific concept edges that are most relevant — not generic BFS."""
        # 1. Get image path
        image_path = await self._get_image_path(target_id)
        if not image_path:
            # Fall back to BFS
            concept_id = f"concept:{target_id.lower().replace(' ', '_')}"
            if concept_id in graph:
                graph.propagate_feedback(concept_id, delta,
                                        depth=FEEDBACK_PROPAGATION_DEPTH,
                                        decay=FEEDBACK_PROPAGATION_DECAY)
            return

        # 2. Find top-matching taste concepts via CLIP
        matched_concepts = self._find_matching_concepts(graph, image_path)
        if not matched_concepts:
            return

        # 3. Generate AI reasoning
        reasoning = await self._generate_feedback_reasoning(
            image_path, matched_concepts, fb.label, note
        )
        if reasoning:
            fb.note = f"{fb.note} | AI: {reasoning}" if fb.note else f"AI: {reasoning}"
            self.event_log.append("feedback.reasoning", {
                "feedback_id": fb.id,
                "reasoning": reasoning,
                "matched_concepts": matched_concepts[:5],
            })

        # 4. Precisely adjust the top-matched concept edges
        ns_id = "concept:north_star"
        if ns_id not in graph:
            return

        for concept_label, sim_score in matched_concepts[:5]:
            concept_id = f"concept:{concept_label.lower().replace(' ', '_')}"
            # Ensure concept node exists
            if concept_id not in graph:
                graph.add_node(concept_label, NodeType.CONCEPT,
                               node_id=concept_id,
                               source="feedback_reasoning")
            # Adjust edge with delta scaled by similarity
            scaled_delta = delta * sim_score
            try:
                if graph.has_edge(ns_id, concept_id):
                    graph.adjust_weight(ns_id, concept_id, scaled_delta)
            except ValueError:
                graph.add_edge(ns_id, concept_id,
                             RelationType.PREFERS if delta > 0 else RelationType.AVOIDS,
                             weight=abs(scaled_delta))

    @staticmethod
    def _find_matching_concepts(graph, image_path: str, top_n: int = 10) -> list[tuple[str, float]]:
        """Use CLIP to find which taste concepts this image best matches."""
        try:
            from taste_graph_ai.services.clip import get_clip
            clip_svc = get_clip()

            # Collect all concept nodes from graph
            concepts = []
            for node_id, data in graph.graph.nodes(data=True):
                if data["type"] in (NodeType.CONCEPT, NodeType.MOOD, NodeType.VISUAL_ELEMENT):
                    concepts.append((node_id, data["label"]))

            if not concepts:
                return []

            # Compute CLIP similarity for image against each concept text
            texts = [label for _, label in concepts]
            img_emb = clip_svc.embed_image(image_path)
            if img_emb is None:
                return []

            import numpy as np
            img_vec = np.array(img_emb)
            scored = []
            for (node_id, label) in concepts:
                text_emb = clip_svc.embed_text(label)
                if text_emb is None:
                    continue
                sim = float(np.dot(img_vec, np.array(text_emb)))
                scored.append((label, sim))

            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_n]
        except Exception:
            return []

    async def _generate_feedback_reasoning(
        self,
        image_path: str,
        matched_concepts: list[tuple[str, float]],
        label,
        note: str,
    ) -> str:
        """Use AI to explain why this image evokes the matched concepts.

        L3 优化:hard 强制命中至少 1 个具体视觉词(颜色/材质/构图/光线/比例/排版)。
        Hard rules:不准说 "feels right"/"很对味"/"不错"/"good";文案 ≤30 字中文。
        """
        top = ", ".join([c for c, _ in matched_concepts[:5]])
        label_text = label.value if hasattr(label, 'value') else str(label)
        try:
            from taste_graph_ai.infrastructure.ai.client import AIClient
            ai = AIClient()
            prompt = f"""Analyze why a taste-driven moodboard user rated this image as "{label_text}".

The image's top CLIP-matched taste concepts: {top}
User's optional note: {note or 'N/A'}

Account taste: quiet, editorial, low-saturation, Hidden NY / JJJJound style.
Taste rules: good things don't shout; can be weird but not cheap; minimal but not empty.

Hard rules(必读,违反视为失败):
- 必中至少 1 个具体视觉词,不允许"feels right"类空话
- 不准说:"feels right"、"很对味"、"不错"、"good"、"对味"
- 文案 ≤30 字中文,1 句话

允许的视觉词表(从中挑至少 1 个命中):
- 颜色:灰 / 白 / 黑 / 米 / 冷调 / 暖调 / 低饱和 / 莫兰迪
- 材质:水泥 / 羊毛 / 棉 / 亚麻 / 金属 / 玻璃 / 木 / 哑光
- 构图:留白 / 居中 / 三分 / 对称 / 边缘切割
- 光线:阴天 / 室内自然光 / 侧光 / 逆光 / 暗调
- 比例:瘦长 / 方正 / 微小 / 夸张
- 排版:无衬线 / 西文 / 标点节制 / 对齐

只输出中文 reason(≤30 字,1 句话),不要 markdown、不要引号、不要解释。
例:"灰色水泥质感配侧光,留白比例克制" """
            result = await ai.chat(prompt, 100)
            await ai.close()
            text = (result or "").strip().strip('"').strip('「').strip('」').strip()
            # 二级清洗:硬拦截空话短语
            empty_phrases = ["feels right", "很对味", "不错", "good", "ok", "对味"]
            low = text.lower()
            if any(low == p or low.startswith(p + "，") or low.startswith(p + ",") for p in empty_phrases):
                return ""
            return text[:60]
        except Exception:
            return ""

    async def _get_image_path(self, image_id: str) -> Optional[str]:
        """Look up an image's local file path from the image repository."""
        try:
            from taste_graph_ai.infrastructure.repos.images import ImageRepository
            from taste_graph_ai.infrastructure.db.connection import get_db
            db = await get_db()
            repo = ImageRepository(db)
            img = await repo.get_by_id(image_id)
            return img.local_path if img and img.local_path else None
        except Exception:
            return None
