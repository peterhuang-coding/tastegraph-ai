"""Read-only data-ops snapshot endpoint.

GET /api/v1/data-ops/snapshot serves a whitelisted projection of a
pre-generated JSON snapshot named by TASTEGRAPH_DATA_OPS_SNAPSHOT. The
endpoint never starts collection, writes to the database, enables
sources, or reads any default location. Responses are Cache-Control:
no-store. POST (and other mutating methods) get 405 from the router.
"""
from __future__ import annotations

import json
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from taste_graph_ai.services.data_ops import build_view

router = APIRouter()

SNAPSHOT_PATH_ENV = "TASTEGRAPH_DATA_OPS_SNAPSHOT"
_UNAVAILABLE = {"detail": "数据运营快照暂不可用"}
_NO_STORE = {"Cache-Control": "no-store"}


@router.get("/api/v1/data-ops/snapshot")
def get_data_ops_snapshot():
    path = os.environ.get(SNAPSHOT_PATH_ENV)
    if not path:
        return JSONResponse(
            status_code=503, content=_UNAVAILABLE, headers=_NO_STORE
        )
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            raise ValueError("snapshot root is not a JSON object")
        view = build_view(raw)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # Never echo the configured path or parser internals.
        return JSONResponse(
            status_code=503, content=_UNAVAILABLE, headers=_NO_STORE
        )
    return JSONResponse(
        status_code=200,
        content=view,
        headers=_NO_STORE,
    )
