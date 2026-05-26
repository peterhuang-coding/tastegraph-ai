import uuid
from datetime import datetime

from taste_graph_ai.config import FEEDBACK_PROPAGATION_DEPTH, FEEDBACK_PROPAGATION_DECAY
from taste_graph_ai.container import get_container
from taste_graph_ai.domain.enums import FeedbackLabel, FeedbackTargetType
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

        # Update graph weights
        delta = LABEL_DELTA_MAP.get(label, 0)
        if delta != 0:
            container = get_container()
            graph = container.taste_graph

            # Find the relevant concept node
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
