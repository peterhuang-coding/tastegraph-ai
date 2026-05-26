from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from taste_graph_ai.domain.enums import (
    SourceType,
    SourceStatus,
    ImageStatus,
    PackStatus,
    TaskType,
    TaskPriority,
    TaskStatus,
    FeedbackLabel,
    FeedbackTargetType,
    UserAction,
)


@dataclass
class Source:
    id: str
    url: str
    name: str
    source_type: SourceType
    discovered_from: Optional[str] = None
    preview_thumbnails: list[str] = field(default_factory=list)
    ai_score: float = 0.0
    ai_reason: str = ""
    ai_risk: str = ""
    status: SourceStatus = SourceStatus.PENDING
    reviewer_note: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    reviewed_at: Optional[str] = None

    def approve(self, note: str = "") -> None:
        self.status = SourceStatus.APPROVED
        self.reviewer_note = note
        self.reviewed_at = datetime.now().isoformat()

    def reject(self, reason: str = "") -> None:
        self.status = SourceStatus.REJECTED
        self.reviewer_note = reason
        self.reviewed_at = datetime.now().isoformat()

    def defer(self) -> None:
        self.status = SourceStatus.DEFERRED
        self.reviewed_at = datetime.now().isoformat()


@dataclass
class Image:
    id: str
    source_id: Optional[str] = None
    url: str = ""
    page_url: str = ""
    local_path: str = ""
    thumbnail_path: str = ""
    keywords: list[str] = field(default_factory=list)
    graph_score: float = 0.0
    visual_score: float = 0.0
    final_score: float = 0.0
    status: ImageStatus = ImageStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class DailyPack:
    id: str
    date: str
    theme: str = ""
    why_today: str = ""
    title_options: list[str] = field(default_factory=list)
    caption: str = ""
    taste_score: float = 0.0
    status: PackStatus = PackStatus.DRAFT
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    selected_at: Optional[str] = None
    published_at: Optional[str] = None

    def select(self) -> None:
        self.status = PackStatus.SELECTED
        self.selected_at = datetime.now().isoformat()

    def reject(self) -> None:
        self.status = PackStatus.REJECTED

    def publish(self) -> None:
        self.status = PackStatus.PUBLISHED
        self.published_at = datetime.now().isoformat()


@dataclass
class PackImage:
    pack_id: str
    image_id: str
    position: int
    user_action: UserAction = UserAction.APPROVED


@dataclass
class Task:
    id: str
    task_type: TaskType
    title: str
    body: str = ""
    priority: TaskPriority = TaskPriority.MEDIUM
    action_url: str = ""
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None

    def complete(self) -> None:
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.now().isoformat()

    def dismiss(self) -> None:
        self.status = TaskStatus.DISMISSED
        self.completed_at = datetime.now().isoformat()


@dataclass
class Feedback:
    id: str
    target_type: FeedbackTargetType
    target_id: str
    label: FeedbackLabel
    note: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PublishRecord:
    id: str
    pack_id: str
    published_at: str
    platform: str = "xiaohongshu"
    post_url: str = ""
    likes: int = 0
    saves: int = 0
    comments: int = 0
    engagement_rate: float = 0.0
