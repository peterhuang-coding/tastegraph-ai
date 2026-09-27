from contextlib import asynccontextmanager
from fastapi import APIRouter, Depends, HTTPException, Request
from ipaddress import ip_address
from urllib.parse import urlsplit
from functools import lru_cache
from fastapi.responses import FileResponse

from taste_graph_ai.services.collections import CollectionError, CollectionStore

from taste_graph_ai.config import DATA_DIR, DB_FILE
from taste_graph_ai.services.collection_research import CollectionResearch

def create_router(db_path=DB_FILE, assets_dir=DATA_DIR / "collections-media"):
    @lru_cache(maxsize=1)
    def get_store():
        return CollectionStore(db_path, assets_dir)
    @lru_cache(maxsize=1)
    def get_engine():
        engine = CollectionResearch(get_store())
        engine.recover_interrupted()
        return engine

    @asynccontextmanager
    async def lifespan(app):
        get_engine()
        try:
            yield
        finally:
            get_engine().close()
            get_engine.cache_clear()

    def owner_only(request: Request):
        # Collection attachments are a local-owner feature, even if the graph is served on LAN.
        try:
            local = request.client and ip_address(request.client.host).is_loopback
        except ValueError:
            local = False
        host = urlsplit(str(request.url)).hostname
        origin = request.headers.get("origin")
        if not local or host not in {"localhost", "127.0.0.1", "::1"}:
            raise HTTPException(403, "藏品档案仅允许本机访问")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            raise HTTPException(403, "不允许跨来源访问私人档案")

    router = APIRouter(prefix="/api/v1/collections", lifespan=lifespan,
                       dependencies=[Depends(owner_only)])

    @router.get("/capabilities")
    def capabilities():
        return get_engine().capabilities()


    async def json_body(request):
        if request.headers.get("content-length", "0").isdigit() and int(request.headers.get("content-length", "0")) > 15 * 1024 * 1024:
            raise HTTPException(413, "请求超过 15MiB")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 15 * 1024 * 1024:
                raise HTTPException(413, "请求超过 15MiB")
        try:
            import json
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="请求体不是有效 JSON")

    def err(e):
        if isinstance(e, CollectionError):
            raise HTTPException(status_code=e.status_code, detail=e.message)
        raise

    @router.get("")
    def list_collection():
        try:
            return {"items": get_store().list_items()}
        except CollectionError as e:
            err(e)

    @router.post("")
    async def create(request: Request):
        try:
            p = await json_body(request)
            if not isinstance(p, dict):
                raise CollectionError("请求体需为对象", 400)
            return get_store().create(p)
        except CollectionError as e:
            err(e)

    @router.get("/{item_id}")
    def get_item(item_id: str):
        try:
            return get_store().get(item_id)
        except CollectionError as e:
            err(e)

    @router.post("/{item_id}")
    async def update(item_id: str, request: Request):
        try:
            p = await json_body(request)
            if not isinstance(p, dict):
                raise CollectionError("请求体需为对象", 400)
            return get_store().update(item_id, p)
        except CollectionError as e:
            err(e)

    @router.post("/{item_id}/photos")
    async def add_photo(item_id: str, request: Request):
        try:
            p = await json_body(request)
            if not isinstance(p, dict):
                raise CollectionError("请求体需为对象", 400)
            return get_store().add_photo(item_id, p)
        except CollectionError as e:
            err(e)

    @router.get("/{item_id}/photos/{photo_id}")
    def photo(item_id: str, photo_id: str):
        try:
            path = get_store().photo_path(item_id, photo_id)
            mt = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            return FileResponse(path, media_type=mt)
        except CollectionError as e:
            err(e)

    @router.post("/{item_id}/actions")
    async def action(item_id: str, request: Request):
        try:
            p = await json_body(request)
            if not isinstance(p, dict):
                raise CollectionError("请求体需为对象", 400)
            if p.get("action") == "start_research":
                return get_engine().start(item_id, p)
            if p.get("action") == "cancel_research":
                return get_engine().cancel(item_id, p)
            return get_store().action(item_id, p)
        except CollectionError as e:
            err(e)

    @router.get("/{item_id}/exports/{export_id}")
    def export(item_id: str, export_id: str):
        try:
            path = get_store().export_zip(item_id, export_id)
            return FileResponse(path, media_type="application/zip", filename=f"{export_id}.zip")
        except CollectionError as e:
            err(e)
    return router

router = create_router()
