import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from taste_graph_ai.api.router import api_router
from taste_graph_ai.config import HOST, PORT, ensure_dirs
from taste_graph_ai.container import get_container
from taste_graph_ai.infrastructure.db.connection import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    ensure_dirs()
    await init_db()
    get_container()  # Initialize graph
    yield
    # Shutdown: nothing needed


app = FastAPI(
    title="TasteGraph AI",
    version="1.0.0",
    description="Personal taste knowledge graph + moodboard recommendation engine",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# Serve images directory (must be mounted before / to avoid interception)
from taste_graph_ai.config import IMAGES_DIR, EXPORTS_DIR
if IMAGES_DIR.exists():
    app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")
if EXPORTS_DIR.exists():
    app.mount("/exports", StaticFiles(directory=str(EXPORTS_DIR)), name="exports")

# Static files (HTML frontend)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


def main():
    import uvicorn
    uvicorn.run(
        "taste_graph_ai.server:app",
        host=HOST,
        port=PORT,
        reload=True,
    )


if __name__ == "__main__":
    main()
