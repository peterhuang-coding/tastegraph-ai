"""File generation shares published-image URL/content exclusions with API picks."""
import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("duplicate_by", ["content", "url"])
def test_generate_excludes_alias_of_under_review_image(tmp_path, monkeypatch, duplicate_by):
    from scripts import generate_publish_packs as generator
    from taste_graph_ai import config
    from taste_graph_ai.graph.taste_graph import TasteGraph
    from taste_graph_ai.infrastructure.db import connection
    from taste_graph_ai.services import images

    db_path = tmp_path / "data" / "test.db"
    db_path.parent.mkdir()
    for module in (config, connection, images):
        monkeypatch.setattr(module, "DB_FILE", db_path)
    for module in (generator, images):
        monkeypatch.setattr(module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(generator, "POSTS_DIR", tmp_path / "posts")
    monkeypatch.setattr(generator, "ensure_dirs", lambda: None)
    monkeypatch.setattr(generator, "get_container", lambda: SimpleNamespace(taste_graph=TasteGraph()))
    asyncio.run(connection.init_db())
    original = tmp_path / "original.jpg"
    duplicate = tmp_path / "duplicate.jpg"
    unique = tmp_path / "unique.jpg"
    original.write_bytes(b"published photograph")
    duplicate.write_bytes(b"published photograph" if duplicate_by == "content" else b"different bytes")
    unique.write_bytes(b"new photograph")
    original_url = "https://example.test/images/original.jpg"
    duplicate_url = original_url if duplicate_by == "url" else "https://example.test/images/duplicate.jpg"
    with sqlite3.connect(db_path) as db:
        db.execute("INSERT INTO daily_packs(id,date,status,created_at) VALUES('under-review','2026-09-12','draft','2026-09-12')")
        for id, path, url, status in (("original", original, original_url, "rejected"),
                ("a-duplicate", duplicate, duplicate_url, "pending"),
                ("z-unique", unique, "https://example.test/images/unique.jpg", "pending")):
            db.execute("INSERT INTO images(id,url,page_url,local_path,status,created_at) VALUES(?,?,?,?,?,?)",
                       (id, url, "https://example.test/project/chair", str(path), status, "2026-09-12"))
        db.execute("INSERT INTO pack_images VALUES('under-review','original',0,'unreviewed')")
        db.execute("INSERT INTO publication_observations(id,pack_id,platform,source,recorded_at,publication_status,raw_json) VALUES('obs','under-review','xiaohongshu','manual','2026-09-12','under_review','{}')")
    if duplicate_by == "url":
        original.unlink()
    folder = asyncio.run(generator.generate("2026-09-13", count=1, pack_size=9, skip_queue=True))
    manifests = list(folder.glob("*/curation.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text())["image_ids"] == ["z-unique"]
