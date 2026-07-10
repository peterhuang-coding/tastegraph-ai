"""发布后 24h 自动回抓互动数据。

从 SQLite publish_history 表查询已发布超过 24h 但未回抓的帖子，
通过 CDP 连接小红书创作者后台获取互动数据，回灌 taste graph。

Usage:
    python scripts/auto_feedback.py            # 回抓超过 24h 的未抓帖子
    python scripts/auto_feedback.py --dry-run  # 预览但不录入
    python scripts/auto_feedback.py --days 48  # 回抓 48h 前的帖子
    python scripts/auto_feedback.py --all      # 回抓所有未回抓的帖子
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

# Ensure project root is in sys.path so taste_graph_ai package is importable.
# This handles both "python scripts/auto_feedback.py" and "python -m scripts.auto_feedback".
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from taste_graph_ai.config import BASE_DIR, DATA_DIR
from taste_graph_ai.infrastructure.db.connection import get_db

# ---------------------------------------------------------------------------
# CDP publisher import (may fail if Chrome is not running — handled gracefully)
# ---------------------------------------------------------------------------
try:
    SCRIPT_DIR = str(BASE_DIR / "xhs_publisher")
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)
    from cdp_publish import XiaohongshuPublisher, CDPError
except ImportError as exc:
    XiaohongshuPublisher = None  # type: ignore
    CDPError = Exception
    _import_error = exc

try:
    from scripts.publish_feedback import record_publish_metrics
except ImportError:
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    from publish_feedback import record_publish_metrics

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DAYS = 1  # 24h
MAX_PAGE_SIZE = 50  # content-data page size


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def ensure_feedback_columns(db: aiosqlite.Connection) -> None:
    """Add feedback_fetched and fetched_at columns to publish_history if absent."""
    cursor = await db.execute("PRAGMA table_info(publish_history)")
    columns = {row[1] for row in await cursor.fetchall()}
    if "feedback_fetched" not in columns:
        await db.execute(
            "ALTER TABLE publish_history ADD COLUMN feedback_fetched INTEGER DEFAULT 0"
        )
    if "fetched_at" not in columns:
        await db.execute(
            "ALTER TABLE publish_history ADD COLUMN fetched_at TEXT DEFAULT ''"
        )
    await db.commit()


async def get_pending_posts(
    db: aiosqlite.Connection,
    days: float | None = None,
    fetch_all: bool = False,
) -> list[dict[str, Any]]:
    """Query publish_history for posts that need feedback fetching.

    Returns rows for posts that:
    - Have feedback_fetched = 0 or NULL
    - Were published more than `days` ago (or any age if fetch_all)
    """
    conditions = ["(ph.feedback_fetched IS NULL OR ph.feedback_fetched = 0)"]
    params: list[Any] = []

    if not fetch_all:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days or DEFAULT_DAYS)).isoformat()
        conditions.append("ph.published_at <= ?")
        params.append(cutoff)

    where_clause = " AND ".join(conditions)
    cursor = await db.execute(
        f"""SELECT ph.*, dp.theme, dp.title_options_json
        FROM publish_history ph
        LEFT JOIN daily_packs dp ON ph.pack_id = dp.id
        WHERE {where_clause}
        ORDER BY ph.published_at ASC""",
        params,
    )
    return [dict(row) for row in await cursor.fetchall()]


async def mark_fetched(db: aiosqlite.Connection, record_id: str) -> None:
    """Mark a publish_history record as feedback-fetched."""
    now = datetime.now(timezone.utc).isoformat()
    await db.execute(
        "UPDATE publish_history SET feedback_fetched = 1, fetched_at = ? WHERE id = ?",
        (now, record_id),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Content data matching
# ---------------------------------------------------------------------------

def _parse_metric(value: Any) -> int:
    """Parse a metric value that might be int, str, or '-'.

    The content data API returns '-' for missing/empty metrics.
    """
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if value == "-" or not value:
            return 0
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def match_note(
    rows: list[dict[str, Any]],
    pack_id: str,
    title: str | None = None,
) -> dict[str, Any] | None:
    """Match a note from content data rows by note_id (_id) or title.

    Matching strategy:
    1. First try to find a row where _id is embedded in post_url (if post_url is set)
    2. Fall back to title matching (exact or substring)
    """
    if not rows:
        return None

    # Strategy 1: match by title (most reliable for our use case)
    if title:
        title_stripped = title.strip()
        for row in rows:
            row_title = (row.get("标题") or "").strip()
            if row_title == title_stripped:
                return row
        # Fuzzy: substring match
        for row in rows:
            row_title = (row.get("标题") or "").strip()
            if title_stripped in row_title or row_title in title_stripped:
                return row

    # Strategy 2: return the first row with any likes/comments/saves
    for row in rows:
        likes = _parse_metric(row.get("点赞"))
        saves = _parse_metric(row.get("收藏"))
        if likes > 0 or saves > 0:
            return row

    # Fallback: return first row
    return rows[0]


# ---------------------------------------------------------------------------
# Core fetch logic
# ---------------------------------------------------------------------------

async def fetch_feedback_for_post(
    publisher: XiaohongshuPublisher,
    post: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fetch feedback data for a single post from Xiaohongshu creator center.

    Returns a dict with fetch status and any metrics found.
    """
    pack_id = post.get("pack_id", "")
    post_url = post.get("post_url", "")
    published_at = post.get("published_at", "")
    title = None

    # Extract title from title_options_json if available
    title_options_json = post.get("title_options_json")
    if title_options_json:
        try:
            options = json.loads(title_options_json)
            if isinstance(options, list) and options:
                title = options[0]
            elif isinstance(options, str):
                title = options
        except (json.JSONDecodeError, TypeError):
            pass

    result: dict[str, Any] = {
        "pack_id": pack_id,
        "published_at": published_at,
        "status": "pending",
        "likes": 0,
        "saves": 0,
        "comments": 0,
        "shares": 0,
        "note_id": "",
        "error": None,
    }

    try:
        # Fetch content data from creator center
        content_data = publisher.get_content_data(
            page_num=1,
            page_size=MAX_PAGE_SIZE,
            note_type=0,
        )

        rows = content_data.get("rows", [])
        if not rows:
            result["status"] = "no_data"
            result["error"] = "No content data rows returned from creator center"
            return result

        matched = match_note(rows, pack_id, title=title)
        if not matched:
            result["status"] = "no_match"
            result["error"] = (
                f"Could not match note (pack_id={pack_id}, title={title}) "
                "among returned content data rows"
            )
            return result

        likes = _parse_metric(matched.get("点赞"))
        saves = _parse_metric(matched.get("收藏"))
        comments = _parse_metric(matched.get("评论"))
        shares = _parse_metric(matched.get("分享"))
        note_id = matched.get("_id", "")

        result["likes"] = likes
        result["saves"] = saves
        result["comments"] = comments
        result["shares"] = shares
        result["note_id"] = note_id

        if dry_run:
            result["status"] = "dry_run"
            return result

        # Record metrics into taste graph
        record_result = await record_publish_metrics(
            pack_id=pack_id,
            likes=likes,
            saves=saves,
            comments=comments,
            shares=shares,
            post_url=post_url,
        )
        result["status"] = "success"
        result["engagement_score"] = record_result.get("engagement_score")
        result["label"] = record_result.get("label")
        result["delta"] = record_result.get("delta")
        result["affected_images"] = record_result.get("affected_images")

    except CDPError as exc:
        result["status"] = "cdp_error"
        result["error"] = str(exc)
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

async def run_auto_feedback(
    days: float | None = None,
    fetch_all: bool = False,
    dry_run: bool = False,
    cdp_host: str = "127.0.0.1",
    cdp_port: int = 9222,
    account_name: str | None = None,
) -> list[dict[str, Any]]:
    """Main entry point: fetch pending posts, get feedback data, record.

    Returns a list of result dicts, one per post processed.
    """
    # 1. Connect to DB and get pending posts
    db = await get_db()
    await ensure_feedback_columns(db)

    pending = await get_pending_posts(db, days=days, fetch_all=fetch_all)
    if not pending:
        print("[auto_feedback] No pending posts to fetch feedback for.")
        await db.close()
        return []

    print(
        f"[auto_feedback] Found {len(pending)} pending post(s) "
        f"({dry_run=}, {fetch_all=}, days={days or DEFAULT_DAYS})."
    )

    # 2. Connect to CDP
    if XiaohongshuPublisher is None:
        print("[auto_feedback] ERROR: Cannot import XiaohongshuPublisher. "
              "Is Chrome running with --remote-debugging-port=9222?")
        await db.close()
        return []

    publisher = XiaohongshuPublisher(
        host=cdp_host,
        port=cdp_port,
        account_name=account_name,
    )
    publisher.connect()
    publisher.check_login()

    # 3. Process each post
    results: list[dict[str, Any]] = []
    try:
        for idx, post in enumerate(pending):
            print(f"\n[auto_feedback] [{idx + 1}/{len(pending)}] "
                  f"Processing pack_id={post.get('pack_id')} "
                  f"(published: {post.get('published_at', '?')})")

            result = await fetch_feedback_for_post(
                publisher, post, dry_run=dry_run
            )

            # Print result summary
            _print_result(result, idx + 1)

            # If not dry run and succeeded, mark as fetched
            if not dry_run and result["status"] == "success":
                await mark_fetched(db, post.get("id", ""))

            results.append(result)

            # Brief pause between posts to avoid rate limiting
            if idx < len(pending) - 1:
                await asyncio.sleep(1.5)

    finally:
        publisher.disconnect()
        await db.close()

    # 4. Summary
    _print_summary(results, dry_run)

    return results


def _print_result(result: dict[str, Any], index: int) -> None:
    """Print a single fetch result to stdout."""
    status = result["status"]
    pack_id = result["pack_id"]

    if status == "success":
        print(
            f"  [auto_feedback] [{index}] SUCCESS: pack_id={pack_id}, "
            f"likes={result['likes']}, saves={result['saves']}, "
            f"comments={result['comments']}, shares={result['shares']}, "
            f"score={result.get('engagement_score', '?')} "
            f"({result.get('label', '?')}) "
            f"delta={result.get('delta', 0):+d}"
        )
    elif status == "dry_run":
        print(
            f"  [auto_feedback] [{index}] DRY-RUN: pack_id={pack_id}, "
            f"would record: likes={result['likes']}, saves={result['saves']}, "
            f"comments={result['comments']}, shares={result['shares']}"
        )
    elif status == "no_data":
        print(
            f"  [auto_feedback] [{index}] SKIP (no data): pack_id={pack_id}, "
            f"reason={result.get('error', 'unknown')}"
        )
    elif status == "no_match":
        print(
            f"  [auto_feedback] [{index}] SKIP (no match): pack_id={pack_id}, "
            f"reason={result.get('error', 'unknown')}"
        )
    elif status == "cdp_error":
        print(
            f"  [auto_feedback] [{index}] CDP ERROR: pack_id={pack_id}, "
            f"error={result.get('error', 'unknown')}"
        )
    else:
        print(
            f"  [auto_feedback] [{index}] ERROR: pack_id={pack_id}, "
            f"status={status}, error={result.get('error', 'unknown')}"
        )


def _print_summary(results: list[dict[str, Any]], dry_run: bool) -> None:
    """Print a final summary of all fetch results."""
    succeeded = sum(1 for r in results if r["status"] == "success")
    dry_run_count = sum(1 for r in results if r["status"] == "dry_run")
    skipped = sum(1 for r in results if r["status"] in ("no_data", "no_match"))
    failed = sum(1 for r in results if r["status"] in ("error", "cdp_error"))

    print("\n" + "=" * 60)
    print(f"[auto_feedback] Summary ({'DRY RUN' if dry_run else 'LIVE'})")
    print("=" * 60)
    print(f"  Total processed: {len(results)}")
    if succeeded:
        print(f"  Recorded: {succeeded}")
    if dry_run_count:
        print(f"  Dry-run preview: {dry_run_count}")
    if skipped:
        print(f"  Skipped (no data / no match): {skipped}")
    if failed:
        print(f"  Failed: {failed}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="自动回抓小红书帖子互动数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/auto_feedback.py               # 回抓超过 24h 的帖子\n"
            "  python scripts/auto_feedback.py --dry-run     # 预览不录入\n"
            "  python scripts/auto_feedback.py --days 48     # 回抓 48h 前的帖子\n"
            "  python scripts/auto_feedback.py --all         # 回抓所有未回抓的帖子\n"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式：只显示会抓取哪些数据，不写入 DB 也不回灌 taste graph",
    )
    parser.add_argument(
        "--days",
        type=float,
        default=None,
        help="回抓多少小时/天前的帖子（默认 24h），如 --days 48 表示 48h",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="fetch_all",
        help="回抓所有未回抓的帖子，忽略时间限制",
    )
    parser.add_argument(
        "--cdp-host",
        default="127.0.0.1",
        help="Chrome DevTools Protocol host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--cdp-port",
        type=int,
        default=9222,
        help="Chrome DevTools Protocol port (default: 9222)",
    )
    parser.add_argument(
        "--account",
        default=None,
        help="小红书账号名称（用于登录缓存）",
    )
    return parser.parse_args(argv)


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    asyncio.run(run_auto_feedback(
        days=args.days,
        fetch_all=args.fetch_all,
        dry_run=args.dry_run,
        cdp_host=args.cdp_host,
        cdp_port=args.cdp_port,
        account_name=args.account,
    ))


if __name__ == "__main__":
    main()
