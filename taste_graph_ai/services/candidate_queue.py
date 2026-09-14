"""Read-only helpers for enforcing the operator candidate queue budget."""

from __future__ import annotations

import sqlite3
from typing import Iterable


DEFAULT_ACTIVE_PACK_LIMIT = 5
SUBMITTED_PUBLICATION_STATUSES = ("under_review", "published", "removed", "rejected")


def _active_candidate_query(
    tables: set[str],
    columns: dict[str, set[str]],
) -> tuple[str, tuple[str, ...]]:
    if "daily_packs" not in tables or "status" not in columns.get("daily_packs", set()):
        return "SELECT 0", ()

    joins: list[str] = []
    conditions = ["p.status IN ('draft','selected')"]
    params: tuple[str, ...] = ()

    if (
        "pack_editorial" in tables
        and {"pack_id", "status"}.issubset(columns.get("pack_editorial", set()))
    ):
        joins.append("LEFT JOIN pack_editorial pe ON pe.pack_id=p.id")
        conditions.append("COALESCE(pe.status,'candidate') != 'rejected'")

    if (
        "publication_observations" in tables
        and {"pack_id", "publication_status"}.issubset(
            columns.get("publication_observations", set())
        )
    ):
        placeholders = ",".join("?" for _ in SUBMITTED_PUBLICATION_STATUSES)
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM publication_observations po "
            f"WHERE po.pack_id=p.id AND po.publication_status IN ({placeholders}))"
        )
        params = SUBMITTED_PUBLICATION_STATUSES

    sql = (
        "SELECT COUNT(DISTINCT p.id) FROM daily_packs p "
        + " ".join(joins)
        + " WHERE "
        + " AND ".join(conditions)
    )
    return sql, params


def _table_names(rows: Iterable[tuple]) -> set[str]:
    return {str(row[0]) for row in rows}


def _column_names(rows: Iterable[tuple]) -> set[str]:
    return {str(row[1]) for row in rows}


def count_active_candidate_packs(con: sqlite3.Connection) -> int:
    """Count packs still waiting for an operator decision.

    Submitted/published/removed packs no longer consume editorial queue slots.
    Explicitly rejected packs release their slot. Missing optional tables are
    treated conservatively using the core ``daily_packs.status`` field only.
    """
    tables = _table_names(
        con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    )
    columns = {
        table: _column_names(con.execute(f"PRAGMA table_info({table})").fetchall())
        for table in tables & {"daily_packs", "pack_editorial", "publication_observations"}
    }
    sql, params = _active_candidate_query(tables, columns)
    row = con.execute(sql, params).fetchone()
    return int(row[0] if row else 0)


async def count_active_candidate_packs_async(db) -> int:
    """Async variant for the aiosqlite-backed generator."""
    rows = await (await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )).fetchall()
    tables = _table_names(rows)
    columns: dict[str, set[str]] = {}
    for table in tables & {"daily_packs", "pack_editorial", "publication_observations"}:
        rows = await (await db.execute(f"PRAGMA table_info({table})")).fetchall()
        columns[table] = _column_names(rows)
    sql, params = _active_candidate_query(tables, columns)
    row = await (await db.execute(sql, params)).fetchone()
    return int(row[0] if row else 0)
