from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Source ───────────────────────────────────────────────────

class SourceResponse(BaseModel):
    id: str
    url: str
    name: str
    source_type: str
    discovered_from: Optional[str] = None
    preview_thumbnails: list[str] = []
    ai_score: float = 0.0
    ai_reason: str = ""
    ai_risk: str = ""
    status: str = "pending"
    reviewer_note: str = ""
    created_at: str
    reviewed_at: Optional[str] = None

class SourceActionRequest(BaseModel):
    note: str = ""

class SourceStatsResponse(BaseModel):
    pending: int = 0
    approved: int = 0
    rejected: int = 0
    deferred: int = 0


# ── Daily Pack ────────────────────────────────────────────────

class PackImageResponse(BaseModel):
    image_id: str
    position: int
    user_action: str
    url: str
    page_url: str = ""
    local_path: str = ""
    keywords: list[str] = []

class DailyPackResponse(BaseModel):
    id: str
    date: str
    theme: str
    why_today: str = ""
    title_options: list[str] = []
    caption: str = ""
    taste_score: float = 0.0
    status: str
    images: list[PackImageResponse] = []
    created_at: str
    selected_at: Optional[str] = None

class DailyTodayResponse(BaseModel):
    packs: list[DailyPackResponse]
    tasks: list["TaskResponse"] = []

class ImageFeedbackRequest(BaseModel):
    label: str = Field(..., description="Feedback label")
    note: str = ""

class ImageReplaceRequest(BaseModel):
    new_image_id: str

class PackPublishRequest(BaseModel):
    platform: str = "xiaohongshu"
    post_url: str = ""


# ── Task ──────────────────────────────────────────────────────

class TaskResponse(BaseModel):
    id: str
    task_type: str
    title: str
    body: str = ""
    priority: str = "medium"
    action_url: str = ""
    status: str = "pending"
    created_at: str
    completed_at: Optional[str] = None


# ── Graph ─────────────────────────────────────────────────────

class GraphOverviewResponse(BaseModel):
    node_count: int
    edge_count: int
    node_types: dict
    edge_relations: dict

class GraphNodeResponse(BaseModel):
    id: str
    type: str
    label: str
    properties: dict = {}

class GraphNodeDetailResponse(BaseModel):
    id: str
    type: str
    label: str
    properties: dict = {}
    related_nodes: list[GraphNodeResponse] = []

class GraphEdgeResponse(BaseModel):
    source: str
    target: str
    relation: str
    weight: float
    feedback_count: int = 0
    last_updated: str = ""

class GraphNodeCreateRequest(BaseModel):
    label: str
    node_type: str

class GraphNodeUpdateRequest(BaseModel):
    label: Optional[str] = None
    properties: Optional[dict] = None

class GraphEdgeCreateRequest(BaseModel):
    source: str
    target: str
    relation: str
    weight: float = 1.0

class GraphWeightRequest(BaseModel):
    source: str
    target: str
    delta: float


# ── History ───────────────────────────────────────────────────

class HistoryItemResponse(BaseModel):
    id: str
    pack_id: str
    published_at: str
    platform: str
    post_url: str = ""
    likes: int = 0
    saves: int = 0
    comments: int = 0
    engagement_rate: float = 0.0
    theme: str = ""

class HistoryStatsResponse(BaseModel):
    total_published: int = 0
    avg_engagement: float = 0.0
    top_themes: list[dict] = []
    recent_trend: str = ""


# ── Pipeline ──────────────────────────────────────────────────

class PipelineResult(BaseModel):
    success: bool
    message: str
    data: dict = {}


# ── Health ────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    components: dict


# Forward ref for recursive model
DailyTodayResponse.model_rebuild()
