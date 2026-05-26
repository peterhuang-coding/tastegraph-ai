from enum import Enum


class SourceType(str, Enum):
    LOOKBOOK = "lookbook"
    VIDEO = "video"
    ARTICLE = "article"
    PHOTO = "photo"
    MIXED = "mixed"


class SourceStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class ImageStatus(str, Enum):
    PENDING = "pending"
    SELECTED = "selected"
    REPLACED = "replaced"
    REJECTED = "rejected"


class PackStatus(str, Enum):
    DRAFT = "draft"
    SELECTED = "selected"
    REJECTED = "rejected"
    PUBLISHED = "published"


class TaskType(str, Enum):
    REVIEW_SOURCES = "review_sources"
    STALE_REVIEW = "stale_review"
    THEME_SUGGESTION = "theme_suggestion"
    TREND_ALERT = "trend_alert"
    PRODUCT_SEED = "product_seed"
    SOURCE_ROTATION = "source_rotation"
    SERIES_IDEA = "series_idea"
    GAP_ALERT = "gap_alert"


class TaskPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    DISMISSED = "dismissed"


class FeedbackLabel(str, Enum):
    DUI_WEI = "对味"
    BU_DUI_WEI = "不对味"
    TAI_PU_TONG = "太普通"
    TAI_WANG_HONG = "太网红"
    TAI_TIAN = "太甜"
    TAI_SHANG_YE = "太商业"
    GENG_LENG = "更冷"
    GENG_KUANG = "更狂"
    GENG_RI_CHANG = "更日常"
    GENG_WEN_HUA = "更文化"
    GENG_CHAN_PIN = "更产品"
    SHI_HE_FA = "适合发"
    ZHI_SHI_HE_CAN_KAO = "只适合参考"
    YOU_CHAN_PIN_QIAN_LI = "有产品潜力"
    KE_YI_ZUO_LAN_MU = "可以做栏目"
    XIANG_WO = "像我"
    BU_XIANG_WO = "不像我"


class FeedbackTargetType(str, Enum):
    SOURCE = "source"
    IMAGE = "image"
    TOPIC = "topic"
    CONCEPT = "concept"
    PACK = "pack"


class NodeType(str, Enum):
    CONCEPT = "concept"
    VISUAL_ELEMENT = "visual_element"
    PILLAR = "pillar"
    SOURCE = "source"
    MOOD = "mood"
    COLOR = "color"
    BRAND = "brand"
    OBJECT = "object"
    LOCATION = "location"


class RelationType(str, Enum):
    PREFERS = "prefers"
    AVOIDS = "avoids"
    BELONGS_TO = "belongs_to"
    SIMILAR_TO = "similar_to"
    APPEARS_WITH = "appears_with"
    SOURCED_FROM = "sourced_from"
    HAS_MOOD = "has_mood"
    HAS_COLOR = "has_color"


class UserAction(str, Enum):
    APPROVED = "approved"
    REPLACED = "replaced"
    REJECTED = "rejected"
