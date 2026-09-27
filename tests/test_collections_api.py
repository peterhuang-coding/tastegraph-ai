"""API contract tests for the collections route factory.

Uses an isolated FastAPI app backed by temporary DB/assets paths.
No network beyond the in-process TestClient, no production data.
"""
import base64
import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from taste_graph_ai.api.routes.collections import create_router


def jpeg_bytes(with_gps=False):
    img = Image.new("RGB", (40, 30), (0, 0, 200))
    buf = io.BytesIO()
    if with_gps:
        exif = img.getexif()
        gps = {}
        gps[1] = "N"
        gps[2] = tuple(IFDRational(v, 1) for v in (39, 54, 0))
        gps[3] = "E"
        gps[4] = tuple(IFDRational(v, 1) for v in (116, 23, 0))
        exif[0x8825] = gps
        img.save(buf, "JPEG", quality=95, exif=exif)
    else:
        img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (30, 30), (200, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


EVIDENCE = [{
    "title": "玩具图鉴",
    "url": "https://example.org/toys",
    "excerpt": "二十世纪中期常见的儿童玩具。",
    "accessed_at": "2026-09-27",
    "scope": "同时代玩具背景",
}]


@pytest.fixture
def client(tmp_path):
    db, assets = tmp_path / "c.db", tmp_path / "assets"
    app = FastAPI()
    app.include_router(create_router(db, assets))
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


CREATE_JSON = {
    "create_token": "tok-1",
    "title": "木质陀螺",
    "known_info": "家里留下的旧玩具",
    "questions": ["是什么年代的？"],
    "personal_story": "外婆给的",
    "private_notes": "私密记号API",
}


def create_doc(client, **over):
    payload = dict(CREATE_JSON)
    payload.update(over)
    return client.post("/api/v1/collections", json=payload)


# ── create / list / get / update ──────────────────────────────────────────

def test_create_returns_unwrapped_document(client):
    res = create_doc(client)
    assert res.status_code == 200
    doc = res.json()
    assert doc["category"] == "toy"
    assert doc["title"] == "木质陀螺"
    assert doc["revision"] == 1
    assert doc["research"]["state"] == "needs_info"
    assert doc["draft"]["version"] == 0


def test_create_token_idempotency_and_conflict(client):
    d1 = create_doc(client).json()
    d2 = create_doc(client).json()
    assert d1["id"] == d2["id"]

    res = create_doc(client, title="铁皮青蛙")
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert isinstance(detail, str) and detail
    assert client.get("/api/v1/collections").json()["items"][0]["id"] == d1["id"]


def test_list_shape(client):
    doc = create_doc(client).json()
    rows = client.get("/api/v1/collections").json()["items"]
    assert rows == [{
        "id": doc["id"],
        "title": "木质陀螺",
        "category": "toy",
        "updated_at": doc["updated_at"],
        "revision": 1,
        "photo_count": 0,
        "research_state": "needs_info",
    }]


def test_get_detail_and_404(client):
    doc = create_doc(client).json()
    res = client.get(f"/api/v1/collections/{doc['id']}")
    assert res.status_code == 200
    assert res.json()["id"] == doc["id"]

    res = client.get("/api/v1/collections/missing")
    assert res.status_code == 404
    assert isinstance(res.json()["detail"], str)


def test_stale_update_is_409(client):
    doc = create_doc(client).json()
    res = client.post(f"/api/v1/collections/{doc['id']}", json={
        "expected_revision": 99, "title": "新"})
    assert res.status_code == 409
    ok = client.post(f"/api/v1/collections/{doc['id']}", json={
        "expected_revision": 1, "known_info": "更新后的已知信息"})
    assert ok.status_code == 200
    assert ok.json()["revision"] == 2


# ── photos ─────────────────────────────────────────────────────────────────

def upload(client, item_id, rev, raw=None, name="cover.jpg", **over):
    payload = {
        "expected_revision": rev,
        "name": name,
        "data_base64": base64.b64encode(raw if raw is not None else jpeg_bytes()).decode(),
    }
    payload.update(over)
    return client.post(f"/api/v1/collections/{item_id}/photos", json=payload)


def test_photo_upload_and_preview_bytes(client):
    doc = create_doc(client).json()
    res = upload(client, doc["id"], 1, raw=jpeg_bytes(with_gps=True))
    assert res.status_code == 200
    photo = res.json()["photos"][0]
    assert photo["private"] is True
    assert photo["allow_model"] is False

    preview = client.get(photo["url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(preview.content))
    assert img.format == "JPEG"
    exif = img.getexif()
    assert 0x8825 not in exif and len(exif) == 0


def test_png_preview_media_type(client):
    doc = create_doc(client).json()
    res = upload(client, doc["id"], 1, raw=png_bytes(), name="a.png")
    photo = res.json()["photos"][0]
    preview = client.get(photo["url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"


def test_duplicate_photo_returns_unchanged_document(client):
    doc = create_doc(client).json()
    d1 = upload(client, doc["id"], 1, raw=jpeg_bytes(), name="a.jpg")
    d2 = upload(client, doc["id"], d1.json()["revision"],
                raw=jpeg_bytes(), name="b.jpg")
    assert d2.status_code == 200
    body = d2.json()
    assert len(body["photos"]) == 1
    assert body["revision"] == d1.json()["revision"]


def test_photo_errors_are_per_file(client):
    doc = create_doc(client).json()
    res = upload(client, doc["id"], 1, raw=b"broken-bytes", name="bad.jpg")
    assert res.status_code == 400
    # Object survives the failed upload and accepts a good file.
    ok = upload(client, doc["id"], 1, raw=jpeg_bytes())
    assert ok.status_code == 200

    other = create_doc(client, create_token="tok-2", title="别的").json()
    foreign = ok.json()["photos"][0]
    res = client.get(
        f"/api/v1/collections/{other['id']}/photos/{foreign['id']}")
    assert res.status_code == 404


def test_oversized_upload_is_413(client):
    doc = create_doc(client).json()
    res = upload(client, doc["id"], 1, raw=b"x" * (10 * 1024 * 1024 + 1))
    assert res.status_code == 413


# ── end-to-end workflow ───────────────────────────────────────────────────

def test_evidence_to_export_workflow(client):
    doc = create_doc(client).json()
    item = doc["id"]

    up = upload(client, item, 1, raw=jpeg_bytes(with_gps=True))
    photo_id = up.json()["photos"][0]["id"]
    rev = up.json()["revision"]

    def action(rev, name, **fields):
        payload = {"expected_revision": rev, "action": name}
        payload.update(fields)
        return client.post(f"/api/v1/collections/{item}/actions", json=payload)

    res = action(rev, "update_photo", photo_id=photo_id, private=False)
    assert res.status_code == 200
    rev = res.json()["revision"]

    res = action(rev, "confirm_target", label="木质陀螺", confirmed=True)
    assert res.json()["research"]["state"] == "ready"
    rev = res.json()["revision"]

    res = action(rev, "save_claim", claim={
        "field": "年代", "text": "二十世纪中期的木质陀螺",
        "origin": "external", "certainty": "supported",
        "review": "accepted", "public": True, "evidence": EVIDENCE})
    assert res.status_code == 200
    claim_id = res.json()["claims"][0]["id"]
    rev = res.json()["revision"]

    res = action(rev, "generate_draft", include_story=False)
    assert res.status_code == 200
    body = res.json()["draft"]["body"]
    assert "二十世纪中期的木质陀螺" in body
    rev = res.json()["revision"]

    res = action(rev, "save_draft", title="陀螺记录", body=body,
                 image_ids=[photo_id], claim_ids=[claim_id],
                 confirmed=True, privacy_checked=True)
    assert res.status_code == 200
    rev = res.json()["revision"]

    res = action(rev, "export", privacy_checked=True)
    assert res.status_code == 200
    result = res.json()
    assert set(result) == {
        "export_id", "title", "body", "image_ids", "download_url"}

    download = client.get(result["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(download.content))
    assert "title.txt" in zf.namelist()
    assert "body.txt" in zf.namelist()
    assert "evidence.json" in zf.namelist()
    images = [n for n in zf.namelist() if n.startswith("images/")]
    assert len(images) == 1
    assert "私密记号API".encode() not in download.content
    exported = Image.open(io.BytesIO(zf.read(images[0])))
    assert len(exported.getexif()) == 0


def test_start_research_requires_explicit_consent(client):
    doc = create_doc(client).json()
    item = doc["id"]
    up = upload(client, item, 1)
    photo_id = up.json()["photos"][0]["id"]
    rev = up.json()["revision"]
    payload = {"expected_revision": rev, "action": "update_photo",
               "photo_id": photo_id, "private": False}
    rev = client.post(f"/api/v1/collections/{item}/actions",
                      json=payload).json()["revision"]
    payload = {"expected_revision": rev, "action": "confirm_target",
               "label": "陀螺", "confirmed": True}
    rev = client.post(f"/api/v1/collections/{item}/actions",
                      json=payload).json()["revision"]

    payload = {"expected_revision": rev, "action": "start_research",
               "mode": "research", "allow_external": False}
    res = client.post(f"/api/v1/collections/{item}/actions", json=payload)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "consent" in detail
    assert client.get(f"/api/v1/collections/{item}").json()[
        "research"]["state"] == "ready"


def test_unknown_action_and_bad_payload(client):
    doc = create_doc(client).json()
    res = client.post(
        f"/api/v1/collections/{doc['id']}/actions",
        json={"expected_revision": 1, "action": "nope"})
    assert res.status_code == 400
    res = client.post(
        f"/api/v1/collections/{doc['id']}/actions",
        json={"expected_revision": 1})
    assert res.status_code == 400


def test_router_construction_creates_nothing(tmp_path):
    db, assets = tmp_path / "x.db", tmp_path / "media"
    create_router(db, assets)
    assert not db.exists()
    assert not assets.exists()


def test_module_import_does_not_touch_production_paths():
    from taste_graph_ai import config
    # Importing the route module (already imported by this test module) must
    # never create the production DB or the private media directory.
    assert not config.DB_FILE.exists()
    assert not (config.DATA_DIR / "collections-media").exists()


def test_private_collection_rejects_cross_origin_and_untrusted_host(client):
    assert client.get('/api/v1/collections', headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.get('/api/v1/collections', headers={'Host':'evil.example'}).status_code == 403
    assert client.get('/api/v1/collections/capabilities').json()['research']['max_pages'] == 3
