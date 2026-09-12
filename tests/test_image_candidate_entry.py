"""Exercise the API candidate entry point without network, models, or production data."""
import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest

from taste_graph_ai.domain.enums import ImageStatus
from taste_graph_ai.domain.models import Image
from taste_graph_ai.graph.taste_graph import TasteGraph
from taste_graph_ai.services import images as image_service
from taste_graph_ai.services.editorial import connect


class Images:
    def __init__(self, items):
        self.items, self.marked, self.pages = items, [], []

    async def get_by_id(self, id):
        return next((item for item in self.items if item.id == id), None)

    async def list_by_status(self, status, limit=50):
        return [item for item in self.items if item.status == status][:limit]

    async def list_by_status_paginated(self, status, page=1, limit=50, require_local_file=False):
        self.pages.append((status, page))
        items = [item for item in self.items if item.status == status]
        return items[(page - 1) * limit:page * limit], len(items)

    async def mark_many_status(self, ids, status):
        self.marked.append((ids, status))


class Packs:
    def __init__(self):
        self.saved = []

    async def save_pack_image(self, image):
        self.saved.append(image)


class Feedback:
    async def get_liked_image_ids(self):
        return set()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from taste_graph_ai.infrastructure.db.connection import SCHEMA
    db_path = tmp_path / "data" / "taste_graph.db"
    db_path.parent.mkdir()
    with sqlite3.connect(db_path) as db:
        db.executescript(SCHEMA)
    monkeypatch.setattr(image_service, "DB_FILE", db_path, raising=False)
    monkeypatch.setattr(image_service, "BASE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(image_service, "get_container", lambda: SimpleNamespace(taste_graph=TasteGraph()))
    # Prevent the old implementation from loading CLIP while demonstrating failures.
    monkeypatch.setattr(image_service.ImageFetchService, "_clip_visual_score", staticmethod(lambda *args: 0), raising=False)
    monkeypatch.setattr(image_service.ImageFetchService, "_exploration_bonus", staticmethod(lambda *args: 0), raising=False)

    def image(id, status=ImageStatus.PENDING, page="https://example.com/project/chair", data=None):
        path = tmp_path / f"{id}.jpg"
        path.write_bytes(data or id.encode())
        return Image(id=id, url=f"https://example.com/images/{id}.jpg", page_url=page,
                     local_path=str(path), status=status)

    def service(items, annotations=None):
        with connect(db_path) as db:
            for id, annotation in (annotations or {}).items():
                db.execute("INSERT INTO image_editorial VALUES(?,?,?)", (id, json.dumps(annotation), "2026-09-12"))
        result = image_service.ImageFetchService.__new__(image_service.ImageFetchService)
        result.image_repo = Images(items)
        result.pack_repo = Packs()
        result.feedback_repo = Feedback()
        return result

    return SimpleNamespace(root=tmp_path, db=db_path, image=image, service=service)


def pick(service, **kwargs):
    return asyncio.run(service.pick_for_pack("candidate-pack", "unused draft theme", **kwargs))


def test_api_uses_shared_annotations_and_includes_candidates_beyond_first_200(setup):
    items = [setup.image(str(i)) for i in range(505)]
    notes = {item.id: {"availability": "excluded"} for item in items[:-1]}
    notes[items[-1].id] = {"availability": "priority", "topic_hint": "Chair in use"}
    service = setup.service(items, notes)
    assert [img.id for img in pick(service, count=9)] == ["504"]
    assert (ImageStatus.PENDING, 2) in service.image_repo.pages


def test_api_reconsiders_selected_candidates_and_saves_as_unreviewed(setup):
    image = setup.image("selected", status=ImageStatus.SELECTED)
    service = setup.service([image])
    assert pick(service) == [image]
    assert [link.user_action.value for link in service.pack_repo.saved] == ["unreviewed"]


def test_api_keeps_one_explicit_topic_group_instead_of_filling_to_nine(setup):
    a, b, unrelated = [setup.image(id, page=f"https://example.com/project/{id}") for id in ("a", "b", "other")]
    notes = {"a": {"topic_hint": "Chair in use"}, "b": {"topic_hint": "Chair in use"}}
    service = setup.service([a, b, unrelated], notes)
    assert {img.id for img in pick(service, count=9)} == {"a", "b"}


def test_api_uses_content_deduplication_across_different_urls(setup):
    first = setup.image("first", data=b"same bytes")
    duplicate = setup.image("duplicate", data=b"same bytes")
    other = setup.image("other")
    service = setup.service([first, duplicate, other])
    chosen = {img.id for img in pick(service, count=9)}
    assert len(chosen) == 2
    assert not {"first", "duplicate"} <= chosen


def test_api_excludes_published_log_db_history_invalid_files_and_explicit_ids(setup):
    ids = ["log", "db", "history", "excluded", "missing", "directory", "available"]
    items = [setup.image(id) for id in ids]
    (setup.root / "missing.jpg").unlink()
    items[5].local_path = str(setup.root)
    folder = setup.root / "posts" / "2026-09-11" / "post-001"
    folder.mkdir(parents=True)
    (folder / "curation.json").write_text(json.dumps({"image_ids": ["log"]}))
    (setup.db.parent / "publish_log.json").write_text(json.dumps([{"pack": "posts/2026-09-11/post-001"}]))
    with sqlite3.connect(setup.db) as db:
        db.executemany("INSERT INTO daily_packs(id,date,status,created_at) VALUES(?,?,?,?)", [
            ("published", "2026-09-11", "published", "2026-09-11"),
            ("history", "2026-09-11", "draft", "2026-09-11"),
        ])
        db.executemany("INSERT INTO pack_images VALUES(?,?,?,?)", [
            ("published", "db", 0, "approved"), ("history", "history", 0, "approved"),
        ])
        db.execute("INSERT INTO publish_history(id,pack_id,published_at) VALUES('record','history','2026-09-11')")
    service = setup.service(items)
    assert [img.id for img in pick(service, count=9, exclude_ids={"excluded"})] == ["available"]


def test_zero_requested_images_does_not_create_links(setup):
    service = setup.service([setup.image("one")])
    assert pick(service, count=0) == []
    assert service.pack_repo.saved == []


def test_legacy_score_wrapper_delegates_to_common_score(setup, monkeypatch):
    from taste_graph_ai.services import editorial
    calls = []
    def shared(img, graph, annotation=None, liked_ids=None):
        calls.append((img.id, annotation, liked_ids))
        return {"total": -0.42}
    monkeypatch.setattr(editorial, "score_candidate", shared)
    img = setup.image("one")
    service = setup.service([img])
    assert service._score_image_for_theme(img, "arbitrary", {"one"}) == -0.42
    assert calls == [("one", None, {"one"})]


def test_unrelated_images_from_entry_pages_remain_separate_research_candidates(setup):
    one = setup.image("one", page="https://example.com")
    two = setup.image("two", page="https://example.com/archive")
    service = setup.service([one, two])
    assert len(pick(service, count=9)) == 1


def test_submitted_and_published_observations_are_excluded_without_inventing_status(setup):
    with sqlite3.connect(setup.db) as db:
        db.execute("CREATE TABLE publication_observations(pack_id TEXT, publication_status TEXT)")
        for id, status in (("review", "under_review"), ("published", "published"), ("unknown", "unknown")):
            db.execute("INSERT INTO daily_packs(id,date,status,created_at) VALUES(?,?,'draft',?)", (id, "2026-09-11", "2026-09-11"))
            db.execute("INSERT INTO pack_images VALUES(?,?,0,'unreviewed')", (id, id))
            db.execute("INSERT INTO publication_observations VALUES(?,?)", (id, status))
    before = setup.db.read_bytes()
    assert image_service._load_published_image_ids() == {"review", "published"}
    assert setup.db.read_bytes() == before


def seed_legacy_post_log(path, ids):
    """Historical data contract; no dependency on an optional legacy UI router."""
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS image_post_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, image_id TEXT NOT NULL,
            post_id TEXT NOT NULL, platform TEXT NOT NULL DEFAULT 'xiaohongshu',
            post_url TEXT DEFAULT '', posted_at TEXT NOT NULL,
            undo_token TEXT NOT NULL, UNIQUE(image_id,post_id))""")
        db.executemany("INSERT INTO image_post_log(image_id,post_id,posted_at,undo_token) VALUES(?,'manual','2026-09-10T01:00:00Z','test-undo')", [(i,) for i in ids])


def test_confirmed_image_log_excludes_existing_rows_but_honors_undo(setup, monkeypatch):
    seed_legacy_post_log(setup.db, ["confirmed", "undone"])
    with sqlite3.connect(setup.db) as db:
        db.execute("DELETE FROM image_post_log WHERE image_id=?", ("undone",))
    before = setup.db.read_bytes()
    assert image_service._load_published_image_ids() == {"confirmed"}
    assert setup.db.read_bytes() == before


@pytest.mark.parametrize("duplicate_by", ["content", "url"])
def test_sequential_picks_exclude_prior_images_fingerprints_not_just_ids(setup, duplicate_by):
    first = setup.image("first", data=b"one picture")
    duplicate = setup.image("duplicate", data=b"one picture" if duplicate_by == "content" else b"other bytes")
    if duplicate_by == "url":
        duplicate.url = first.url
    unique = setup.image("unique")
    service = setup.service([first, duplicate, unique])
    selected = pick(service, count=1)
    assert [img.id for img in selected] == ["first"]
    next_pack = asyncio.run(service.pick_for_pack("second-pack", "", count=1,
                                                exclude_ids={img.id for img in selected}))
    assert [img.id for img in next_pack] == ["unique"]


@pytest.mark.parametrize("duplicate_by", ["content", "url"])
def test_published_images_fingerprints_apply_even_outside_candidate_statuses(setup, monkeypatch, duplicate_by):
    published = setup.image("published", status=ImageStatus.REJECTED, data=b"published bytes")
    duplicate = setup.image("duplicate", data=b"published bytes" if duplicate_by == "content" else b"different bytes")
    if duplicate_by == "url":
        duplicate.url = published.url
        (setup.root / "published.jpg").unlink()  # URL dedup survives a removed local original.
    unique = setup.image("unique")
    seed_legacy_post_log(setup.db, [published.id])
    service = setup.service([published, duplicate, unique])
    assert [img.id for img in pick(service, count=9)] == ["unique"]
