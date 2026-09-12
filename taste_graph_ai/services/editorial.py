"""Operational annotations and pack-level editorial decisions, separate from taste."""
import hashlib
import json
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

EDITORIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS image_editorial (
 image_id TEXT PRIMARY KEY, annotation_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pack_editorial (
 pack_id TEXT PRIMARY KEY, review_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'candidate',
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS editorial_events (
 id TEXT PRIMARY KEY, target_scope TEXT NOT NULL, target_id TEXT NOT NULL,
 actor TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
"""
DATE_FIELDS = {"photo_created", "object_original_design", "project_release", "page_published"}
AVAILABILITY = {"candidate", "priority", "needs_context", "excluded"}


def now():
    return datetime.now(timezone.utc).isoformat()


def connect(db_path):
    db = sqlite3.connect(str(db_path), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(EDITORIAL_SCHEMA)
    return db


def _dump(value):
    return json.dumps(value, ensure_ascii=False)


def _event(db, scope, target, actor, value):
    db.execute("INSERT INTO editorial_events VALUES(?,?,?,?,?,?)",
               (uuid.uuid4().hex, scope, target, actor, _dump(value), now()))


def validate_annotation(payload, actor):
    if not isinstance(payload, dict):
        raise ValueError("标签必须为对象")
    value = {k: payload.get(k, "") for k in (
        "image_form", "scene", "topic_hint", "reason", "source_evidence")}
    for key, text in value.items():
        if not isinstance(text, str) or len(text) > 4000:
            raise ValueError(f"{key} 必须为文本，最多4000字符")
    value["availability"] = payload.get("availability", "candidate")
    if value["availability"] not in AVAILABILITY:
        raise ValueError("无效的运营状态")
    value["source_verified"] = payload.get("source_verified", False) is True
    if value["source_verified"] and not _http_url(value["source_evidence"]):
        raise ValueError("已核验出处需要证据链接")
    value["dates"] = {}
    dates = payload.get("dates", {})
    if not isinstance(dates, dict) or set(dates) - DATE_FIELDS:
        raise ValueError("无效的年代字段")
    for key in DATE_FIELDS:
        fact = dates.get(key)
        if fact is not None:
            if (not isinstance(fact, dict) or not str(fact.get("value", "")).strip()
                    or not _http_url(fact.get("evidence_url", ""))):
                raise ValueError("年代事实必须附证据链接；未知请留空")
            fact = {"value": str(fact["value"])[:100], "evidence_url": fact["evidence_url"],
                    "note": str(fact.get("note", ""))[:1000]}
        value["dates"][key] = fact
    value["actor"] = actor
    value["updated_at"] = now()
    return value


def _http_url(value):
    return isinstance(value, str) and urlsplit(value).scheme in {"http", "https"} and bool(urlsplit(value).hostname)


def save_annotation(db_path, image_id, payload, actor="operator"):
    value = validate_annotation(payload, actor)
    db = connect(db_path)
    try:
        with db:
            if not db.execute("SELECT 1 FROM images WHERE id=?", (image_id,)).fetchone():
                raise ValueError("图片不存在")
            db.execute("INSERT INTO image_editorial VALUES(?,?,?) ON CONFLICT(image_id) DO UPDATE SET annotation_json=excluded.annotation_json,updated_at=excluded.updated_at",
                       (image_id, _dump(value), value["updated_at"]))
            _event(db, "image_annotation", image_id, actor, value)
        return value
    finally:
        db.close()


def get_annotation(db_path, image_id):
    db = connect(db_path)
    try:
        row = db.execute("SELECT annotation_json FROM image_editorial WHERE image_id=?", (image_id,)).fetchone()
        return json.loads(row[0]) if row else {}
    finally:
        db.close()


def load_annotations(db_path):
    db = connect(db_path)
    try:
        return {r[0]: json.loads(r[1]) for r in db.execute("SELECT image_id,annotation_json FROM image_editorial")}
    finally:
        db.close()


def save_pack_review(db_path, pack_id, payload, actor="operator"):
    status = payload.get("status", "candidate")
    if status not in {"candidate", "approved", "rejected"}:
        raise ValueError("无效审核状态")
    thesis = str(payload.get("thesis", "")).strip()
    sequence = str(payload.get("sequence_reason", "")).strip()
    images = payload.get("images", [])
    if not isinstance(images, list):
        raise ValueError("图片说明必须为列表")
    db = connect(db_path)
    try:
        with db:
            pack = db.execute("SELECT * FROM daily_packs WHERE id=?", (pack_id,)).fetchone()
            if not pack:
                raise ValueError("图集不存在")
            current_ids = [r[0] for r in db.execute("SELECT image_id FROM pack_images WHERE pack_id=? ORDER BY position", (pack_id,))]
            image_ids = [r.get("image_id") for r in images if isinstance(r, dict)]
            if len(image_ids) != len(images) or len(image_ids) != len(set(image_ids)):
                raise ValueError("每张图片必须唯一且有ID")
            if status == "approved":
                if not thesis or not sequence or not 1 <= len(images) <= 18:
                    raise ValueError("审核通过需要命题、顺序说明及1至18张图")
                if set(image_ids) != set(current_ids):
                    raise ValueError("审核必须覆盖图集全部图片")
                for row in images:
                    if not all(isinstance(row.get(k), str) and row[k].strip() for k in ("role","evidence","reason")):
                        raise ValueError("每张图都需要角色、画面证据及入选理由")
            elif any(i not in current_ids for i in image_ids):
                raise ValueError("说明中有不属于该图集的图片")
            submitted = pack["status"] == "published"
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_observations'").fetchone():
                cols={r[1] for r in db.execute("PRAGMA table_info(publication_observations)")}
                if "publication_status" in cols:
                    submitted = submitted or bool(db.execute("SELECT 1 FROM publication_observations WHERE pack_id=? AND publication_status IN ('under_review','published','removed','rejected') LIMIT 1",(pack_id,)).fetchone())
            if submitted and status != "approved":
                raise ValueError("已提交图集不能退回候选或拒绝")
            if submitted and image_ids and image_ids != current_ids:
                raise ValueError("已提交图集不能更改顺序")
            value = {"status":status, "thesis":thesis, "sequence_reason":sequence,
                     "images":images, "actor":actor, "updated_at":now()}
            db.execute("INSERT INTO pack_editorial VALUES(?,?,?,?) ON CONFLICT(pack_id) DO UPDATE SET review_json=excluded.review_json,status=excluded.status,updated_at=excluded.updated_at",
                       (pack_id, _dump(value), status, value["updated_at"]))
            if not submitted and status in {"candidate", "rejected"}:
                db.execute("UPDATE daily_packs SET status=?,is_curated=0 WHERE id=?", ("draft" if status == "candidate" else "rejected",pack_id))
            if status == "approved" and not submitted:
                db.execute("UPDATE daily_packs SET theme=?,why_today=?,status='selected',is_curated=1 WHERE id=?", (thesis,sequence,pack_id))
                for pos, image_id in enumerate(image_ids):
                    db.execute("UPDATE pack_images SET position=? WHERE pack_id=? AND image_id=?", (pos,pack_id,image_id))
            _event(db, "pack_editorial", pack_id, actor, value)
            return value
    finally:
        db.close()


def get_pack_review(db_path, pack_id):
    db = connect(db_path)
    try:
        row = db.execute("SELECT review_json FROM pack_editorial WHERE pack_id=?", (pack_id,)).fetchone()
        return json.loads(row[0]) if row else {"status":"candidate", "thesis":"", "sequence_reason":"", "images":[]}
    finally:
        db.close()


def source_domain(url):
    return (urlsplit(url or "").hostname or "unknown").lower().removeprefix("www.")


def choose_candidate_groups(scored, count, pack_size, annotations=None, exclude_ids=None):
    """Group by explicit topic or page; these are research candidates, not approved stories."""
    annotations = annotations or {}
    exclude_ids = exclude_ids or set()
    from taste_graph_ai.services.provenance import is_site_asset, classify_page
    seen_ids, seen_urls, seen_hashes = set(exclude_ids), set(), set()
    buckets = defaultdict(list)
    for item in sorted(scored, key=lambda row: row["total"], reverse=True):
        img = item["img"]
        note = annotations.get(img.id, {})
        if img.id in seen_ids or img.url in seen_urls or note.get("availability") in {"excluded", "needs_context"}:
            continue
        if is_site_asset(img.url, " ".join(getattr(img, "keywords", []))):
            continue
        try:
            digest = hashlib.sha256(Path(img.local_path).read_bytes()).hexdigest()
        except OSError:
            continue
        if digest in seen_hashes:
            continue
        seen_ids.add(img.id); seen_urls.add(img.url); seen_hashes.add(digest)
        page = getattr(img, "page_url", "") or ""
        topic = note.get("topic_hint", "").strip()
        if topic:
            key = ("topic", topic)
        elif classify_page(page) == "detail":
            key = ("page", page)
        else:
            key = ("research", img.id)
        buckets[key].append(item)
    groups, used_domains = [], set()
    while buckets and len(groups) < count:
        keys = sorted(buckets, key=lambda key: (
            source_domain(buckets[key][0]["img"].page_url) not in used_domains,
            key[0] == "topic", key[0] == "page", buckets[key][0]["total"]), reverse=True)
        key = keys[0]
        group = buckets[key][:pack_size]
        buckets[key] = buckets[key][pack_size:]
        if not buckets[key]:
            del buckets[key]
        if group:
            groups.append(group)
            used_domains.add(source_domain(group[0]["img"].page_url))
    return groups

def score_candidate(img, graph, annotation=None, liked_ids=None):
    """One explainable score shared by file and API candidate entry points."""
    from taste_graph_ai.services.provenance import classify_page
    annotation = annotation or {}
    labels = list(getattr(img, "keywords", []) or [])
    labels += [annotation[k] for k in ("image_form","scene","topic_hint") if annotation.get(k)]
    raw = graph.score_content(labels, source_id=getattr(img,"source_id",None),
                              source_url=getattr(img,"page_url",""))
    graph_part = max(-1.0, min(1.0, raw / 10.0))
    context = (0.2 if annotation.get("source_verified") else 0.0) + (
        0.1 if classify_page(getattr(img,"page_url","")) == "detail" else 0.0)
    priority = 0.1 if annotation.get("availability") == "priority" else 0.0
    liked = 0.1 if liked_ids and img.id in liked_ids else 0.0
    return {"total":0.5*graph_part+context+priority+liked,
            "graph":graph_part, "context":context, "priority":priority, "liked":liked}
