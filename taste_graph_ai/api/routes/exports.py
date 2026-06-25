from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from taste_graph_ai.config import EXPORTS_DIR

router = APIRouter(prefix="/api/v1/exports", tags=["exports"])


@router.get("/{filename}")
async def get_export(filename: str):
    filepath = EXPORTS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Export not found")
    return FileResponse(filepath, media_type="image/png")
