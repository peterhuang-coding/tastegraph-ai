import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from taste_graph_ai.api.router import api_router
from taste_graph_ai.config import ALLOWED_ORIGINS, HOST, PORT, RELOAD, ensure_dirs
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

# CORS：默认空白名单 = 同源 only（前端静态文件与 API 同源；跨域访问走
# queue_server 的服务端代理）。需要 Tailscale/局域网跨域时设
# TASTEGRAPH_ALLOWED_ORIGINS 逗号分隔白名单，永不允许 "*"。
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(api_router)

# 归一：旧版信息源简报已废弃，重定向到工作台的 live 源面板（8766 /sources）
from fastapi.responses import RedirectResponse


@app.get("/SOURCES.html")
def _legacy_sources_redirect():
    return RedirectResponse("http://127.0.0.1:8766/sources")


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
        reload=RELOAD,  # 生产默认 False；开发设 TASTEGRAPH_RELOAD=1
    )


if __name__ == "__main__":
    main()
