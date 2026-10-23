"""Read-only whitelist projection for the data-ops snapshot.

build_view() accepts the parsed synthetic snapshot JSON and returns only
the fixed public contract::

    {"assembled_at": str | None,
     "sections": [{"id", "title", "as_of", "items": [{"label", "value", "note"}]}]}

Rules:
- only explicitly named scalar fields are projected; raw logs, paths,
  URLs, accounts and any unknown keys can never appear in the result;
- a missing/null/ill-typed value becomes None ("未知" in the UI);
  a real 0 stays 0;
- counts accept non-negative integers only (bool/float/NaN/Infinity/
  negative values become None, which also keeps strict JSON serialization
  safe);
- status/integrity values pass a fixed enum whitelist only, so hostile
  strings can never be echoed through them;
- timestamps are returned only when they are timezone-aware ISO-8601
  strings; naive timestamps are never guessed as UTC or local time;
  scheduled_date accepts calendar dates (YYYY-MM-DD) only;
- each section carries the evidence time (as_of) of its own source
  field; assembled_at is never reused as a section audit time.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

SECTION_TITLES = {
    "inventory": "库存 / 文件缺口",
    "sources": "来源 / 追溯",
    "updates": "更新 / 失败 / 备份",
    "publication": "候选 / 发布进度",
}

# Closed output vocabularies: anything else becomes None instead of being
# echoed (which would allow path/URL strings to ride out on these fields).
INTEGRITY_STATES = frozenset({"ok", "mismatch", "failed"})
DAY_STATES = frozenset({"succeeded", "running", "partial", "failed"})

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _dig(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
    return cur


def _count(value: Any) -> int | None:
    """Non-negative integer counts only; bool/float/negative -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _enum(value: Any, allowed: frozenset) -> str | None:
    if isinstance(value, str) and value in allowed:
        return value
    return None


def _time(value: Any) -> str | None:
    """Return a timezone-aware ISO-8601 timestamp; naive/broken -> None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    parsed = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        dt = datetime.fromisoformat(parsed)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # Never guess UTC or the browser/local timezone for a naive value.
        return None
    return text


def _date_only(value: Any) -> str | None:
    """Return a real calendar date YYYY-MM-DD; anything else -> None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _DATE_RE.fullmatch(text):
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def _target_range(value: Any) -> str | None:
    """Validate [low, high] of two non-negative ints; render 'low–high'."""
    if not isinstance(value, list) or len(value) != 2:
        return None
    low, high = value
    if isinstance(low, bool) or isinstance(high, bool):
        return None
    if not (isinstance(low, int) and isinstance(high, int)):
        return None
    if low < 0 or high < 0 or low > high:
        return None
    return "{}–{}".format(low, high)


def _time_note(value: Any) -> str | None:
    """Note for an item that carries its own timestamp value."""
    return None if _time(value) is not None else "时间未知"


def _item(label: str, value: Any, note: str | None = None) -> dict:
    return {"label": label, "value": value, "note": note}


def _inventory(raw: dict) -> dict:
    existence = _dig(raw, "database", "quality", "images_file_existence")
    coverage = _dig(raw, "database", "quality", "images_source_coverage")
    items = [
        _item("图片总数", _count(_dig(raw, "database", "counts", "images"))),
        _item("来源总数", _count(_dig(raw, "database", "counts", "sources"))),
        _item("有文件图片", _count(_dig(existence, "existing_file"))),
        _item("缺失文件图片", _count(_dig(existence, "missing_file"))),
        _item("无路径记录图片", _count(_dig(coverage, "missing_path"))),
    ]
    return {
        "id": "inventory",
        "title": SECTION_TITLES["inventory"],
        "as_of": _time(
            _dig(
                raw,
                "section_freshness",
                "database_quality_and_file_existence",
                "as_of",
            )
        ),
        "items": items,
    }


def _sources(raw: dict) -> dict:
    db = _dig(raw, "source_layers", "DB")
    peer = _dig(raw, "source_layers", "peer_research")
    archive = _dig(raw, "source_layers", "archive_reserve")
    coverage = _dig(raw, "database", "quality", "images_source_coverage")
    target = _target_range(_dig(archive, "target_size_range"))

    # Traceability/coverage statistics live under database.quality, so
    # their evidence time is the database-quality time, not the section's
    # own source-layers time. Each item note states the real evidence time.
    quality_as_of = _time(
        _dig(
            raw,
            "section_freshness",
            "database_quality_and_file_existence",
            "as_of",
        )
    )
    evidence_note = "证据时间：{}（数据库质量块，非来源层时刻）".format(
        quality_as_of if quality_as_of is not None else "未知"
    )

    items = [
        _item("DB 来源行", _count(_dig(db, "rows"))),
        _item("已批准来源", _count(_dig(db, "approved"))),
        _item("待审来源", _count(_dig(db, "pending"))),
        _item("驳回来源", _count(_dig(db, "rejected"))),
        _item(
            "已核实研究来源",
            _count(_dig(peer, "verified_research_sources")),
        ),
        _item("研究摄入变更", _count(_dig(peer, "ingestion_changes"))),
        _item(
            "新增完整视觉套",
            _count(_dig(archive, "new_complete_visual_sets")),
        ),
        _item(
            "完整视觉套目标区间",
            target,
            "仅为目标区间，非实测成熟度" if target is not None else None,
        ),
        _item(
            "追溯覆盖图片总数",
            _count(_dig(coverage, "total")),
            evidence_note,
        ),
        _item(
            "缺来源ID图片",
            _count(_dig(coverage, "missing_source_id")),
            evidence_note,
        ),
        _item(
            "来源ID未解析图片",
            _count(_dig(coverage, "unresolved_source_id")),
            evidence_note,
        ),
        _item(
            "有溯源记录图片",
            _count(_dig(raw, "database", "quality", "images_with_provenance")),
            "溯源记录/链接数不等于已下载图片数；" + evidence_note,
        ),
    ]
    return {
        "id": "sources",
        "title": SECTION_TITLES["sources"],
        "as_of": _time(
            _dig(
                raw,
                "section_freshness",
                "source_layers_and_update_chain",
                "as_of",
            )
        ),
        "items": items,
    }


def _updates(raw: dict) -> dict:
    backup = _dig(raw, "latest_operations", "lastBackup")
    active = _count(_dig(raw, "latest_operations", "activeCandidatePacks"))
    limit = _count(_dig(raw, "latest_operations", "activePackLimit"))
    queue_note = None
    if active is not None and limit is not None and active >= limit:
        queue_note = "队列已满"

    finished_at = _dig(backup, "finishedAt")
    items = [
        _item("最近备份成功", _bool(_dig(backup, "ok"))),
        _item("备份完成时间", _time(finished_at), _time_note(finished_at)),
        _item(
            "备份完整性",
            _enum(_dig(backup, "integrity"), INTEGRITY_STATES),
        ),
        _item(
            "备份数量核对一致",
            _bool(_dig(backup, "countsMatch")),
        ),
        _item("备份字节数", _count(_dig(backup, "backupBytes"))),
        _item("活动候选包", active, queue_note),
        _item("候选包上限", limit),
    ]

    day = _dig(raw, "today_at_snapshot")
    scheduled = _date_only(_dig(day, "scheduled_date"))
    date_label = scheduled if scheduled is not None else "日期未知"
    counts = _dig(day, "processed_status_counts")
    items.extend(
        [
            _item(
                "采集日 {} 状态".format(date_label),
                _enum(_dig(day, "status"), DAY_STATES),
                "原日期记录，不代表今日" if scheduled is not None else None,
            ),
            _item(
                "采集日 {} 已处理".format(date_label),
                _count(_dig(day, "processed_at_snapshot")),
            ),
            _item(
                "采集日 {} 新插入".format(date_label),
                _count(_dig(day, "inserted_at_snapshot")),
            ),
            _item(
                "采集日 {} 已下载".format(date_label),
                _count(_dig(counts, "downloaded")),
            ),
            _item(
                "采集日 {} 失败".format(date_label),
                _count(_dig(counts, "failed")),
            ),
            _item(
                "采集日 {} 跳过".format(date_label),
                _count(_dig(counts, "skipped")),
            ),
        ]
    )
    day_time = _time(_dig(day, "as_of"))
    evidence_note = "采集记录证据时间：" + (day_time or "未知")
    if day_time is not None:
        parsed = datetime.fromisoformat(day_time.replace("Z", "+00:00").replace("z", "+00:00"))
        age = (datetime.now(parsed.tzinfo) - parsed).total_seconds()
        if age > 86400:
            evidence_note += "；旧快照（超过24小时）"
        elif age < 0:
            evidence_note += "；证据时间异常：位于未来"
    for item in items[-6:]:
        item["note"] = "；".join(filter(None, [item["note"], evidence_note]))
    return {
        "id": "updates",
        "title": SECTION_TITLES["updates"],
        "as_of": _time(_dig(raw, "latest_operations_observed_at")),
        "items": items,
    }


def _blocked_slots(value: Any) -> int | None:
    if not isinstance(value, list):
        return None
    if not all(
        isinstance(slot, int)
        and not isinstance(slot, bool)
        and slot >= 0
        for slot in value
    ):
        return None
    return len(value)


def _publication(raw: dict) -> dict:
    pub = _dig(raw, "publication")
    blocked = _dig(pub, "editorial_blocked_slots")
    blocked_count = _blocked_slots(blocked)
    blocked_note = None
    if blocked_count:
        blocked_note = "阻塞槽位：" + "、".join(str(s) for s in blocked)
    items = [
        _item("有限批次容量", _count(_dig(pub, "finite_batch_capacity"))),
        _item("已占用槽位", _count(_dig(pub, "consumed"))),
        _item("剩余槽位", _count(_dig(pub, "remaining"))),
        _item(
            "本地日志提交数",
            _count(_dig(pub, "today_submitted_by_local_log")),
            "仅为提交记录，不等于公开",
        ),
        _item("每日上限", _count(_dig(pub, "daily_cap"))),
        _item("最早槽位", _count(_dig(pub, "earliest_slot"))),
        _item("编辑阻塞槽位数", blocked_count, blocked_note),
        _item("发布暂停", _bool(_dig(pub, "hold"))),
    ]
    return {
        "id": "publication",
        "title": SECTION_TITLES["publication"],
        "as_of": _time(_dig(pub, "as_of")),
        "items": items,
    }


def build_view(raw: Any) -> dict:
    """Project a parsed snapshot dict into the public read-only view."""
    if not isinstance(raw, dict):
        raw = {}
    return {
        "assembled_at": _time(raw.get("assembled_at")),
        "sections": [
            _inventory(raw),
            _sources(raw),
            _updates(raw),
            _publication(raw),
        ],
    }
