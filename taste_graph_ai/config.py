import os
from pathlib import Path

# Load .env file if present
try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).resolve().parent.parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
except ImportError:
    pass

# ── Paths ────────────────────────────────────────────────────

BASE_DIR = Path(os.environ.get(
    "TASTEGRAPH_BASE_DIR",
    Path(__file__).resolve().parent.parent,
))

DATA_DIR = Path(os.environ.get(
    "TASTEGRAPH_DATA_DIR",
    BASE_DIR / "data",
))

GRAPH_FILE = DATA_DIR / "taste_graph.json"
DB_FILE = DATA_DIR / "taste_graph.db"
EVENT_LOG_FILE = DATA_DIR / "events.log"
IMAGES_DIR = DATA_DIR / "images"
EXPORTS_DIR = DATA_DIR / "exports"
LOGS_DIR = DATA_DIR / "logs"

# ── Server ───────────────────────────────────────────────────

HOST = os.environ.get("TASTEGRAPH_HOST", "0.0.0.0")
PORT = int(os.environ.get("TASTEGRAPH_PORT", "8787"))

# ── External APIs ────────────────────────────────────────────

CLAUDE_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("TASTEGRAPH_CLAUDE_MODEL", "claude-sonnet-4-6")

ARENA_ACCESS_TOKEN = os.environ.get("ARENA_ACCESS_TOKEN", "")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

# ── CLIP ─────────────────────────────────────────────────────

CLIP_MODEL_NAME = os.environ.get("TASTEGRAPH_CLIP_MODEL", "ViT-B/32")
CLIP_DEVICE = os.environ.get("TASTEGRAPH_CLIP_DEVICE", "cpu")

# ── Discovery ────────────────────────────────────────────────

DISCOVERY_MAX_SOURCES_PER_RUN = int(os.environ.get("TASTEGRAPH_DISCOVERY_MAX", "10"))
DISCOVERY_REQUEST_DELAY = float(os.environ.get("TASTEGRAPH_DISCOVERY_DELAY", "1.0"))

# ── Scoring ──────────────────────────────────────────────────

GRAPH_SCORE_WEIGHT = float(os.environ.get("TASTEGRAPH_GRAPH_WEIGHT", "0.4"))
VISUAL_SCORE_WEIGHT = float(os.environ.get("TASTEGRAPH_VISUAL_WEIGHT", "0.2"))
NOVELTY_SCORE_WEIGHT = float(os.environ.get("TASTEGRAPH_NOVELTY_WEIGHT", "0.15"))
TIMELINESS_SCORE_WEIGHT = float(os.environ.get("TASTEGRAPH_TIMELINESS_WEIGHT", "0.15"))
PRODUCT_SCORE_WEIGHT = float(os.environ.get("TASTEGRAPH_PRODUCT_WEIGHT", "0.1"))

# ── Daily Pack ───────────────────────────────────────────────

DAILY_PACK_COUNT = int(os.environ.get("TASTEGRAPH_PACK_COUNT", "3"))
DAILY_IMAGES_PER_PACK = int(os.environ.get("TASTEGRAPH_IMAGES_PER_PACK", "9"))

# ── Feedback ─────────────────────────────────────────────────

FEEDBACK_PROPAGATION_DEPTH = int(os.environ.get("TASTEGRAPH_FEEDBACK_DEPTH", "2"))
FEEDBACK_PROPAGATION_DECAY = float(os.environ.get("TASTEGRAPH_FEEDBACK_DECAY", "0.5"))


# ── Xiaohongshu Publish ───────────────────────────────────────

XHS_COOKIES_FILE = DATA_DIR / "xhs_cookies.json"
XHS_CREATOR_URL = "https://creator.xiaohongshu.com"
XHS_HEADLESS = not bool(os.environ.get("TASTEGRAPH_XHS_HEADFUL"))


def ensure_dirs() -> None:
    """Create all required directories."""
    for d in [DATA_DIR, IMAGES_DIR, EXPORTS_DIR, LOGS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
