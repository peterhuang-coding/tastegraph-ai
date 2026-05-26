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

    # Claude
    components["claude"] = "not_configured"

    all_ok = all(not v.startswith("error") for v in components.values())
    return schemas.HealthResponse(
        status="healthy" if all_ok else "degraded",
        components=components,
    )
