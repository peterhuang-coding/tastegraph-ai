"""Local operational tagging and editorial review, separate from preference feedback."""
import json
import shutil
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from taste_graph_ai.config import BASE_DIR, DB_FILE
from taste_graph_ai.services.editorial import (
    connect, get_pack_review, save_annotation, save_pack_review, now,
)

router = APIRouter(prefix="/api/v1/editorial", tags=["editorial"])


@router.get("/images")
def images(page: int = Query(1, ge=1), limit: int = Query(24, ge=1, le=100), q: str = "", annotated: bool = False):
    db = connect(DB_FILE)
    try:
        where = "i.local_path != ''"
        params = []
        if q:
            where += " AND (i.page_url LIKE ? OR i.keywords_json LIKE ? OR e.annotation_json LIKE ?)"
            params += ["%" + q + "%"] * 3
        if annotated:
            where += " AND e.image_id IS NOT NULL"
        total = db.execute(f"SELECT COUNT(*) FROM images i LEFT JOIN image_editorial e ON e.image_id=i.id WHERE {where}", params).fetchone()[0]
        rows = db.execute(f"""SELECT i.*,e.annotation_json FROM images i LEFT JOIN image_editorial e ON e.image_id=i.id
            WHERE {where} ORDER BY (e.image_id IS NOT NULL) DESC,e.updated_at DESC,i.created_at DESC,i.id
            LIMIT ? OFFSET ?""", params + [limit, (page-1)*limit]).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["annotation"] = json.loads(item.pop("annotation_json") or "{}")
            item["image_url"] = f"/api/v1/editorial/images/{item['id']}/file"
            item["local_available"] = Path(item["local_path"]).is_file()
            item["provenance"] = [dict(r) for r in db.execute("SELECT * FROM image_provenance WHERE image_id=? ORDER BY observed_at DESC LIMIT 5", (item["id"],))]
            result.append(item)
        return {"items":result, "page":page, "total":total}
    finally:
        db.close()


@router.get("/images/{image_id}/file")
def image_file(image_id: str):
    db = connect(DB_FILE)
    try:
        row = db.execute("SELECT local_path FROM images WHERE id=?", (image_id,)).fetchone()
    finally:
        db.close()
    if not row or not Path(row[0]).is_file():
        raise HTTPException(404, "原图当前不可读取")
    if Path(row[0]).suffix.lower() not in {".jpg",".jpeg",".png",".webp",".gif",".avif"}:
        raise HTTPException(415, "不是支持的图片文件")
    return FileResponse(row[0])


@router.post("/images/{image_id}")
def annotate(image_id: str, payload: dict):
    try:
        return save_annotation(DB_FILE, image_id, payload, actor="operator")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/packs")
def packs():
    db = connect(DB_FILE)
    try:
        rows = db.execute("""SELECT p.*,e.status AS editorial_status FROM daily_packs p
            LEFT JOIN pack_editorial e ON e.pack_id=p.id
            ORDER BY p.created_at DESC LIMIT 60""").fetchall()
        return {"items":[dict(row) for row in rows]}
    finally:
        db.close()


@router.get("/packs/{pack_id}")
def pack_detail(pack_id: str):
    db = connect(DB_FILE)
    try:
        row = db.execute("SELECT * FROM daily_packs WHERE id=?", (pack_id,)).fetchone()
        if not row:
            raise HTTPException(404, "图集不存在")
        items = [dict(r) for r in db.execute("""SELECT i.*,pi.position FROM pack_images pi
                JOIN images i ON i.id=pi.image_id WHERE pi.pack_id=? ORDER BY pi.position""", (pack_id,))]
    finally:
        db.close()
    return {"pack":dict(row), "images":items, "review":get_pack_review(DB_FILE,pack_id)}


@router.post("/packs")
def create_pack(payload: dict):
    ids = payload.get("image_ids", [])
    if not isinstance(ids,list) or not 1<=len(ids)<=18 or len(set(ids)) != len(ids):
        raise HTTPException(400,"请选择1至18张不同图片")
    pack_id = "ed_" + uuid.uuid4().hex[:16]
    thesis = str(payload.get("thesis","")).strip()
    db = connect(DB_FILE)
    try:
        with db:
            for image_id in ids:
                row = db.execute("SELECT local_path FROM images WHERE id=?", (image_id,)).fetchone()
                if not row or not Path(row[0]).is_file():
                    raise HTTPException(400, "所选图片不可用: " + str(image_id))
            db.execute("""INSERT INTO daily_packs(id,date,theme,status,created_at,is_curated)
                VALUES(?,?,?,'draft',?,0)""",(pack_id,date.today().isoformat(),thesis or "待定选题",now()))
            db.executemany("INSERT INTO pack_images(pack_id,image_id,position,user_action) VALUES(?,?,?,'unreviewed')",
                           [(pack_id, image_id, i) for i,image_id in enumerate(ids)])
    finally:
        db.close()
    return {"pack_id":pack_id, "status":"candidate"}


@router.post("/packs/{pack_id}/review")
def review(pack_id: str, payload: dict):
    try:
        return save_pack_review(DB_FILE, pack_id, payload, actor="operator")
    except ValueError as exc:
        raise HTTPException(400,str(exc))


@router.post("/packs/{pack_id}/export")
def export(pack_id: str):
    detail = pack_detail(pack_id)
    review = detail["review"]
    if review["status"] != "approved":
        raise HTTPException(409,"请先完成命题、角色与顺序审核")
    if detail["pack"]["status"] == "published":
        raise HTTPException(409,"已发布图集保留原记录")
    db = connect(DB_FILE)
    try:
        # A successful submission awaiting review must also remain immutable.
        existing = db.execute("SELECT 1 FROM publication_observations WHERE pack_id=? AND publication_status IN ('under_review','published','removed','rejected') LIMIT 1", (pack_id,)).fetchone()
        if existing:
            raise HTTPException(409,"已提交图集保留原记录")
    finally:
        db.close()
    import hashlib
    import tempfile
    # Each reviewed version has a separate export, preserving earlier files and order.
    version = hashlib.sha256(json.dumps(review,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:12]
    safe_id = hashlib.sha256(pack_id.encode()).hexdigest()[:12]
    parent = BASE_DIR / "posts" / detail["pack"]["date"]
    parent.mkdir(parents=True,exist_ok=True)
    folder = parent / ("editorial-" + safe_id + "-" + version)
    if not folder.exists():
        stage = Path(tempfile.mkdtemp(prefix=".editorial-export-",dir=parent))
        try:
            lookup = {row["id"]:row for row in detail["images"]}
            for i,note in enumerate(review["images"],1):
                src=Path(lookup[note["image_id"]]["local_path"])
                shutil.copy2(src,stage/f"image-{i:02d}{src.suffix}")
            curation={"pack_id":pack_id,"image_ids":[r["image_id"] for r in review["images"]],
                      "theme":review["thesis"],"workflow_status":"editorial_approved","editorial_review":review}
            (stage/"curation.json").write_text(json.dumps(curation,ensure_ascii=False,indent=2))
            (stage/"title.txt").write_text(review["thesis"])
            (stage/"body.txt").write_text("\n\n".join(row["reason"] for row in review["images"]))
            stage.rename(folder)
        finally:
            if stage.exists():shutil.rmtree(stage)
    return {"pack_id":pack_id,"pack_path":str(folder.relative_to(BASE_DIR)),"status":"editorial_approved"}
