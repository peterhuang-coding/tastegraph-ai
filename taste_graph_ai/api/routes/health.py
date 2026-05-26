import os

from fastapi import APIRouter

from taste_graph_ai.api import schemas
from taste_graph_ai.config import GRAPH_FILE, DB_FILE
from taste_graph_ai.container import get_container

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=schemas.HealthResponse)
async def health_check():
    components = {}

    # DB
    try:
        components["db"] = "ok" if DB_FILE.exists() or True else "missing"
    except Exception:
        components["db"] = "error"

    # Graph
    try:
        graph = get_container().taste_graph
        components["graph"] = f"ok ({graph.node_count} nodes)"
    except Exception as e:
        components["graph"] = f"error: {e}"

    # CLIP
    components["clip"] = "not_loaded"

    # AI provider
    if os.environ.get("DEEPSEEK_API_KEY"):
        components["ai"] = f"deepseek ({os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')})"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        components["ai"] = f"claude ({os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-6')})"
    else:
        components["ai"] = "not_configured"

    all_ok = all(not v.startswith("error") for v in components.values())
    return schemas.HealthResponse(
        status="healthy" if all_ok else "degraded",
        components=components,
    )
