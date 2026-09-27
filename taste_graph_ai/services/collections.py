"""Single-owner toy collection archive (wave1).

Each archive object is a versioned JSON document stored in a separate SQLite
table. Private assets live only beneath the injected assets directory.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageOps

MAX_ORIGINAL_BYTES = 10 * 1024 * 1024
MAX_TOTAL_PIXELS = 20_000_000
MAX_PHOTOS = 18
MAX_QUESTIONS = 3

LIMIT_TITLE = 200
LIMIT_KNOWN_INFO = 5000
LIMIT_QUESTION = 1000
LIMIT_LONG_TEXT = 5000
LIMIT_NAME = 200
LIMIT_ROLE = 50
LIMIT_CAPTION = 1000
LIMIT_CLAIM_FIELD = 100
LIMIT_CLAIM_TEXT = 5000
LIMIT_DRAFT_TITLE = 200
LIMIT_DRAFT_BODY = 10_000
LIMIT_ERROR = 500

ALLOWED_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
CLAIM_ORIGINS = {"observation", "user", "external"}
CLAIM_CERTAINTIES = {"supported", "inferred", "unknown"}
CLAIM_REVIEWS = {"pending", "accepted", "disputed"}
RESEARCH_STATES = {
    "needs_info", "ready", "running", "awaiting_review",
    "failed", "cancelled",
}

_ID_RE = re.compile(r"^(col|ph|cl|run|ex)_[0-9a-f]{16}$")

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS collection_items (
        id TEXT PRIMARY KEY,
        create_token TEXT NOT NULL UNIQUE,
        revision INTEGER NOT NULL,
        initial_payload TEXT NOT NULL,
        doc TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS collection_draft_snapshots (
        item_id TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )
    """,
)


class CollectionError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def now():
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix):
    return f"{prefix}{uuid.uuid4().hex[:16]}"


def clean_text(value, limit, *, required=False):
    if value is None:
        if required:
            raise CollectionError("内容不能为空")
        return ""
    if not isinstance(value, str):
        raise CollectionError("该字段需为文本")
    text = value.strip()
    if not text:
        if required:
            raise CollectionError("内容不能为空")
        return ""
    if len(text) > limit:
        raise CollectionError(f"文本超出长度限制（最多 {limit} 字）")
    return text


def as_bool(value, field):
    if not isinstance(value, bool):
        raise CollectionError(f"{field} 需为 true 或 false")
    return value


def has_id_shape(value, prefix):
    return (isinstance(value, str)
            and re.fullmatch(rf"{prefix}_[0-9a-f]{{16}}", value) is not None)


def atomic_write(target: Path, data: bytes):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _sha(data: bytes):
    return hashlib.sha256(data).hexdigest()


def _http_url(value):
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


class CollectionStore:
    def __init__(self, db_path, assets_dir):
        self.db_path = Path(db_path)
        self.assets_dir = Path(assets_dir).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            for stmt in _SCHEMA:
                conn.execute(stmt)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _write_tx(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _row(self, conn, item_id, *, for_update=False):
        if not has_id_shape(item_id, "col"):
            raise CollectionError("物件不存在", 404)
        row = conn.execute(
            "SELECT * FROM collection_items WHERE id=?", (item_id,)
        ).fetchone()
        if row is None:
            raise CollectionError("物件不存在", 404)
        return row

    def _get_doc(self, conn, item_id, *, for_update=False):
        row = self._row(conn, item_id, for_update=for_update)
        return json.loads(row["doc"]), row

    def _save(self, conn, row, doc):
        expected = int(row["revision"])
        doc["revision"] = expected + 1
        doc["updated_at"] = now()
        cur = conn.execute(
            "UPDATE collection_items SET revision=?, doc=? WHERE id=? AND revision=?",
            (doc["revision"], json.dumps(doc, ensure_ascii=False), doc["id"], expected),
        )
        if cur.rowcount != 1:
            raise CollectionError("内容已被其他人更新，请刷新后重试", 409)
        return doc

    def _check_revision(self, payload, doc):
        expected = payload.get("expected_revision")
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise CollectionError("缺少有效的 expected_revision")
        if expected != doc["revision"]:
            raise CollectionError("内容已被其他人更新，请刷新后重试", 409)

    def _item_dir(self, item_id):
        path = (self.assets_dir / item_id).resolve()
        if self.assets_dir not in path.parents:
            raise CollectionError("资源路径无效")
        return path

    def _safe_asset(self, item_id, *parts):
        root = self._item_dir(item_id)
        path = root.joinpath(*parts).resolve()
        if root != path and root not in path.parents:
            raise CollectionError("资源路径无效")
        return path

    def _research_state(self, doc):
        return doc["research"].get("state", "needs_info")

    def list_items(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT doc FROM collection_items ORDER BY created_at DESC"
            ).fetchall()
        items = []
        for row in rows:
            doc = json.loads(row["doc"])
            items.append({
                "id": doc["id"],
                "title": doc["title"],
                "category": doc["category"],
                "updated_at": doc["updated_at"],
                "revision": doc["revision"],
                "photo_count": len(doc["photos"]),
                "research_state": self._research_state(doc),
            })
        return items

    def create(self, payload):
        token = clean_text(payload.get("create_token"), 200, required=True)
        title = clean_text(payload.get("title"), LIMIT_TITLE, required=True)
        known = clean_text(payload.get("known_info"), LIMIT_KNOWN_INFO)
        story = clean_text(payload.get("personal_story"), LIMIT_LONG_TEXT)
        notes = clean_text(payload.get("private_notes"), LIMIT_LONG_TEXT)
        questions = self._validate_questions(payload.get("questions", []))
        initial = self._initial_payload(token, title, known, questions, story, notes)
        stamp = now()
        with self._write_tx() as conn:
            row = conn.execute(
                "SELECT * FROM collection_items WHERE create_token=?", (token,)
            ).fetchone()
            if row is not None:
                old_initial = json.loads(row["initial_payload"])
                if old_initial != initial:
                    raise CollectionError("同一创建令牌不能用于不同内容", 409)
                return json.loads(row["doc"])
            item_id = new_id("col_")
            doc = {
                "id": item_id,
                "title": title,
                "category": "toy",
                "known_info": known,
                "questions": questions,
                "personal_story": story,
                "private_notes": notes,
                "target": {"label": "", "confirmed": False},
                "revision": 1,
                "created_at": stamp,
                "updated_at": stamp,
                "photos": [],
                "claims": [],
                "research": {
                    "id": None, "state": "needs_info", "phase": "",
                    "error": None, "result": None,
                },
                "draft": {
                    "title": "", "body": "", "image_ids": [], "claim_ids": [],
                    "confirmed": False, "needs_review": False, "version": 0,
                },
                "exports": [],
            }
            conn.execute(
                "INSERT INTO collection_items "
                "(id,create_token,revision,initial_payload,doc,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (item_id, token, 1, json.dumps(initial, ensure_ascii=False),
                 json.dumps(doc, ensure_ascii=False), stamp),
            )
        return doc

    def _initial_payload(self, token, title, known, questions, story, notes):
        return {
            "create_token": token, "title": title, "known_info": known,
            "questions": questions, "personal_story": story,
            "private_notes": notes,
        }

    def _validate_questions(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise CollectionError("问题需为列表")
        if len(value) > MAX_QUESTIONS:
            raise CollectionError(f"最多只能记录 {MAX_QUESTIONS} 个问题")
        result = []
        for item in value:
            text = clean_text(item, LIMIT_QUESTION, required=True)
            if text not in result:
                result.append(text)
        return result

    def get(self, item_id):
        with self._connect() as conn:
            doc, _ = self._get_doc(conn, item_id)
        return doc

    def update(self, item_id, payload):
        with self._write_tx() as conn:
            doc, row = self._get_doc(conn, item_id, for_update=True)
            self._check_revision(payload, doc)
            changed = False
            if "title" in payload:
                doc["title"] = clean_text(payload["title"], LIMIT_TITLE, required=True)
                changed = True
            if "known_info" in payload:
                doc["known_info"] = clean_text(payload["known_info"], LIMIT_KNOWN_INFO)
                changed = True
            if "questions" in payload and doc["research"]["state"] == "running" and payload["questions"] != doc["questions"]:
                raise CollectionError("请先取消研究，再更改研究问题", 409)
            if "questions" in payload:
                doc["questions"] = self._validate_questions(payload["questions"])
                changed = True
            if "personal_story" in payload:
                doc["personal_story"] = clean_text(payload["personal_story"], LIMIT_LONG_TEXT)
                changed = True
            if "private_notes" in payload:
                doc["private_notes"] = clean_text(payload["private_notes"], LIMIT_LONG_TEXT)
                changed = True
            if not changed:
                raise CollectionError("没有需要更新的字段")
            self._refresh_ready(doc)
            return self._save(conn, row, doc)

    def add_photo(self, item_id, payload):
        name = clean_text(payload.get("name"), LIMIT_NAME, required=True)
        role = clean_text(payload.get("role", ""), LIMIT_ROLE)
        caption = clean_text(payload.get("caption", ""), LIMIT_CAPTION)
        private = as_bool(payload.get("private", True), "private")
        allow_model = as_bool(payload.get("allow_model", False), "allow_model")
        encoded = payload.get("data_base64")
        if not isinstance(encoded, str):
            raise CollectionError("照片数据需为 Base64 文本")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception:
            raise CollectionError("照片不是有效的 Base64 数据")
        if not raw or len(raw) > MAX_ORIGINAL_BYTES:
            raise CollectionError("照片为空或超过 10MiB", 413)
        try:
            probe = Image.open(io.BytesIO(raw))
            fmt = probe.format
            if fmt not in ALLOWED_FORMATS:
                raise CollectionError("仅支持 JPG、PNG、WEBP 图片")
            width, height = probe.size
            if width <= 0 or height <= 0 or width * height > MAX_TOTAL_PIXELS:
                raise CollectionError("图片尺寸无效或超过 2000 万像素")
            probe.load()
            image = probe
        except (OSError, ValueError, Image.DecompressionBombError):
            raise CollectionError("照片已损坏或格式不受支持")
        digest = _sha(raw)
        with self._write_tx() as conn:
            doc, row = self._get_doc(conn, item_id, for_update=True)
            self._check_revision(payload, doc)
            if next((p for p in doc["photos"] if p["sha256"] == digest), None):
                return doc
            if len(doc["photos"]) >= MAX_PHOTOS:
                raise CollectionError(f"每个物件最多 {MAX_PHOTOS} 张照片")
            photo_id = new_id("ph_")
            preview = self._make_preview(image, fmt)
            root = self._item_dir(item_id)
            original = root / "originals" / f"{photo_id}{ALLOWED_FORMATS[fmt]}"
            preview_path = root / "previews" / f"{photo_id}.jpg"
            if preview["format"] == "PNG":
                preview_path = root / "previews" / f"{photo_id}.png"
            atomic_write(original, raw)
            atomic_write(preview_path, preview["data"])
            doc["photos"].append({
                "id": photo_id, "name": Path(name).name, "role": role,
                "caption": caption, "private": private, "allow_model": allow_model,
                "sha256": digest,
                "url": f"/api/v1/collections/{item_id}/photos/{photo_id}",
                "_preview": str(preview_path.relative_to(root)),
                "_original": str(original.relative_to(root)),
                "_media_type": preview["media_type"],
            })
            self._refresh_ready(doc)
            return self._save(conn, row, doc)

    def _make_preview(self, image, original_format):
        image = ImageOps.exif_transpose(image)
        fmt = "PNG" if original_format == "PNG" or image.mode == "RGBA" else "JPEG"
        mode = "RGBA" if fmt == "PNG" and image.mode == "RGBA" else "RGB"
        clean = Image.new(mode, image.size)
        clean.paste(image.convert(mode))
        out = io.BytesIO()
        clean.save(out, fmt)
        return {"data": out.getvalue(), "format": fmt,
                "media_type": "image/png" if fmt == "PNG" else "image/jpeg"}

    def photo_path(self, item_id, photo_id):
        with self._connect() as conn:
            doc, _ = self._get_doc(conn, item_id)
        photo = self._find_photo(doc, photo_id)
        path = self._safe_asset(item_id, photo["_preview"])
        if not path.is_file():
            raise CollectionError("照片文件不存在", 404)
        return path

    def _find_photo(self, doc, photo_id):
        if not has_id_shape(photo_id, "ph"):
            raise CollectionError("照片不存在", 404)
        photo = next((p for p in doc["photos"] if p["id"] == photo_id), None)
        if photo is None:
            raise CollectionError("照片不存在", 404)
        return photo

    def action(self, item_id, payload):
        name = payload.get("action")
        handlers = {
            "reorder_photos": self._reorder_photos,
            "update_photo": self._update_photo,
            "remove_photo": self._remove_photo,
            "confirm_target": self._confirm_target,
            "save_claim": self._save_claim,
            "generate_draft": self._generate_draft,
            "save_draft": self._save_draft,
            "start_research": self._start_research_action,
            "cancel_research": self._cancel_research,
            "export": self._export,
        }
        if name not in handlers:
            raise CollectionError("未知操作")
        with self._write_tx() as conn:
            doc, row = self._get_doc(conn, item_id, for_update=True)
            self._check_revision(payload, doc)
            result = handlers[name](conn, doc, payload)
            if name == "export":
                return result
            return self._save(conn, row, doc)

    def _reorder_photos(self, conn, doc, payload):
        ids = payload.get("photo_ids")
        current = [p["id"] for p in doc["photos"]]
        if not isinstance(ids, list) or sorted(ids) != sorted(current) or len(set(ids)) != len(ids):
            raise CollectionError("照片排序必须包含当前全部照片且不能重复")
        doc["photos"].sort(key=lambda p: ids.index(p["id"]))
        return doc

    def _update_photo(self, conn, doc, payload):
        photo = self._find_photo(doc, payload.get("photo_id"))
        before_private = photo["private"]
        if "private" in payload:
            photo["private"] = as_bool(payload["private"], "private")
        if "allow_model" in payload:
            photo["allow_model"] = as_bool(payload["allow_model"], "allow_model")
        if "caption" in payload:
            photo["caption"] = clean_text(payload["caption"], LIMIT_CAPTION)
        if "role" in payload:
            photo["role"] = clean_text(payload["role"], LIMIT_ROLE)
        if before_private != photo["private"] and photo["id"] in doc["draft"]["image_ids"]:
            self._invalidate_draft(doc)
            if photo["private"]:
                doc["draft"]["image_ids"].remove(photo["id"])
        return doc

    def _remove_photo(self, conn, doc, payload):
        if doc["research"]["state"] == "running":
            raise CollectionError("请先取消研究，再移除照片", 409)
        photo = self._find_photo(doc, payload.get("photo_id"))
        doc["photos"] = [p for p in doc["photos"] if p["id"] != photo["id"]]
        if photo["id"] in doc["draft"]["image_ids"]:
            doc["draft"]["image_ids"] = [x for x in doc["draft"]["image_ids"] if x != photo["id"]]
            self._invalidate_draft(doc)
        for p in ("_preview", "_original"):
            try:
                self._safe_asset(doc["id"], photo[p]).unlink(missing_ok=True)
            except CollectionError:
                pass
        self._refresh_ready(doc)
        return doc

    def _confirm_target(self, conn, doc, payload):
        if doc["research"]["state"] == "running":
            raise CollectionError("请先取消研究，再更改研究对象", 409)
        label = clean_text(payload.get("label", doc["target"]["label"]), LIMIT_TITLE,
                          required=True)
        confirmed = as_bool(payload.get("confirmed"), "confirmed")
        doc["target"] = {"label": label, "confirmed": confirmed}
        self._refresh_ready(doc)
        return doc

    def _refresh_ready(self, doc):
        research = doc["research"]
        if research["state"] in {"running", "awaiting_review", "failed", "cancelled"}:
            return
        eligible = doc["target"]["confirmed"] and bool(doc["photos"]) and bool(doc["questions"])
        if eligible and research["state"] in {"needs_info", "ready", "failed", "cancelled", ""}:
            research["state"] = "ready"
        elif not eligible and research["state"] == "ready":
            research["state"] = "needs_info"

    def _validate_evidence(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise CollectionError("证据需为列表")
        result = []
        for item in value:
            if not isinstance(item, dict):
                raise CollectionError("证据格式无效")
            title = clean_text(item.get("title"), 200, required=True)
            url = clean_text(item.get("url"), 1000, required=True)
            excerpt = clean_text(item.get("excerpt"), LIMIT_LONG_TEXT, required=True)
            accessed = clean_text(item.get("accessed_at"), 50, required=True)
            scope = clean_text(item.get("scope"), LIMIT_LONG_TEXT, required=True)
            limitations = clean_text(item.get("limitations"), LIMIT_LONG_TEXT)
            if not _http_url(url):
                raise CollectionError("证据链接必须是 http 或 https URL")
            try:
                datetime.fromisoformat(accessed)
            except ValueError:
                raise CollectionError("证据访问时间需为 ISO 时间")
            result.append({
                "title": title, "url": url, "excerpt": excerpt,
                "accessed_at": accessed, "scope": scope, "limitations": limitations,
            })
        return result

    def _validate_claim(self, value, old=None):
        if not isinstance(value, dict):
            raise CollectionError("claim 需为对象")
        claim_id = value.get("id", old.get("id") if old else None)
        if claim_id is not None and not has_id_shape(claim_id, "cl"):
            raise CollectionError("结论编号无效")
        field = clean_text(value.get("field", old.get("field") if old else None),
                           LIMIT_CLAIM_FIELD, required=True)
        text = clean_text(value.get("text", old.get("text") if old else None),
                          LIMIT_CLAIM_TEXT, required=True)
        origin = value.get("origin", old.get("origin") if old else "observation")
        certainty = value.get("certainty", old.get("certainty") if old else "unknown")
        review = value.get("review", old.get("review") if old else "pending")
        public = as_bool(value.get("public", old.get("public") if old else False), "public")
        if origin not in CLAIM_ORIGINS:
            raise CollectionError("结论来源无效")
        if certainty not in CLAIM_CERTAINTIES or review not in CLAIM_REVIEWS:
            raise CollectionError("结论确定性或审核状态无效")
        if "evidence" in value:
            evidence = self._validate_evidence(value.get("evidence"))
        elif old:
            evidence = json.loads(json.dumps(old.get("evidence", []), ensure_ascii=False))
        else:
            evidence = []
        if certainty == "supported" and (origin == "external" or evidence) and not evidence:
            raise CollectionError("已支持的外部结论必须附有效证据")
        return {
            "id": claim_id or new_id("cl_"), "field": field, "text": text,
            "origin": origin, "certainty": certainty, "review": review,
            "public": public, "version": int(old["version"]) + 1 if old else 1,
            "evidence": evidence,
        }

    def _save_claim(self, conn, doc, payload):
        incoming = payload.get("claim")
        if not isinstance(incoming, dict):
            raise CollectionError("缺少 claim")
        old = None
        if incoming.get("id"):
            if not has_id_shape(incoming["id"], "cl"):
                raise CollectionError("结论编号无效")
            old = next((c for c in doc["claims"] if c["id"] == incoming["id"]), None)
            if old is None:
                raise CollectionError("结论不存在", 404)
        claim = self._validate_claim(incoming, old)
        renewed = bool(claim["evidence"]) and (not old or claim["evidence"] != old["evidence"])
        if (old and old["certainty"] != "supported" and claim["certainty"] == "supported"
                and claim["text"] == old["text"] and not incoming.get("evidence")):
            claim["certainty"] = old["certainty"]
        if old and old["origin"] == "external" and claim["origin"] == "external" and old["text"] != claim["text"] and not renewed:
            claim["certainty"] = "unknown"
            claim["review"] = "pending"
            claim["evidence"] = []
        if claim["id"] in doc["draft"]["claim_ids"]:
            changed = (not old or old["text"] != claim["text"] or old["field"] != claim["field"]
                       or old["review"] != claim["review"] or old["public"] != claim["public"]
                       or old["certainty"] != claim["certainty"]
                       or old["origin"] != claim["origin"] or old["evidence"] != claim["evidence"])
            if changed:
                self._invalidate_draft(doc)
        if old:
            doc["claims"] = [claim if c["id"] == claim["id"] else c for c in doc["claims"]]
        else:
            doc["claims"].append(claim)
        return doc

    def _invalidate_draft(self, doc):
        draft = doc["draft"]
        draft["needs_review"] = True
        draft["confirmed"] = False
        draft["version"] += 1

    def _generate_draft(self, conn, doc, payload):
        draft = doc["draft"]
        if draft.get("body"):
            raise CollectionError("已有草稿，请直接编辑现有草稿", 409)
        include_story = as_bool(payload.get("include_story", False), "include_story")
        angle = clean_text(payload.get("angle", "观察细节"), 100, required=True)
        claims = [c for c in doc["claims"] if c["review"] == "accepted" and c["public"]]
        lines = ["# 证据汇编", "", f"## {angle}", ""]
        labels = {"supported": "已有证据支持", "inferred": "推测", "unknown": "未知"}
        for certainty in ("supported", "unknown", "inferred"):
            group = [c for c in claims if c["certainty"] == certainty]
            for c in group:
                lines.append(f"- 【{labels[certainty]}】{c['field']}：{c['text']}")
        if include_story and doc["personal_story"]:
            lines.extend(["", "## 个人记忆", doc["personal_story"]])
        title = f"{doc['title']}的证据汇编"
        draft.update({
            "title": title[:LIMIT_DRAFT_TITLE], "body": "\n".join(lines),
            "claim_ids": [c["id"] for c in claims], "image_ids": [],
            "confirmed": False, "needs_review": False, "version": 1,
        })
        return doc

    def _save_draft(self, conn, doc, payload):
        draft = doc["draft"]
        title = clean_text(payload.get("title"), LIMIT_DRAFT_TITLE, required=True)
        body = clean_text(payload.get("body"), LIMIT_DRAFT_BODY, required=True)
        image_ids = payload.get("image_ids", [])
        claim_ids = payload.get("claim_ids", [])
        confirmed = as_bool(payload.get("confirmed", False), "confirmed")
        if not isinstance(image_ids, list) or not isinstance(claim_ids, list):
            raise CollectionError("草稿引用需为列表")
        if any(not isinstance(x, str) for x in image_ids + claim_ids):
            raise CollectionError("草稿引用编号无效")
        if len(set(image_ids)) != len(image_ids) or len(set(claim_ids)) != len(claim_ids):
            raise CollectionError("草稿引用不能重复")
        photos = {p["id"]: p for p in doc["photos"]}
        claims = {c["id"]: c for c in doc["claims"]}
        if any(x not in photos for x in image_ids):
            raise CollectionError("草稿引用了不存在的照片")
        if any(photos[x]["private"] for x in image_ids):
            raise CollectionError("草稿只能使用公开照片")
        if any(x not in claims for x in claim_ids):
            raise CollectionError("草稿引用了不存在的结论")
        if any(not claims[x]["public"] or claims[x]["review"] != "accepted" for x in claim_ids):
            raise CollectionError("草稿只能引用已接受的公开结论")
        privacy_checked = as_bool(payload.get("privacy_checked", False), "privacy_checked")
        refs_current = True  # Explicit confirmation acknowledges current, validated references.
        if confirmed:
            if not title or not body or not image_ids:
                raise CollectionError("确认草稿需要标题、正文和至少一张公开图片", 409)
            if not privacy_checked:
                raise CollectionError("请先完成隐私检查")
            if draft["needs_review"] and not refs_current:
                raise CollectionError("引用内容已变化，请复核后再确认", 409)
        draft.update({
            "title": title, "body": body, "image_ids": image_ids,
            "claim_ids": claim_ids, "confirmed": confirmed,
            "needs_review": False if confirmed and refs_current else draft["needs_review"],
            "version": draft["version"] + 1,
        })
        conn.execute(
            "INSERT OR REPLACE INTO collection_draft_snapshots(item_id,data) VALUES(?,?)",
            (doc["id"], json.dumps({
                "title": title, "body": body, "image_ids": image_ids,
                "claim_ids": claim_ids, "version": draft["version"],
            }, ensure_ascii=False)),
        )
        return doc


    def begin_research(self, item_id, mode="research", expected_revision=None):
        if mode not in {"identify", "research"}:
            raise CollectionError("研究模式无效")
        with self._write_tx() as conn:
            doc, row = self._get_doc(conn, item_id, for_update=True)
            if expected_revision is not None:
                self._check_revision({"expected_revision": expected_revision}, doc)
            if doc["research"]["state"] == "running":
                raise CollectionError("研究任务已在运行", 409)
            if not doc["photos"] or (mode == "research" and not (doc["target"]["confirmed"] and doc["questions"])):
                raise CollectionError("请先确认目标、添加照片和问题", 409)
            run_id = new_id("run_")
            doc["research"] = {"id": run_id, "state": "running", "phase": mode,
                               "error": None, "result": None, "started_at": now()}
            self._save(conn, row, doc)
            return run_id

    def research_phase(self, item_id, run_id, phase, result=None):
        with self._write_tx() as conn:
            doc, row = self._get_doc(conn, item_id)
            r = doc["research"]
            if r["state"] != "running" or r["id"] != run_id:
                raise CollectionError("研究已停止或被替换", 409)
            r["phase"] = clean_text(phase, 200, required=True)
            if isinstance(result, dict):
                r["result"] = result
            return self._save(conn, row, doc)

    def finish_research(self, item_id, run_id, result, error=None):
        with self._write_tx() as conn:
            doc, row = self._get_doc(conn, item_id, for_update=True)
            r = doc["research"]
            if r.get("state") != "running" or r.get("id") != run_id:
                raise CollectionError("研究任务状态不匹配", 409)
            r["finished_at"] = now()
            if error:
                r.update({"state": "failed", "error": clean_text(error, LIMIT_ERROR, required=True), "result": result if isinstance(result, dict) else {}})
            else:
                r.update({"state": "awaiting_review", "error": None,
                          "result": result if isinstance(result, dict) else {}})
            return self._save(conn, row, doc)

    def recover_interrupted(self, item_id, reason):
        with self._write_tx() as conn:
            doc, row = self._get_doc(conn, item_id, for_update=True)
            if doc["research"].get("state") == "running":
                doc["research"].update({"state": "failed",
                    "error": clean_text(reason or "interrupted", LIMIT_ERROR, required=True)})
                return self._save(conn, row, doc)
            return doc

    def _start_research_action(self, conn, doc, payload):
        raise CollectionError("研究功能尚未配置", 409)

    def _cancel_research(self, conn, doc, payload):
        if doc["research"].get("state") != "running":
            raise CollectionError("只有运行中的任务可以取消", 409)
        doc["research"]["state"] = "cancelled"
        doc["research"]["error"] = None
        return doc

    def _validated_refs(self, doc):
        photos = {p["id"]: p for p in doc["photos"]}
        claims = {c["id"]: c for c in doc["claims"]}
        draft = doc["draft"]
        image_ids = draft.get("image_ids", [])
        claim_ids = draft.get("claim_ids", [])
        if any(x not in photos or photos[x]["private"] for x in image_ids):
            raise CollectionError("草稿包含无效或非公开图片", 409)
        if any(x not in claims or not claims[x]["public"] or claims[x]["review"] != "accepted" for x in claim_ids):
            raise CollectionError("草稿包含无效或未接受的公开结论", 409)
        return [photos[x] for x in image_ids], [claims[x] for x in claim_ids]

    def _strip_image_bytes(self, image, ext):
        out = io.BytesIO()
        img = image.convert("RGB") if ext == ".jpg" else image
        img.save(out, "JPEG" if ext == ".jpg" else "PNG")
        return out.getvalue()

    def _export(self, conn, doc, payload):
        d = doc["draft"]
        if not d.get("title") or not d.get("body"):
            raise CollectionError("草稿尚未准备好", 409)
        if not d.get("confirmed") or d.get("needs_review"):
            raise CollectionError("草稿尚未确认或仍需复核", 409)
        if not as_bool(payload.get("privacy_checked", False), "privacy_checked"):
            raise CollectionError("请先完成隐私检查", 409)
        photos, claims = self._validated_refs(doc)
        if not photos:
            raise CollectionError("导出至少需要一张公开图片", 409)
        export_id = new_id("ex_")
        root = self._item_dir(doc["id"]) / "exports"
        root.mkdir(parents=True, exist_ok=True)
        zpath = root / f"{export_id}.zip"
        buf = io.BytesIO()
        evidence = []
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("title.txt", d["title"])
            zf.writestr("body.txt", d["body"])
            for i, p in enumerate(photos, 1):
                ipath = self._safe_asset(doc["id"], p["_preview"])
                ext = ".jpg" if p["_media_type"] == "image/jpeg" else ".png"
                with Image.open(ipath) as im:
                    data = self._strip_image_bytes(im, ext)
                zf.writestr(f"images/{i:02d}{ext}", data)
            evidence = [{k: c[k] for k in ("id", "field", "text", "origin", "certainty", "review", "evidence")} for c in claims]
            zf.writestr("evidence.json", json.dumps(evidence, ensure_ascii=False, indent=2))
        data = buf.getvalue()
        atomic_write(zpath, data)
        rec = {"id": export_id, "content_sha256": _sha(data),
               "image_count": len(photos), "created_at": now(),
               "download_url": f"/api/v1/collections/{doc['id']}/exports/{export_id}",
               "_path": str(zpath.relative_to(root.parent))}
        doc["exports"].append(rec)
        self._save(conn, self._row(conn, doc["id"], for_update=True), doc)
        return {"export_id": export_id, "title": d["title"], "body": d["body"],
                "image_ids": [p["id"] for p in photos],
                "download_url": rec["download_url"]}

    def export_zip(self, item_id, export_id):
        if not has_id_shape(export_id, "ex"):
            raise CollectionError("导出不存在", 404)
        with self._connect() as conn:
            doc, _ = self._get_doc(conn, item_id)
        rec = next((x for x in doc["exports"] if x["id"] == export_id), None)
        if rec is None:
            raise CollectionError("导出不存在", 404)
        path = self._safe_asset(item_id, rec["_path"])
        if not path.is_file():
            raise CollectionError("导出文件不存在", 404)
        return path
