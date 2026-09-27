"""Behavior tests for the toy collection store (frozen wave1 contract).

All state lives in pytest-provided temporary DB/assets paths; no network,
no production data, no model calls.
"""
import base64
import hashlib
import io
import json
import zipfile
from datetime import datetime

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from taste_graph_ai.services.collections import CollectionError, CollectionStore


# ── synthetic image helpers ────────────────────────────────────────────────

def _image(size=(40, 30), color="white", mode="RGB"):
    return Image.new(mode, size, color)


def png_bytes(color=(255, 0, 0), size=(40, 30)):
    buf = io.BytesIO()
    _image(size=size, color=color).save(buf, "PNG")
    return buf.getvalue()


def webp_bytes(color=(0, 255, 0), size=(40, 30)):
    buf = io.BytesIO()
    _image(size=size, color=color).save(buf, "WEBP")
    return buf.getvalue()


def gif_bytes():
    buf = io.BytesIO()
    _image().save(buf, "GIF")
    return buf.getvalue()


def jpeg_bytes(color=(0, 0, 255), size=(40, 30), with_gps=False):
    img = _image(size=size, color=color)
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


def b64(data):
    return base64.b64encode(data).decode("ascii")


VALID_EVIDENCE = [{
    "title": "旧式陀螺图鉴",
    "url": "https://example.org/toys/top",
    "excerpt": "木质陀螺常见于二十世纪中期的儿童玩具。",
    "accessed_at": "2026-09-27",
    "scope": "介绍同时代木质玩具的一般背景",
    "limitations": "未直接收录本物件",
}]


def assert_aware(ts):
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None


# ── fixtures / payload builders ────────────────────────────────────────────

@pytest.fixture
def env(tmp_path):
    return tmp_path / "coll.db", tmp_path / "collection-assets"


@pytest.fixture
def store(env):
    return CollectionStore(env[0], env[1])


def create_payload(token="tok-1", **over):
    payload = {
        "create_token": token,
        "title": "木质陀螺",
        "known_info": "家里留下的旧玩具",
        "questions": ["是什么年代的？"],
        "personal_story": "外婆给的，记得小时候在院子玩。",
        "private_notes": "估价不对外",
    }
    payload.update(over)
    return payload


def make_item(store, **over):
    return store.create(create_payload(**over))


def add_photo(store, item_id, rev, raw=None, name="photo.jpg", **over):
    payload = {
        "expected_revision": rev,
        "name": name,
        "data_base64": b64(raw if raw is not None else jpeg_bytes()),
    }
    payload.update(over)
    return store.add_photo(item_id, payload)


def save_claim(store, doc, claim):
    return store.action(doc["id"], {
        "expected_revision": doc["revision"],
        "action": "save_claim",
        "claim": claim,
    })


def claim_payload(**over):
    claim = {
        "field": "生产年代",
        "text": "约二十世纪中期",
        "origin": "user",
        "certainty": "unknown",
        "review": "pending",
    }
    claim.update(over)
    return claim


def act(store, doc, name, **fields):
    payload = {"expected_revision": doc["revision"], "action": name}
    payload.update(fields)
    return store.action(doc["id"], payload)


# ── create / read / update ─────────────────────────────────────────────────

def test_create_returns_document_with_frozen_defaults(store):
    doc = store.create(create_payload())
    assert isinstance(doc["id"], str) and doc["id"]
    assert doc["category"] == "toy"
    assert doc["title"] == "木质陀螺"
    assert doc["known_info"] == "家里留下的旧玩具"
    assert doc["questions"] == ["是什么年代的？"]
    assert doc["personal_story"].startswith("外婆给的")
    assert doc["private_notes"] == "估价不对外"
    assert doc["target"] == {"label": "", "confirmed": False}
    assert doc["revision"] == 1
    assert_aware(doc["created_at"])
    assert_aware(doc["updated_at"])
    assert doc["photos"] == []
    assert doc["claims"] == []
    assert doc["research"] == {
        "id": None, "state": "needs_info", "phase": "",
        "error": None, "result": None,
    }
    assert doc["draft"] == {
        "title": "", "body": "", "image_ids": [], "claim_ids": [],
        "confirmed": False, "needs_review": False, "version": 0,
    }
    assert doc["exports"] == []



def test_create_token_is_idempotent_for_same_payload(store):
    d1 = store.create(create_payload())
    d2 = store.create(create_payload())
    assert d1["id"] == d2["id"]
    assert d2["revision"] == 1
    assert len(store.list_items()) == 1


def test_create_token_conflicts_for_different_payload(store):
    store.create(create_payload())
    with pytest.raises(CollectionError) as exc:
        store.create(create_payload(title="铁皮青蛙"))
    assert exc.value.status_code == 409
    assert len(store.list_items()) == 1


def test_create_validates_payload(store):
    def must_fail(**over):
        with pytest.raises(CollectionError) as exc:
            store.create(create_payload(**over))
        assert exc.value.status_code == 400

    must_fail(create_token="")
    must_fail(title="   ")
    must_fail(questions=["一？", "二？", "三？", "四？"])
    must_fail(questions="不是列表")
    must_fail(questions=[""])
    must_fail(known_info=123)
    must_fail(personal_story=5)
    assert len(store.list_items()) == 0


def test_list_items_returns_summary_rows(store):
    doc = make_item(store)
    doc = add_photo(store, doc["id"], doc["revision"])
    rows = store.list_items()
    assert rows == [{
        "id": doc["id"],
        "title": "木质陀螺",
        "category": "toy",
        "updated_at": doc["updated_at"],
        "revision": doc["revision"],
        "photo_count": 1,
        "research_state": "needs_info",
    }]


def test_get_unknown_is_404(store):
    with pytest.raises(CollectionError) as exc:
        store.get("does-not-exist")
    assert exc.value.status_code == 404


def test_update_partial_and_bumps_revision(store):
    doc = make_item(store)
    d2 = store.update(doc["id"], {"expected_revision": 1, "title": "新名字"})
    assert d2["title"] == "新名字"
    assert d2["known_info"] == doc["known_info"]
    assert d2["questions"] == doc["questions"]
    assert d2["private_notes"] == "估价不对外"
    assert d2["revision"] == 2
    assert d2["updated_at"] >= d2["created_at"]


def test_stale_update_is_409(store):
    doc = make_item(store)
    with pytest.raises(CollectionError) as exc:
        store.update(doc["id"], {"expected_revision": 5, "title": "x"})
    assert exc.value.status_code == 409
    assert store.get(doc["id"])["revision"] == 1


def test_update_unknown_item_is_404(store):
    with pytest.raises(CollectionError) as exc:
        store.update("nope", {"expected_revision": 1, "title": "x"})
    assert exc.value.status_code == 404


def test_mutation_requires_expected_revision(store):
    doc = make_item(store)
    with pytest.raises(CollectionError) as exc:
        store.update(doc["id"], {"title": "x"})
    assert exc.value.status_code == 400


# ── photos ─────────────────────────────────────────────────────────────────

def test_add_photo_defaults_private_preserves_original_and_preview(env, store):
    db, assets = env
    doc = make_item(store)
    raw = jpeg_bytes(with_gps=True)
    out = add_photo(store, doc["id"], 1, raw=raw, name="cover.jpg")
    photo = out["photos"][0]
    assert photo["private"] is True
    assert photo["allow_model"] is False
    assert photo["name"] == "cover.jpg"
    assert photo["role"] == ""
    assert photo["caption"] == ""
    assert photo["sha256"] == hashlib.sha256(raw).hexdigest()
    assert photo["url"] == (
        f"/api/v1/collections/{doc['id']}/photos/{photo['id']}"
    )
    assert out["revision"] == 2

    originals = list((assets / doc["id"] / "originals").glob("*"))
    previews = list((assets / doc["id"] / "previews").glob("*"))
    assert len(originals) == len(previews) == 1
    # Private original is preserved byte-for-byte, EXIF/GPS included.
    assert originals[0].read_bytes() == raw
    # Preview is a reencoded JPEG without metadata.
    pimg = Image.open(previews[0])
    assert pimg.format == "JPEG"
    exif = pimg.getexif()
    assert 0x8825 not in exif and len(exif) == 0
    assert store.photo_path(doc["id"], photo["id"]) == previews[0].resolve()


def test_accepts_png_and_webp(store):
    doc = make_item(store)
    d = add_photo(store, doc["id"], 1, raw=png_bytes(), name="a.png")
    assert d["photos"][0]["sha256"] == hashlib.sha256(png_bytes()).hexdigest()
    d = add_photo(store, doc["id"], d["revision"], raw=webp_bytes(), name="b.webp")
    assert len(d["photos"]) == 2


def test_photo_rejects_bad_base64(store):
    doc = make_item(store)
    with pytest.raises(CollectionError) as exc:
        store.add_photo(doc["id"], {
            "expected_revision": 1, "name": "x.jpg",
            "data_base64": "@@not-base64",
        })
    assert exc.value.status_code == 400


def test_photo_rejects_malformed_and_unsupported_format(store):
    doc = make_item(store)
    with pytest.raises(CollectionError) as exc:
        add_photo(store, doc["id"], 1, raw=b"this is not an image")
    assert exc.value.status_code == 400
    with pytest.raises(CollectionError) as exc:
        add_photo(store, doc["id"], 1, raw=gif_bytes(), name="a.gif")
    assert exc.value.status_code == 400


def test_photo_oversized_is_413(store):
    doc = make_item(store)
    with pytest.raises(CollectionError) as exc:
        add_photo(store, doc["id"], 1, raw=b"x" * (10 * 1024 * 1024 + 1))
    assert exc.value.status_code == 413


def test_photo_decoded_dimensions_limited(store):
    doc = make_item(store)
    with pytest.raises(CollectionError) as exc:
        add_photo(store, doc["id"], 1, raw=png_bytes(size=(5000, 4001)))
    assert exc.value.status_code == 400
    # Exactly 20 megapixels is accepted.
    out = add_photo(store, doc["id"], 1, raw=png_bytes(size=(5000, 4000)))
    assert len(out["photos"]) == 1


def test_photo_count_limited_to_18(store):
    doc = make_item(store)
    for i in range(18):
        doc = add_photo(
            store, doc["id"], doc["revision"],
            raw=png_bytes(color=(i % 250, 10, 10)),
        )
    assert len(doc["photos"]) == 18
    with pytest.raises(CollectionError) as exc:
        add_photo(store, doc["id"], doc["revision"], raw=jpeg_bytes())
    assert exc.value.status_code == 400


def test_same_byte_photo_duplicates_within_object(store):
    doc = make_item(store)
    raw = jpeg_bytes()
    d1 = add_photo(store, doc["id"], 1, raw=raw, name="a.jpg")
    d2 = add_photo(store, doc["id"], d1["revision"], raw=raw, name="b.jpg")
    assert len(d2["photos"]) == 1
    assert d2["photos"][0]["name"] == "a.jpg"
    assert d2["revision"] == d1["revision"]
    with pytest.raises(CollectionError) as exc:
        add_photo(store, doc["id"], 99, raw=raw)
    assert exc.value.status_code == 409


def test_same_bytes_across_objects_do_not_merge(env, store):
    a = make_item(store, token="t1")
    b = make_item(store, token="t2", title="铁皮青蛙")
    raw = jpeg_bytes()
    da = add_photo(store, a["id"], 1, raw=raw)
    db2 = add_photo(store, b["id"], 1, raw=raw)
    pa, pb = da["photos"][0], db2["photos"][0]
    assert pa["id"] != pb["id"]
    originals = [
        p for p in env[1].rglob("*")
        if p.is_file() and "originals" in p.parts
    ]
    assert len(originals) == 2
    assert {p.read_bytes() for p in originals} == {raw}


def test_photo_name_is_never_used_as_path(env, store):
    db, assets = env
    doc = make_item(store)
    out = add_photo(
        store, doc["id"], 1, raw=jpeg_bytes(),
        name="../../evil-SECRET.jpg",
    )
    assert out["photos"][0]["name"] == "evil-SECRET.jpg"
    assert not (assets.parent / "evil-SECRET.jpg").exists()
    assert not (assets / doc["id"] / "evil-SECRET.jpg").exists()
    out = add_photo(
        store, doc["id"], out["revision"], raw=png_bytes(),
        name="/etc/passwd",
    )
    assert out["photos"][-1]["name"] == "passwd"


def test_photo_path_scoped_to_object(store):
    a = make_item(store, token="t1")
    b = make_item(store, token="t2", title="其他玩具")
    da = add_photo(store, a["id"], 1, raw=jpeg_bytes())
    db2 = add_photo(store, b["id"], 1, raw=jpeg_bytes())
    pa, pb = da["photos"][0], db2["photos"][0]
    assert pa["id"] != pb["id"]
    assert store.photo_path(a["id"], pa["id"]).is_file()
    with pytest.raises(CollectionError) as exc:
        store.photo_path(a["id"], pb["id"])
    assert exc.value.status_code == 404
    with pytest.raises(CollectionError) as exc:
        store.photo_path(a["id"], "../x")
    assert exc.value.status_code == 404


# ── claims ─────────────────────────────────────────────────────────────────

def test_new_claim_defaults_and_version(store):
    doc = make_item(store)
    out = save_claim(store, doc, claim_payload())
    claim = out["claims"][0]
    assert claim["public"] is False
    assert claim["version"] == 1
    assert claim["evidence"] == []
    assert claim["id"]
    assert out["revision"] == 2


def test_external_supported_claim_requires_valid_evidence(store):
    doc = make_item(store)

    def must_fail(evidence):
        with pytest.raises(CollectionError) as exc:
            save_claim(store, doc, claim_payload(
                origin="external", certainty="supported", evidence=evidence))
        assert exc.value.status_code == 400

    must_fail([])
    must_fail([{}])
    base = {
        "title": "t", "url": "https://e.org/a", "excerpt": "e",
        "accessed_at": "2026-09-27", "scope": "s",
    }
    for key, bad in [("url", "ftp://e.org/a"), ("url", ""), ("url", "not-url"),
                     ("title", ""), ("excerpt", ""),
                     ("accessed_at", ""), ("scope", "")]:
        item = dict(base)
        item[key] = bad
        must_fail([item])

    out = save_claim(store, doc, claim_payload(
        origin="external", certainty="supported", evidence=VALID_EVIDENCE))
    saved = out["claims"][0]
    assert saved["evidence"][0]["url"] == VALID_EVIDENCE[0]["url"]
    # limitations is optional.
    evidence = [{k: v for k, v in VALID_EVIDENCE[0].items()
                 if k != "limitations"}]
    out = save_claim(store, out, claim_payload(
        field="材质", origin="external", certainty="supported", evidence=evidence))
    assert out["claims"][-1]["evidence"][0]["limitations"] == ""


def test_external_inferred_or_unknown_does_not_require_evidence(store):
    doc = make_item(store)
    out = save_claim(store, doc, claim_payload(
        origin="external", certainty="inferred"))
    assert out["claims"][0]["certainty"] == "inferred"


def test_claim_enums_and_text_validated(store):
    doc = make_item(store)
    for key, bad in [("origin", "dream"), ("certainty", "maybe"),
                     ("review", "whatever")]:
        with pytest.raises(CollectionError):
            save_claim(store, doc, claim_payload(**{key: bad}))
    with pytest.raises(CollectionError):
        save_claim(store, doc, claim_payload(text=" "))
    with pytest.raises(CollectionError):
        save_claim(store, doc, claim_payload(field=""))


def test_accepting_claim_does_not_upgrade_uncertainty(store):
    doc = make_item(store)
    d1 = save_claim(store, doc, claim_payload())
    d2 = save_claim(store, d1, {
        "id": d1["claims"][0]["id"], "field": "生产年代",
        "text": "约二十世纪中期", "origin": "user",
        "certainty": "unknown", "review": "accepted",
    })
    claim = d2["claims"][0]
    assert claim["review"] == "accepted"
    assert claim["certainty"] == "unknown"
    assert claim["origin"] == "user"
    assert claim["version"] == 2
    # Trying to sneak in a higher certainty while accepting cannot upgrade.
    d3 = save_claim(store, d2, {
        "id": claim["id"], "field": "生产年代",
        "text": "约二十世纪中期", "origin": "user",
        "certainty": "supported", "review": "accepted",
    })
    assert d3["claims"][0]["certainty"] == "unknown"


def test_correcting_external_claim_text_forces_review_and_flags_draft(store):
    doc = make_item(store)
    doc = add_photo(store, doc["id"], doc["revision"], raw=jpeg_bytes())
    photo_id = doc["photos"][0]["id"]
    doc = act(store, doc, "update_photo", photo_id=photo_id, private=False)
    doc = save_claim(store, doc, claim_payload(
        field="年代", text="二十世纪中期生产", origin="external",
        certainty="supported", review="accepted", public=True,
        evidence=VALID_EVIDENCE))
    claim_id = doc["claims"][0]["id"]
    doc = act(store, doc, "generate_draft", include_story=False)
    body = doc["draft"]["body"]
    assert body
    doc = act(store, doc, "save_draft", title="我的陀螺", body=body,
              image_ids=[photo_id], claim_ids=[claim_id],
              confirmed=True, privacy_checked=True)
    assert doc["draft"]["confirmed"] is True

    doc = save_claim(store, doc, {
        "id": claim_id, "field": "年代",
        "text": "可能是二十世纪七十年代", "origin": "external",
        "certainty": "supported", "review": "accepted",
    })
    claim = doc["claims"][0]
    assert claim["certainty"] == "unknown"
    assert claim["review"] == "pending"
    assert claim["evidence"] == []
    draft = doc["draft"]
    assert draft["needs_review"] is True
    assert draft["confirmed"] is False
    assert draft["body"] == body
    assert draft["title"] == "我的陀螺"


def test_renewed_evidence_allows_supported_after_text_change(store):
    doc = make_item(store)
    doc = save_claim(store, doc, claim_payload(
        origin="external", certainty="supported", review="accepted",
        public=True, evidence=VALID_EVIDENCE))
    renewed = [dict(VALID_EVIDENCE[0], title="新的图鉴证据",
                    url="https://example.org/updated")]
    doc = save_claim(store, doc, {
        "id": doc["claims"][0]["id"], "field": "生产年代",
        "text": "二十世纪七十年代生产", "origin": "external",
        "certainty": "supported", "review": "accepted",
        "evidence": renewed,
    })
    claim = doc["claims"][0]
    assert claim["certainty"] == "supported"
    assert claim["review"] == "accepted"
    assert claim["evidence"][0]["title"] == "新的图鉴证据"


def test_save_claim_rejects_foreign_or_missing_references(store):
    doc = make_item(store)
    with pytest.raises(CollectionError) as exc:
        store.action(doc["id"], {
            "expected_revision": doc["revision"], "action": "save_claim"})
    assert exc.value.status_code == 400


# ── draft ──────────────────────────────────────────────────────────────────

def _setup_graded_claims(store):
    doc = make_item(store)
    claims = [
        claim_payload(field="外观", text="表面涂有红漆", origin="user",
                      certainty="supported", review="accepted", public=True),
        claim_payload(field="产地", text="具体产地不明", origin="user",
                      certainty="unknown", review="accepted", public=True),
        claim_payload(field="工艺", text="可能是手工制作", origin="user",
                      certainty="inferred", review="pending", public=True),
        claim_payload(field="年代", text="生产于1965年", origin="external",
                      certainty="supported", review="disputed", public=True,
                      evidence=VALID_EVIDENCE),
        claim_payload(field="备注", text="主人私下的判断", origin="user",
                      certainty="supported", review="accepted", public=False),
    ]
    for claim in claims:
        doc = save_claim(store, doc, claim)
    return doc


def test_generate_draft_uses_only_accepted_public_claims(store):
    doc = _setup_graded_claims(store)
    out = act(store, doc, "generate_draft", include_story=False)
    draft = out["draft"]
    body = draft["body"]
    assert "观察细节" in body
    assert "已有证据支持" in body and "表面涂有红漆" in body
    assert "未知" in body and "具体产地不明" in body
    assert "可能是手工制作" not in body
    assert "生产于1965年" not in body
    assert "主人私下的判断" not in body
    ids = [c["id"] for c in out["claims"] if c["review"] == "accepted"
           and c["public"]]
    assert draft["claim_ids"] == ids
    assert draft["version"] == 1


def test_generate_draft_includes_story_only_when_explicitly_asked(store):
    doc = _setup_graded_claims(store)
    out = act(store, doc, "generate_draft", include_story=False)
    assert "外婆给的" not in out["draft"]["body"]

    second = make_item(store, token="other")
    second = save_claim(store, second, claim_payload(
        text="主人记得它的声音", certainty="supported",
        review="accepted", public=True))
    out = act(store, second, "generate_draft", include_story=True)
    assert "外婆给的" in out["draft"]["body"]
    assert "个人记忆" in out["draft"]["body"]


def test_generate_draft_twice_is_409(store):
    doc = _setup_graded_claims(store)
    out = act(store, doc, "generate_draft")
    with pytest.raises(CollectionError) as exc:
        act(store, out, "generate_draft")
    assert exc.value.status_code == 409


def test_save_draft_validates_references(store):
    doc = make_item(store, token="t1")
    doc = add_photo(store, doc["id"], doc["revision"], raw=jpeg_bytes())
    other = make_item(store, token="t2", title="别的玩具")
    other = add_photo(store, other["id"], other["revision"], raw=png_bytes())
    other_claim = save_claim(store, other, claim_payload(text="别的结论"))
    private_id = doc["photos"][0]["id"]

    payload_base = {
        "title": "t", "body": "b", "confirmed": False,
    }
    with pytest.raises(CollectionError) as exc:
        act(store, doc, "save_draft",
            image_ids=[other["photos"][0]["id"]], claim_ids=[], **payload_base)
    assert exc.value.status_code == 400
    with pytest.raises(CollectionError):
        act(store, doc, "save_draft",
            image_ids=[], claim_ids=[other_claim["claims"][0]["id"]],
            **payload_base)
    with pytest.raises(CollectionError):
        act(store, doc, "save_draft",
            image_ids=["missing"], claim_ids=[], **payload_base)
    # image must be public even when only saving (not confirming).
    with pytest.raises(CollectionError):
        act(store, doc, "save_draft",
            image_ids=[private_id], claim_ids=[], **payload_base)


def test_save_draft_confirmation_requirements(store):
    doc = make_item(store)
    doc = add_photo(store, doc["id"], doc["revision"], raw=jpeg_bytes())
    photo_id = doc["photos"][0]["id"]
    doc = act(store, doc, "update_photo", photo_id=photo_id, private=False)

    def confirm(**over):
        payload = {
            "title": "我的陀螺", "body": "正文内容",
            "image_ids": [photo_id], "claim_ids": [],
            "confirmed": True, "privacy_checked": True,
        }
        payload.update(over)
        return act(store, doc, "save_draft", **payload)

    with pytest.raises(CollectionError) as exc:
        confirm(privacy_checked=False)
    assert exc.value.status_code == 400
    with pytest.raises(CollectionError):
        confirm(title="")
    with pytest.raises(CollectionError):
        confirm(body=" ")
    with pytest.raises(CollectionError):
        confirm(image_ids=[])
    out = confirm()
    assert out["draft"]["confirmed"] is True
    assert out["draft"]["needs_review"] is False


def test_private_photo_change_invalidates_draft(store):
    doc = make_item(store)
    doc = add_photo(store, doc["id"], doc["revision"], raw=jpeg_bytes())
    photo_id = doc["photos"][0]["id"]
    doc = act(store, doc, "update_photo", photo_id=photo_id, private=False)
    doc = act(store, doc, "save_draft", title="t", body="b",
              image_ids=[photo_id], claim_ids=[],
              confirmed=True, privacy_checked=True)
    out = act(store, doc, "update_photo", photo_id=photo_id, private=True)
    draft = out["draft"]
    assert draft["confirmed"] is False
    assert draft["needs_review"] is True
    assert draft["image_ids"] == []
    assert draft["body"] == "b"
    # allow_model alone does not invalidate.
    out2 = act(store, out, "update_photo", photo_id=photo_id,
               private=False)
    out2 = act(store, out2, "save_draft", title="t", body="b",
               image_ids=[photo_id], claim_ids=[],
               confirmed=True, privacy_checked=True)
    out2 = act(store, out2, "update_photo", photo_id=photo_id,
               allow_model=True)
    assert out2["draft"]["confirmed"] is True


def test_remove_photo_invalidates_draft_and_deletes_files(env, store):
    db, assets = env
    doc = make_item(store)
    doc = add_photo(store, doc["id"], doc["revision"], raw=jpeg_bytes())
    photo_id = doc["photos"][0]["id"]
    doc = act(store, doc, "update_photo", photo_id=photo_id, private=False)
    doc = act(store, doc, "save_draft", title="t", body="b",
              image_ids=[photo_id], claim_ids=[],
              confirmed=True, privacy_checked=True)
    out = act(store, doc, "remove_photo", photo_id=photo_id)
    assert out["photos"] == []
    assert out["draft"]["confirmed"] is False
    assert out["draft"]["needs_review"] is True
    assert out["draft"]["image_ids"] == []
    item_dir = assets / doc["id"]
    assert not list((item_dir / "originals").glob("*"))
    assert not list((item_dir / "previews").glob("*"))


def test_reorder_photos_requires_all_ids_exactly_once(store):
    doc = make_item(store)
    doc = add_photo(store, doc["id"], doc["revision"], raw=jpeg_bytes())
    first = doc["photos"][0]["id"]
    doc = add_photo(store, doc["id"], doc["revision"], raw=png_bytes())
    second = doc["photos"][-1]["id"]

    with pytest.raises(CollectionError):
        act(store, doc, "reorder_photos", photo_ids=[first])
    with pytest.raises(CollectionError):
        act(store, doc, "reorder_photos", photo_ids=[first, first])
    with pytest.raises(CollectionError):
        act(store, doc, "reorder_photos", photo_ids=[first, second, first])
    out = act(store, doc, "reorder_photos", photo_ids=[second, first])
    assert [p["id"] for p in out["photos"]] == [second, first]


# ── research lifecycle ────────────────────────────────────────────────────

def ready_item(store, token="tok-1"):
    doc = make_item(store, token=token)
    doc = add_photo(store, doc["id"], doc["revision"], raw=jpeg_bytes())
    doc = act(store, doc, "confirm_target", label="木质陀螺", confirmed=True)
    return doc


def test_research_readiness_requires_target_photo_questions(store):
    doc = make_item(store, questions=[])
    doc = add_photo(store, doc["id"], doc["revision"], raw=jpeg_bytes())
    assert doc["research"]["state"] == "needs_info"
    doc = act(store, doc, "confirm_target", label="陀螺", confirmed=True)
    assert doc["research"]["state"] == "needs_info"
    doc = store.update(doc["id"], {
        "expected_revision": doc["revision"],
        "questions": ["是什么年代的？"],
    })
    assert doc["research"]["state"] == "ready"
    # Un-confirming returns to needs_info.
    doc = act(store, doc, "confirm_target", label="陀螺", confirmed=False)
    assert doc["research"]["state"] == "needs_info"


def test_begin_research_creates_run_and_blocks_parallel(store):
    doc = ready_item(store)
    run = store.begin_research(doc["id"], "research")
    assert isinstance(run, str) and run
    current = store.get(doc["id"])
    assert current["research"]["state"] == "running"
    assert current["research"]["id"] == run
    with pytest.raises(CollectionError) as exc:
        store.begin_research(doc["id"], "identify")
    assert exc.value.status_code == 409


def test_begin_research_needs_ready_state(store):
    doc = make_item(store)
    with pytest.raises(CollectionError) as exc:
        store.begin_research(doc["id"], "research")
    assert exc.value.status_code == 409


def test_finish_without_evidence_is_valid_awaiting_review(store):
    doc = ready_item(store)
    # Manual draft edits are never overwritten by worker completion.
    doc = act(store, doc, "save_draft", title="手工标题", body="手工正文",
              image_ids=[], claim_ids=[], confirmed=False)
    run = store.begin_research(doc["id"], "identify")
    result = {
        "summary": "现有资料无法确认具体型号",
        "evidence": [],
        "gaps": ["物件上没有铭文", "缺少更多角度照片"],
    }
    out = store.finish_research(doc["id"], run, result)
    research = out["research"]
    assert research["state"] == "awaiting_review"
    assert research["result"] == result
    assert research["error"] is None
    assert out["draft"]["title"] == "手工标题"
    assert out["draft"]["body"] == "手工正文"


def test_cancelled_run_rejects_late_completion(store):
    doc = ready_item(store)
    run = store.begin_research(doc["id"], "research")
    out = act(store, store.get(doc["id"]), "cancel_research")
    assert out["research"]["state"] == "cancelled"
    with pytest.raises(CollectionError) as exc:
        store.finish_research(doc["id"], run, {"evidence": []})
    assert exc.value.status_code == 409
    assert store.get(doc["id"])["research"]["state"] == "cancelled"


def test_superseded_run_rejects_late_completion(store):
    doc = ready_item(store)
    run1 = store.begin_research(doc["id"], "research")
    doc = act(store, store.get(doc["id"]), "cancel_research")
    run2 = store.begin_research(doc["id"], "research")
    assert run1 != run2
    with pytest.raises(CollectionError):
        store.finish_research(doc["id"], run1, {"evidence": []})
    current = store.get(doc["id"])
    assert current["research"]["state"] == "running"
    assert current["research"]["id"] == run2


def test_finish_with_error_marks_failed(store):
    doc = ready_item(store)
    run = store.begin_research(doc["id"], "research")
    out = store.finish_research(doc["id"], run, None, error="搜索服务超时")
    assert out["research"]["state"] == "failed"
    assert "超时" in out["research"]["error"]
    with pytest.raises(CollectionError):
        store.finish_research(doc["id"], run, None)


def test_cancel_requires_running_run(store):
    doc = ready_item(store)
    with pytest.raises(CollectionError) as exc:
        act(store, doc, "cancel_research")
    assert exc.value.status_code == 409


def test_interrupted_run_marked_failed_on_restart(env, store):
    db, assets = env
    doc = ready_item(store)
    store.begin_research(doc["id"], "research")
    restarted = CollectionStore(db, assets)
    out = restarted.recover_interrupted(
        doc["id"], "服务重启导致研究中断，可稍后重新开始")
    assert out["research"]["state"] == "failed"
    assert "中断" in out["research"]["error"]
    # Recovery on a non-running item is a no-op.
    again = restarted.recover_interrupted(doc["id"], "再次扫描")
    assert again["revision"] == out["revision"]
    assert again["research"]["state"] == "failed"


def test_start_research_action_not_configured_in_wave1(store):
    doc = ready_item(store)
    with pytest.raises(CollectionError) as exc:
        act(store, doc, "start_research", mode="research",
            allow_external=False)
    assert exc.value.status_code == 409
    assert "尚未配置" in str(exc.value)
    assert store.get(doc["id"])["research"]["state"] == "ready"


# ── export ────────────────────────────────────────────────────────────────

def ready_for_export(store, token="tok-1", with_gps=True,
                     raw=None, name="原始名字SECRET.jpg"):
    doc = make_item(
        store, token=token,
        private_notes="私密记号ZZ", known_info="已知记号KK")
    if raw is None:
        raw = jpeg_bytes(with_gps=with_gps)
    doc = add_photo(store, doc["id"], doc["revision"], raw=raw, name=name)
    photo_id = doc["photos"][0]["id"]
    doc = act(store, doc, "update_photo", photo_id=photo_id, private=False)
    doc = save_claim(store, doc, claim_payload(
        field="年代", text="二十世纪中期的木质陀螺", origin="external",
        certainty="supported", review="accepted", public=True,
        evidence=VALID_EVIDENCE))
    claim_id = doc["claims"][0]["id"]
    doc = act(store, doc, "generate_draft", include_story=False)
    body = doc["draft"]["body"]
    doc = act(store, doc, "save_draft", title="陀螺记录", body=body,
              image_ids=[photo_id], claim_ids=[claim_id],
              confirmed=True, privacy_checked=True)
    return doc, photo_id, claim_id, body


def _read_zip(store, doc, result):
    path = store.export_zip(doc["id"], result["export_id"])
    return path, zipfile.ZipFile(path)


def test_export_requires_confirmed_clean_draft_and_checklist(store):
    doc = make_item(store)
    with pytest.raises(CollectionError) as exc:
        act(store, doc, "export", privacy_checked=True)
    assert exc.value.status_code == 409

    doc, photo_id, claim_id, body = ready_for_export(store, token="tok-ready")
    with pytest.raises(CollectionError) as exc:
        act(store, doc, "export", privacy_checked=False)
    assert exc.value.status_code == 409

    # A disputed referenced claim blocks export.
    doc2, _, cid2, _ = ready_for_export(store, token="tok-2")
    doc2 = save_claim(store, doc2, {
        "id": cid2, "field": "年代",
        "text": "二十世纪中期的木质陀螺", "origin": "external",
        "certainty": "supported", "review": "disputed",
        "evidence": VALID_EVIDENCE,
    })
    with pytest.raises(CollectionError):
        act(store, doc2, "export", privacy_checked=True)


def test_export_creates_snapshot_without_private_data(store):
    doc, photo_id, claim_id, body = ready_for_export(store)
    result = act(store, doc, "export", privacy_checked=True)
    assert set(result) == {
        "export_id", "title", "body", "image_ids", "download_url"}
    assert result["title"] == "陀螺记录"
    assert result["body"] == body
    assert result["image_ids"] == [photo_id]
    assert result["download_url"] == (
        f"/api/v1/collections/{doc['id']}/exports/{result['export_id']}")

    path, zf = _read_zip(store, doc, result)
    names = zf.namelist()
    assert "title.txt" in names
    assert "body.txt" in names
    assert "evidence.json" in names
    images = [n for n in names if n.startswith("images/")]
    assert len(images) == 1
    assert zf.read("title.txt").decode("utf-8") == "陀螺记录"
    assert zf.read("body.txt").decode("utf-8") == body

    evidence = json.loads(zf.read("evidence.json"))
    assert [e["id"] for e in evidence] == [claim_id]
    entry = evidence[0]
    assert entry["text"] == "二十世纪中期的木质陀螺"
    assert entry["origin"] == "external"
    assert entry["certainty"] == "supported"
    assert entry["evidence"][0]["url"] == VALID_EVIDENCE[0]["url"]
    assert "private_notes" not in entry

    raw_zip = path.read_bytes()
    for banned in ["私密记号ZZ", "已知记号KK", "原始名字SECRET",
                   "估价", "外婆给的"]:
        assert banned.encode("utf-8") not in raw_zip
    assert all("SECRET" not in n for n in names)

    latest = store.get(doc["id"])
    record = latest["exports"][0]
    assert record["id"] == result["export_id"]
    assert record["content_sha256"] == hashlib.sha256(raw_zip).hexdigest()
    assert record["image_count"] == 1
    assert_aware(record["created_at"])
    assert record["download_url"] == result["download_url"]


def test_export_excludes_private_photos(store):
    doc, photo_id, claim_id, body = ready_for_export(store, with_gps=False)
    doc = add_photo(store, doc["id"], doc["revision"], raw=png_bytes(),
                    name="private.png")
    private_id = doc["photos"][-1]["id"]
    assert doc["photos"][-1]["private"] is True

    result = act(store, doc, "export", privacy_checked=True)
    path, zf = _read_zip(store, doc, result)
    images = [n for n in zf.namelist() if n.startswith("images/")]
    assert len(images) == 1
    image_bytes = zf.read(images[0])
    assert Image.open(io.BytesIO(image_bytes)).format == "JPEG"


def test_export_images_have_no_exif_or_gps(store):
    doc, photo_id, claim_id, body = ready_for_export(store, with_gps=True)
    result = act(store, doc, "export", privacy_checked=True)
    path, zf = _read_zip(store, doc, result)
    images = [n for n in zf.namelist() if n.startswith("images/")]
    exported = Image.open(io.BytesIO(zf.read(images[0])))
    exif = exported.getexif()
    assert 0x8825 not in exif and len(exif) == 0


def test_exports_are_immutable_after_later_edits(store):
    doc, photo_id, claim_id, body = ready_for_export(store)
    r1 = act(store, doc, "export", privacy_checked=True)
    p1 = store.export_zip(doc["id"], r1["export_id"])
    first_bytes = p1.read_bytes()

    doc = store.get(doc["id"])
    doc = store.update(doc["id"], {
        "expected_revision": doc["revision"], "title": "新的物件名"})
    assert p1.read_bytes() == first_bytes
    assert store.get(doc["id"])["exports"][0]["content_sha256"] == (
        hashlib.sha256(first_bytes).hexdigest())

    # A second export is a separate snapshot; the first one stays identical.
    r2 = act(store, doc, "export", privacy_checked=True)
    assert r2["export_id"] != r1["export_id"]
    assert p1.read_bytes() == first_bytes
    assert len(store.get(doc["id"])["exports"]) == 2


def test_export_zip_paths_are_bounded(store):
    doc, photo_id, claim_id, body = ready_for_export(store, token="t1")
    r = act(store, doc, "export", privacy_checked=True)

    other = make_item(store, token="t2", title="别的")
    with pytest.raises(CollectionError) as exc:
        store.export_zip(doc["id"], "missing-export")
    assert exc.value.status_code == 404
    with pytest.raises(CollectionError):
        store.export_zip(doc["id"], r["export_id"] + "../")
    with pytest.raises(CollectionError):
        store.export_zip(doc["id"], "../../etc/passwd")
    with pytest.raises(CollectionError):
        store.export_zip(other["id"], r["export_id"])

    path = store.export_zip(doc["id"], r["export_id"])
    assert path.is_file()
    assert zipfile.is_zipfile(path)


def test_unknown_action_is_400(store):
    doc = make_item(store)
    with pytest.raises(CollectionError) as exc:
        act(store, doc, "explode")
    assert exc.value.status_code == 400


def test_evidence_only_change_invalidates_confirmation(store):
    doc = make_item(store)
    doc = add_photo(store, doc['id'], doc['revision'], private=False)
    doc = save_claim(store, doc, claim_payload(origin='external', certainty='supported', review='accepted', public=True, evidence=VALID_EVIDENCE))
    claim = doc['claims'][0]
    doc = act(store, doc, 'save_draft', title='Edited title', body='My edited words', image_ids=[doc['photos'][0]['id']], claim_ids=[claim['id']], confirmed=True, privacy_checked=True)
    doc = save_claim(store, doc, dict(claim, evidence=[dict(VALID_EVIDENCE[0], limitations='New conflicting evidence')]))
    assert doc['draft']['needs_review'] and not doc['draft']['confirmed']
    assert doc['draft']['body'] == 'My edited words'


def test_identical_resent_evidence_cannot_support_changed_external_claim(store):
    doc = make_item(store)
    doc = save_claim(store, doc, claim_payload(origin='external', certainty='supported', review='accepted', evidence=VALID_EVIDENCE))
    doc = save_claim(store, doc, dict(doc['claims'][0], text='Entirely different production date'))
    assert doc['claims'][0]['certainty'] == 'unknown'
    assert doc['claims'][0]['review'] == 'pending'


def test_duplicate_draft_photo_refs_rejected(store):
    doc = make_item(store)
    doc = add_photo(store, doc['id'], doc['revision'], private=False)
    pid = doc['photos'][0]['id']
    with pytest.raises(CollectionError):
        act(store, doc, 'save_draft', title='Toy', body='Test', image_ids=[pid,pid], claim_ids=[])


@pytest.mark.parametrize('terminal',['awaiting_review','failed','cancelled'])
def test_list_preserves_real_terminal_research_state(store, terminal):
    doc=make_item(store);doc=add_photo(store,doc['id'],doc['revision'])
    doc=act(store,doc,'confirm_target',label='Toy',confirmed=True)
    rid=store.begin_research(doc['id'])
    if terminal=='cancelled':
        doc=act(store,store.get(doc['id']),'cancel_research')
    else:doc=store.finish_research(doc['id'],rid,{},error='Test failure' if terminal=='failed' else None)
    assert store.list_items()[0]['research_state']==terminal
    doc=store.update(doc['id'],{'expected_revision':doc['revision'],'private_notes':'Still local'})
    assert doc['research']['state']==terminal


def test_phone_orientation_is_baked_into_metadata_free_preview(store):
    im=Image.new('RGB',(30,50),'red');exif=im.getexif();exif[274]=6
    out=io.BytesIO();im.save(out,'JPEG',exif=exif)
    doc=make_item(store);doc=add_photo(store,doc['id'],doc['revision'],raw=out.getvalue())
    with Image.open(store.photo_path(doc['id'],doc['photos'][0]['id'])) as preview:
        assert preview.size==(50,30)
        assert not preview.getexif()
