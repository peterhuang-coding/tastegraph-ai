"""AiToEarn MCP publish wrapper — I1 (壳)。

等 MCP server 工具列表联调后,在 _TODO_MCP_INTEGRATION 标注位置填具体实现。

端点(全部先 501 Not Implemented):
  GET  /api/v1/publish/platforms          → 拉支持的平台列表(缓存 data/aitoearn_platforms.json)
  POST /api/v1/publish/upload             → 上传素材(multipart/form-data)
  POST /api/v1/publish/flow               → 创建发布 flow
  GET  /api/v1/publish/flow/{flow_id}     → 查询发布进度

安全约束(用户 hard rule):
  - XHS publish-08/20 plist 永久不恢复
  - _publish_disabled=true 永久保持
  - 不调任何 XHS 自动发布 API
  - 此 router 只对接 AiToEarn MCP,绝不通向 xhs_publisher
"""

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from taste_graph_ai.config import DATA_DIR


router = APIRouter(prefix="/api/v1/publish", tags=["publish"])

AITOERN_CACHE = DATA_DIR / "aitoearn_platforms.json"


# ── TODO_MCP_INTEGRATION ──────────────────────────────────────────
# 用户填完 ~/.claude.mcp.json 里的 x-api-key 后:
#   1. 在 server.py lifespan 里 init aitoearn MCP client(http transport)
#   2. 把 _get_aitoearn_client() 下面的 None 替换成实际 client
#   3. 把每个 endpoint 里的 TODO 注释替换成真实 MCP 调用
# 参考: https://aitoearn.cn/api/unified/mcp  (HTTP MCP endpoint)
# ──────────────────────────────────────────────────────────────────


def _get_aitoearn_client():
    """返回 AiToEarn MCP client 实例。联调前 None,联调后注入。"""
    # TODO_MCP_INTEGRATION: 初始化 MCP client
    #   from aitoearn_mcp import Client  # 待 MCP SDK 接入
    #   return Client(base_url="https://aitoearn.cn/api/unified/mcp",
    #                 api_key=os.environ["AITOERN_API_KEY"])
    return None


@router.get("/platforms")
async def list_platforms():
    """返回 aitoearn 支持的平台列表。

    TODO_MCP_INTEGRATION: 调 MCP list_platforms 工具,
    把结果缓存到 AITOERN_CACHE(TTL 24h)。
    """
    client = _get_aitoearn_client()
    if client is None:
        raise HTTPException(
            status_code=501,
            detail=(
                "AiToEarn MCP 尚未联调。"
                "请在 ~/.claude.mcp.json 填 x-api-key 后重启服务,"
                "或参考 taste_graph_ai/api/routes/publish.py:_get_aitoearn_client 完成 SDK 注入。"
            ),
        )

    # 缓存命中
    if AITOERN_CACHE.exists():
        try:
            cached = json.loads(AITOERN_CACHE.read_text())
            if cached.get("platforms"):
                return {
                    "source": "cache",
                    "cached_at": cached.get("cached_at"),
                    "platforms": cached["platforms"],
                }
        except (json.JSONDecodeError, OSError):
            pass

    # TODO_MCP_INTEGRATION: 真实实现
    #   platforms = await client.call("list_platforms")
    #   AITOERN_CACHE.write_text(json.dumps({"cached_at": "...", "platforms": platforms}))
    #   return {"source": "live", "platforms": platforms}
    raise HTTPException(status_code=501, detail="MCP client 初始化后填实现")


@router.post("/upload")
async def upload_material(request: Request):
    """上传素材(multipart/form-data)。

    TODO_MCP_INTEGRATION: 解析 multipart → 调 MCP upload_material 工具
    """
    client = _get_aitoearn_client()
    if client is None:
        raise HTTPException(status_code=501, detail="AiToEarn MCP 尚未联调")
    # TODO_MCP_INTEGRATION: 真实实现
    raise HTTPException(status_code=501, detail="待 MCP 联调后填实现")


@router.post("/flow")
async def create_flow(body: dict):
    """创建发布 flow。

    body 期望: {platform, account_id, content, items}
    TODO_MCP_INTEGRATION: 转发到 MCP create_flow 工具。
    """
    client = _get_aitoearn_client()
    if client is None:
        raise HTTPException(status_code=501, detail="AiToEarn MCP 尚未联调")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    # TODO_MCP_INTEGRATION: 真实实现
    raise HTTPException(status_code=501, detail="待 MCP 联调后填实现")


@router.get("/flow/{flow_id}")
async def get_flow_status(flow_id: str):
    """查询发布 flow 进度。"""
    client = _get_aitoearn_client()
    if client is None:
        raise HTTPException(status_code=501, detail="AiToEarn MCP 尚未联调")
    # TODO_MCP_INTEGRATION: 真实实现
    raise HTTPException(status_code=501, detail="待 MCP 联调后填实现")
