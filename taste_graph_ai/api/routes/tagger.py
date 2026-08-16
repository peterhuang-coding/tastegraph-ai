"""AI 自动风格标签 API — L1 入口。

POST /api/v1/tagger/spotcheck
  body: { images: [abs_path, ...], theme_hint?: str }
  返回: { count, results: [...], elapsed_ms }

注册方式参考 api/router.py(crawler.py 的 pattern)。
"""

import time
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from taste_graph_ai.services.tagger import ImageTaggerService


router = APIRouter(prefix="/api/v1/tagger", tags=["tagger"])


class SpotcheckTagRequest(BaseModel):
    images: List[str]
    theme_hint: str = ""


class SpotcheckTagResponse(BaseModel):
    count: int = 0
    results: list = []
    elapsed_ms: int = 0
    theme_hint: str = ""


# 单例 service(避免每次请求都重新拉 CLIP 模型)
_service: Optional[ImageTaggerService] = None


def _get_service() -> ImageTaggerService:
    global _service
    if _service is None:
        _service = ImageTaggerService()
    return _service


@router.post("/spotcheck", response_model=SpotcheckTagResponse)
async def tag_spotcheck(body: SpotcheckTagRequest):
    """对一组图片(默认就是抽检那 20 张)做 AI 风格打标。

    - images 接受绝对路径;前端从 feedback/spotcheck 拿到的 local_path 直接传过来即可
    - theme_hint 可选,用于 LLM context
    """
    t0 = time.time()
    svc = _get_service()
    results = await svc.tag_spotcheck(body.images, body.theme_hint or "")
    elapsed = int((time.time() - t0) * 1000)

    return SpotcheckTagResponse(
        count=len(results),
        results=results,
        elapsed_ms=elapsed,
        theme_hint=body.theme_hint or "",
    )
