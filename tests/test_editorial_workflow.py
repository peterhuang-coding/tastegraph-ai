import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def db_path(tmp_path):
    from taste_graph_ai.infrastructure.db.connection import SCHEMA
    path = tmp_path / "test.db"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("ALTER TABLE daily_packs ADD COLUMN is_curated INTEGER DEFAULT 0")
        for i in range(1, 5):
            db.execute("INSERT INTO images(id,url,page_url,created_at) VALUES(?,?,?,?)",
                       (str(i), f"https://example.org/{i}.jpg", "https://example.org/work/rams", "2026-09-12"))
        db.execute("INSERT INTO daily_packs(id,date,status,created_at) VALUES('p','2026-09-12','draft','2026-09-12')")
        db.executemany("INSERT INTO pack_images(pack_id,image_id,position) VALUES('p',?,?)",
                       [(str(i), i-1) for i in range(1,5)])
    return path


def test_unknown_date_stays_unknown_and_known_date_requires_evidence(db_path):
    from taste_graph_ai.services.editorial import save_annotation, get_annotation
    save_annotation(db_path, "1", {"image_form":"纪实", "dates":{"photo_created":None}}, actor="assistant")
    assert get_annotation(db_path, "1")["dates"]["photo_created"] is None
    with pytest.raises(ValueError, match="证据"):
        save_annotation(db_path, "1", {"dates":{"photo_created":{"value":"1980"}}}, actor="operator")


def test_annotations_are_scoped_events_not_taste_feedback(db_path):
    from taste_graph_ai.services.editorial import save_annotation, get_annotation
    save_annotation(db_path, "1", {"availability":"candidate", "reason":"能观察物件被使用"}, actor="assistant")
    row = get_annotation(db_path, "1")
    assert row["actor"] == "assistant"
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM editorial_events").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM feedback_log").fetchone()[0] == 0


def test_review_requires_real_thesis_and_each_images_role_evidence(db_path):
    from taste_graph_ai.services.editorial import save_pack_review
    with pytest.raises(ValueError):
        save_pack_review(db_path, "p", {"status":"approved", "thesis":"物件进入日常", "images":[]}, actor="operator")
    images=[{"image_id":str(i),"role":role,"evidence":"可见的人与物件", "reason":"延续使用关系"} for i,role in enumerate(["开场","动作","细节","收尾"],1)]
    saved=save_pack_review(db_path, "p", {"status":"approved","thesis":"物件进入日常","sequence_reason":"从场景进入使用动作，落到个人细节","images":images}, actor="operator")
    assert saved["status"] == "approved"
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM feedback_log").fetchone()[0] == 0


def test_review_rejects_unknown_or_duplicate_images(db_path):
    from taste_graph_ai.services.editorial import save_pack_review
    images=[{"image_id":"1","role":"开场","evidence":"可见","reason":"关联"}]*4
    with pytest.raises(ValueError):
        save_pack_review(db_path,"p",{"status":"approved","thesis":"主题","sequence_reason":"递进","images":images},actor="operator")


def test_selection_deduplicates_content_and_never_reuses_between_groups(tmp_path):
    from taste_graph_ai.services.editorial import choose_candidate_groups
    scored=[]
    for i, data in enumerate([b"same",b"same",b"other",b"third",b"fourth"],1):
        path=tmp_path/f"{i}.jpg"; path.write_bytes(data)
        img=SimpleNamespace(id=str(i),local_path=str(path),url=f"https://example.org/{i}.jpg",page_url="https://example.org/works/rams",source_id="")
        scored.append({"img":img,"total":1.0,"kws":[]})
    groups=choose_candidate_groups(scored,count=3,pack_size=2,annotations={"5":{"availability":"excluded"}})
    ids=[row["img"].id for group in groups for row in group]
    assert len(ids)==len(set(ids))==3
    assert "5" not in ids
    assert not ({"1","2"} <= set(ids))


def test_default_image_preparation_keeps_original_bytes(tmp_path):
    from PIL import Image
    from scripts.generate_publish_packs import _prepare_image
    source=tmp_path/"landscape.png"; out=tmp_path/"out.png"
    Image.new("RGB",(900,300),"white").save(source)
    _prepare_image(source,out)
    assert out.read_bytes()==source.read_bytes()

def test_submitted_pack_cannot_reorder_or_retitle(db_path):
    from taste_graph_ai.services.editorial import save_pack_review
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE publication_observations(pack_id TEXT,publication_status TEXT)")
        db.execute("INSERT INTO publication_observations VALUES('p','under_review')")
    notes=[{"image_id":str(i),"role":"细节","evidence":"可见","reason":"关联"} for i in range(4,0,-1)]
    with pytest.raises(ValueError,match="提交"):
        save_pack_review(db_path,"p",{"status":"approved","thesis":"新标题","sequence_reason":"递进","images":notes},actor="operator")


def test_export_reorder_has_exactly_one_original_per_position(db_path, tmp_path, monkeypatch):
    from PIL import Image
    from taste_graph_ai.api.routes import editorial as route
    from taste_graph_ai.services.editorial import save_pack_review
    monkeypatch.setattr(route,"DB_FILE",db_path)
    monkeypatch.setattr(route,"BASE_DIR",tmp_path)
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE publication_observations(pack_id TEXT,publication_status TEXT)")
        db.execute("INSERT INTO publication_observations VALUES('p','draft')")
        for i in range(1,5):
            image_path=tmp_path/f"source{i}.{ 'jpg' if i%2 else 'png'}"
            Image.new("RGB",(20,20),(i*20,10,10)).save(image_path)
            db.execute("UPDATE images SET local_path=? WHERE id=?",(str(image_path),str(i)))
    notes=[{"image_id":str(i),"role":"细节","evidence":"可见","reason":"关联"} for i in range(1,5)]
    payload={"status":"approved","thesis":"图集","sequence_reason":"递进","images":notes}
    save_pack_review(db_path,"p",payload,actor="operator")
    route.export("p")
    payload["images"]=list(reversed(notes))
    save_pack_review(db_path,"p",payload,actor="operator")
    out=route.export("p")
    folder=tmp_path/out["pack_path"]
    assert len(list(folder.glob("image-*"))) == 4
    metadata=json.loads((folder/"curation.json").read_text())
    assert metadata["image_ids"]==["4","3","2","1"]

def test_new_queue_links_canonical_editorial_id_without_publish_actions(tmp_path):
    from scripts.generate_publish_packs import _generate_queue_html
    folder=tmp_path/"pack-editorial-test";folder.mkdir()
    (folder/"curation.json").write_text(json.dumps({"pack_id":"fs_canonical","workflow_status":"needs_editorial_review","images":[]}))
    for name in ["title.txt","body.txt","hashtags.txt"]:(folder/name).write_text("待审核")
    _generate_queue_html(tmp_path,[folder],"2026-09-12")
    html=(tmp_path/"QUEUE.html").read_text()
    assert "editorial.html?pack=fs_canonical" in html
    assert "submitFeedback(" not in html
    assert "togglePublished(" not in html

@pytest.mark.parametrize("url",[
 "https://www.theguardian.com/artanddesign",
 "https://www.highsnobiety.com/the-hs-style-guide/",
 "https://www.highsnobiety.com/l/hs-style-guide/",
 "https://hypebeast.com/zh/change-language?locale=hk",
 "https://www.theguardian.com/preference/edition/int",
 "https://www.vogue.com/fashion-shows/designer/032c"])
def test_known_collection_routes_are_not_detail(url):
    from taste_graph_ai.services.provenance import classify_page
    assert classify_page(url) == "entry"


def test_website_sized_logo_is_filtered_without_banning_product_identity():
    from taste_graph_ai.services.provenance import is_site_asset
    assert is_site_asset("https://www.highsnobiety.com/static-assets/assets/images/logo-800x800.png")
    assert not is_site_asset("https://example.org/projects/logo-design-poster.jpg")


def test_source_label_does_not_use_unrelated_same_domain_collection():
    from scripts.generate_publish_packs import _build_source_lookup
    source=SimpleNamespace(id="wrong",url="https://www.vogue.com/fashion-shows/designer/032c",name="032c")
    lookup=_build_source_lookup([source])
    assert lookup("wrong","https://www.vogue.com/fashion-shows/pre-fall-2026/dior-homme") != "032c"


def test_review_state_changes_sync_daily_status(db_path):
    from taste_graph_ai.services.editorial import save_pack_review
    for review_status, expected in [("rejected","rejected"),("candidate","draft")]:
        save_pack_review(db_path,"p",{"status":review_status},actor="operator")
        with sqlite3.connect(db_path) as db:
            assert db.execute("SELECT status,is_curated FROM daily_packs WHERE id='p'").fetchone()==(expected,0)


def test_submitted_pack_cannot_be_rejected_as_editorial_candidate(db_path):
    from taste_graph_ai.services.editorial import save_pack_review
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE daily_packs SET status='published' WHERE id='p'")
    with pytest.raises(ValueError,match="提交"):
        save_pack_review(db_path,"p",{"status":"rejected"},actor="operator")


def test_mixed_queue_is_stamped_and_handles_legacy_folder(tmp_path):
    from scripts.generate_publish_packs import _generate_queue_html, TEMPLATE_VERSION
    modern=tmp_path/"new"; modern.mkdir()
    (modern/"curation.json").write_text(json.dumps({"pack_id":"ed_id","workflow_status":"needs_editorial_review"}))
    legacy=tmp_path/"old"; legacy.mkdir()
    (legacy/"image.jpg").write_bytes(b"legacy")
    _generate_queue_html(tmp_path,[modern,legacy],"2026-09-13")
    page=(tmp_path/"QUEUE.html").read_text()
    assert f"<!-- queue-template-v: {TEMPLATE_VERSION} -->" in page
    assert 'old/image.jpg' in page
    assert 'editorial.html?pack="' not in page
