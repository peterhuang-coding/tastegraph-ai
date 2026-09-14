import json
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import date as date_type
from pathlib import Path
from typing import Any

from fastapi import APIRouter

try:
    import psutil
except ImportError:  # Health evidence should remain available in minimal installs.
    psutil = None

from taste_graph_ai.api import schemas
from taste_graph_ai.config import (
    BASE_DIR,
    DB_FILE,
    DATA_DIR,
    EXPORTS_DIR,
    IMAGES_DIR,
    LOGS_DIR,
)
from taste_graph_ai.container import get_container
from taste_graph_ai.services.candidate_queue import (
    DEFAULT_ACTIVE_PACK_LIMIT,
    count_active_candidate_packs,
)

router = APIRouter(prefix="/api", tags=["health"])

# Track server start time for uptime calculation
_SERVER_START_TIME = time.time()
_SERVER_PID = os.getpid()
_SERVER_PROCESS = psutil.Process(_SERVER_PID) if psutil is not None else None

# Known launchd plist labels we manage for tastegraph
_TASTEGRAPH_PLIST_LABELS = [
    "com.user.tastegraph",
    "com.user.tastegraph.daemon",
    "com.user.tastegraph.scrape",
    "com.user.tastegraph.publish-08",
    "com.user.tastegraph.publish-20",
]


@router.get("/health", response_model=schemas.HealthResponse)
async def health_check():
    components = {}

    # DB
    try:
        components["db"] = "ok" if DB_FILE.exists() or True else "missing"
    except Exception:
        components["db"] = "error"

    # Graph
    try:
        graph = get_container().taste_graph
        components["graph"] = f"ok ({graph.node_count} nodes)"
    except Exception as e:
        components["graph"] = f"error: {e}"

    # CLIP
    components["clip"] = "not_loaded"

    # AI provider
    if os.environ.get("DEEPSEEK_API_KEY"):
        components["ai"] = f"deepseek ({os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')})"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        components["ai"] = f"claude ({os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-6')})"
    else:
        components["ai"] = "not_configured"

    all_ok = all(not v.startswith("error") for v in components.values())
    return schemas.HealthResponse(
        status="healthy" if all_ok else "degraded",
        components=components,
    )


# ── Helpers for /detailed ────────────────────────────────────


def _safe_run(cmd: list[str], timeout: int = 5) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr). Never raises."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:  # FileNotFoundError, PermissionError, etc.
        return -2, "", f"{type(e).__name__}: {e}"


def _collect_daemons(errors: list[str]) -> list[dict[str, Any]]:
    """Parse `launchctl list` for our managed plists."""
    daemons: list[dict[str, Any]] = []
    rc, out, err = _safe_run(["launchctl", "list"], timeout=4)
    if rc < 0:
        errors.append(f"daemons: launchctl failed ({err.strip() or 'unavailable'})")
        # Fall back to listing the labels as not-loaded so the UI still has structure
        return [
            {
                "name": label,
                "loaded": False,
                "pid": None,
                "lastExitCode": None,
            }
            for label in _TASTEGRAPH_PLIST_LABELS
        ]

    live: dict[str, tuple[str, str]] = {}
    for line in out.splitlines():
        # Format: "<pid> <exit_code> <label>" — fields separated by whitespace
        parts = line.split()
        if len(parts) < 3:
            continue
        pid_tok, exit_tok, label = parts[0], parts[1], parts[2]
        live[label] = (pid_tok, exit_tok)

    for label in _TASTEGRAPH_PLIST_LABELS:
        if label in live:
            pid_tok, exit_tok = live[label]
            pid_val: int | None
            try:
                pid_val = int(pid_tok) if pid_tok and pid_tok != "-" else None
            except ValueError:
                pid_val = None
            exit_val: int | None
            try:
                exit_val = int(exit_tok) if exit_tok and exit_tok != "-" else None
            except ValueError:
                exit_val = None
            daemons.append({
                "name": label,
                "loaded": True,
                "pid": pid_val,
                "lastExitCode": exit_val,
            })
        else:
            daemons.append({
                "name": label,
                "loaded": False,
                "pid": None,
                "lastExitCode": None,
            })
    return daemons


def _collect_database(errors: list[str]) -> dict[str, Any]:
    size_mb: float | None = None
    tables: list[str] = []
    try:
        if DB_FILE.exists():
            size_mb = round(DB_FILE.stat().st_size / 1024 / 1024, 2)
        else:
            errors.append("database: file missing")
            return {"path": _display_path(DB_FILE), "sizeMb": None, "tables": []}
    except Exception as e:
        errors.append(f"database: stat failed ({e})")

    try:
        conn = _readonly_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in cur.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        errors.append(f"database: sqlite open failed ({type(e).__name__})")

    return {"path": _display_path(DB_FILE), "sizeMb": size_mb, "tables": tables}


def _collect_git(errors: list[str]) -> dict[str, Any]:
    info: dict[str, Any] = {
        "branch": None,
        "commit": None,
        "uncommitted": 0,
        "untracked": 0,
        "lastCommitMsg": None,
    }
    repo = str(BASE_DIR)

    rc, out, err = _safe_run(["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"], timeout=4)
    if rc == 0 and out.strip():
        info["branch"] = out.strip()

    rc, out, err = _safe_run(["git", "-C", repo, "rev-parse", "HEAD"], timeout=4)
    if rc == 0 and out.strip():
        info["commit"] = out.strip()

    rc, out, err = _safe_run(["git", "-C", repo, "log", "-1", "--pretty=%s"], timeout=4)
    if rc == 0 and out.strip():
        info["lastCommitMsg"] = out.strip()

    rc, out, err = _safe_run(["git", "-C", repo, "status", "--porcelain"], timeout=4)
    if rc < 0:
        errors.append(f"git: status failed ({err.strip() or 'git unavailable'})")
    elif rc != 0:
        errors.append(f"git: not a repo (rc={rc})")
    else:
        for line in out.splitlines():
            if not line.strip():
                continue
            if line.startswith("??"):
                info["untracked"] += 1
            else:
                info["uncommitted"] += 1

    return info


def _du_mb(path: Path) -> float | None:
    """Return size of path in MB using `du -sm`, or None on failure."""
    if not path.exists():
        return 0.0
    rc, out, _ = _safe_run(["du", "-sm", str(path)], timeout=10)
    if rc != 0 or not out.strip():
        return None
    try:
        return round(float(out.split()[0]), 2)
    except (ValueError, IndexError):
        return None


def _collect_data_dirs(errors: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "imagesMb": None,
        "exportsMb": None,
        "logsMb": None,
        "baseDir": ".",
        "dataDir": _display_path(DATA_DIR),
    }
    for key, target in (
        ("imagesMb", IMAGES_DIR),
        ("exportsMb", EXPORTS_DIR),
        ("logsMb", LOGS_DIR),
    ):
        try:
            result[key] = _du_mb(target)
        except Exception as e:
            errors.append(f"data_dirs.{key}: {e}")
    return result


def _display_path(path: Path) -> str:
    """Return a UI-safe repository-relative path, never a host absolute path."""
    try:
        return path.resolve().relative_to(BASE_DIR.resolve()).as_posix() or "."
    except (OSError, ValueError):
        return path.name


def _readonly_connection() -> sqlite3.Connection:
    uri = DB_FILE.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _order_expression(columns: set[str]) -> str:
    order_fields = [
        field
        for field in ("finished_at", "recorded_at", "started_at", "scheduled_for", "created_at")
        if field in columns
    ]
    return (
        "COALESCE(" + ",".join(order_fields) + ",'') DESC"
        if order_fields
        else "rowid DESC"
    )


def _latest_row(conn: sqlite3.Connection, table: str) -> dict[str, Any] | None:
    columns = _table_columns(conn, table)
    row = conn.execute(
        f"SELECT * FROM {table} ORDER BY {_order_expression(columns)} LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def _run_timestamp(row: dict[str, Any]) -> Any:
    return (
        row.get("finished_at")
        or row.get("recorded_at")
        or row.get("started_at")
        or row.get("scheduled_for")
        or row.get("created_at")
    )


def _run_evidence(row: dict[str, Any] | None, *, crawl: bool = False) -> dict[str, Any] | None:
    if not row:
        return None
    result = {
        "id": row.get("id"),
        "status": row.get("status"),
        "scheduledFor": row.get("scheduled_for"),
        "startedAt": row.get("started_at"),
        "finishedAt": row.get("finished_at"),
        "errorSummary": row.get("error_summary") or "",
    }
    if crawl:
        for key in (
            "pages_attempted",
            "pages_fetched",
            "pages_failed",
            "images_discovered",
            "images_downloaded",
            "backlog_count",
        ):
            result[key] = row.get(key)
    else:
        result["jobName"] = row.get("job_name")
        result["scheduledDate"] = row.get("scheduled_date")
        summary = row.get("summary_json")
        if summary:
            try:
                result["summary"] = json.loads(summary)
            except (TypeError, ValueError):
                result["summary"] = None
        log_path = row.get("log_path")
        if log_path:
            result["logFile"] = Path(str(log_path)).name
    return result


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _collect_operations(errors: list[str]) -> dict[str, Any]:
    operations: dict[str, Any] = {
        "latestJobRun": None,
        "latestCrawlRun": None,
        "todayStatus": {
            "date": date_type.today().isoformat(),
            "status": "not_run",
            "lastRunAt": None,
            "lastSuccessAt": None,
        },
        "backlogCount": 0,
        "activeCandidatePacks": 0,
        "activePackLimit": DEFAULT_ACTIVE_PACK_LIMIT,
        "retryQueueCount": 0,
        "lastBackup": None,
    }

    if DB_FILE.is_file():
        try:
            conn = _readonly_connection()
            try:
                tables = _table_names(conn)
                if "job_runs" in tables:
                    latest_job = _latest_row(conn, "job_runs")
                    operations["latestJobRun"] = _run_evidence(latest_job)
                    columns = _table_columns(conn, "job_runs")
                    today = operations["todayStatus"]["date"]
                    today_row = None
                    if {"job_name", "status", "scheduled_date"}.issubset(columns):
                        today_row = conn.execute(
                            "SELECT * FROM job_runs WHERE job_name='daily_ingestion' "
                            f"AND scheduled_date=? ORDER BY {_order_expression(columns)} LIMIT 1",
                            (today,),
                        ).fetchone()
                    elif {"job_name", "status", "scheduled_for"}.issubset(columns):
                        today_row = conn.execute(
                            "SELECT * FROM job_runs WHERE job_name='daily_ingestion' "
                            "AND substr(scheduled_for,1,10)=? "
                            f"ORDER BY {_order_expression(columns)} LIMIT 1",
                            (today,),
                        ).fetchone()
                    success = None
                    if {"job_name", "status"}.issubset(columns):
                        success = conn.execute(
                            "SELECT * FROM job_runs WHERE job_name='daily_ingestion' "
                            f"AND status='succeeded' ORDER BY {_order_expression(columns)} LIMIT 1"
                        ).fetchone()
                    if today_row:
                        today_data = dict(today_row)
                        operations["todayStatus"].update({
                            "status": today_data.get("status") or "unknown",
                            "lastRunAt": _run_timestamp(today_data),
                        })
                    if success:
                        operations["todayStatus"]["lastSuccessAt"] = _run_timestamp(dict(success))
                if "crawl_runs" in tables:
                    operations["latestCrawlRun"] = _run_evidence(
                        _latest_row(conn, "crawl_runs"), crawl=True
                    )
                if (
                    "ingestion_items" in tables
                    and "status" in _table_columns(conn, "ingestion_items")
                ):
                    operations["backlogCount"] = int(conn.execute(
                        "SELECT COUNT(*) FROM ingestion_items "
                        "WHERE status IN ('discovered','failed')"
                    ).fetchone()[0])
                operations["activeCandidatePacks"] = count_active_candidate_packs(conn)
            finally:
                conn.close()
        except sqlite3.Error as e:
            errors.append(f"operations: database read failed ({type(e).__name__})")

    retry_state = _read_json(BASE_DIR / "runs" / "crawl_retry_state.json")
    if isinstance(retry_state, (dict, list)):
        operations["retryQueueCount"] = len(retry_state)

    backup = _read_json(DATA_DIR / "backups" / "latest_backup.json")
    if isinstance(backup, dict):
        operations["lastBackup"] = {
            "ok": backup.get("ok") is True,
            "finishedAt": backup.get("finished_at"),
            "integrity": backup.get("integrity"),
            "countsMatch": backup.get("counts_match"),
            "backupFile": Path(str(backup.get("backup", ""))).name or None,
            "backupBytes": backup.get("backup_bytes"),
        }
    return operations


def _coverage_value(count: int, total: int) -> dict[str, Any]:
    return {
        "count": int(count),
        "total": int(total),
        "percent": round((count / total) * 100, 1) if total else 0.0,
    }


def _collect_coverage(errors: list[str]) -> dict[str, Any]:
    empty = {
        "totalImages": 0,
        "sourceResolved": _coverage_value(0, 0),
        "contentHashed": _coverage_value(0, 0),
        "provenanceCovered": _coverage_value(0, 0),
        "editorialAnnotated": _coverage_value(0, 0),
        "sourceVerified": _coverage_value(0, 0),
        "activePacks": 0,
        "publicationObserved": 0,
    }
    if not DB_FILE.is_file():
        return empty

    try:
        conn = _readonly_connection()
        try:
            tables = _table_names(conn)
            if "images" not in tables:
                return empty
            total = int(conn.execute("SELECT COUNT(*) FROM images").fetchone()[0])
            result = dict(empty)
            result["totalImages"] = total
            image_columns = _table_columns(conn, "images")
            if (
                "sources" in tables
                and "id" in _table_columns(conn, "sources")
                and "source_id" in image_columns
            ):
                resolved = int(conn.execute(
                    "SELECT COUNT(*) FROM images i WHERE i.source_id IS NOT NULL "
                    "AND i.source_id != '' AND EXISTS "
                    "(SELECT 1 FROM sources s WHERE s.id=i.source_id)"
                ).fetchone()[0])
            else:
                resolved = 0
            hashed = int(conn.execute(
                "SELECT COUNT(*) FROM images WHERE content_hash IS NOT NULL AND content_hash != ''"
            ).fetchone()[0]) if "content_hash" in image_columns else 0
            provenance_columns = (
                _table_columns(conn, "image_provenance")
                if "image_provenance" in tables else set()
            )
            editorial_columns = (
                _table_columns(conn, "image_editorial")
                if "image_editorial" in tables else set()
            )
            provenance = int(conn.execute(
                "SELECT COUNT(DISTINCT p.image_id) FROM image_provenance p "
                "JOIN images i ON i.id=p.image_id"
            ).fetchone()[0]) if "image_id" in provenance_columns else 0
            annotated = int(conn.execute(
                "SELECT COUNT(DISTINCT image_id) FROM image_editorial"
            ).fetchone()[0]) if "image_id" in editorial_columns else 0
            verified = 0
            if "annotation_json" in editorial_columns:
                for row in conn.execute("SELECT annotation_json FROM image_editorial"):
                    try:
                        verified += json.loads(row[0]).get("source_verified") is True
                    except (TypeError, ValueError, AttributeError):
                        continue
            result.update({
                "sourceResolved": _coverage_value(resolved, total),
                "contentHashed": _coverage_value(hashed, total),
                "provenanceCovered": _coverage_value(provenance, total),
                "editorialAnnotated": _coverage_value(annotated, total),
                "sourceVerified": _coverage_value(verified, total),
                "activePacks": count_active_candidate_packs(conn),
                "publicationObserved": int(conn.execute(
                    "SELECT COUNT(DISTINCT pack_id) FROM publication_observations"
                ).fetchone()[0]) if (
                    "publication_observations" in tables
                    and "pack_id" in _table_columns(conn, "publication_observations")
                ) else 0,
            })
            return result
        finally:
            conn.close()
    except sqlite3.Error as e:
        errors.append(f"coverage: database read failed ({type(e).__name__})")
        return empty


# ── Detailed endpoint ─────────────────────────────────────────


@router.get("/v1/health/detailed")
async def health_detailed() -> dict[str, Any]:
    """Full system health snapshot for the frontend Health tab."""
    errors: list[str] = []

    # Server info
    server: dict[str, Any] = {
        "uptimeSeconds": int(time.time() - _SERVER_START_TIME),
        "pid": _SERVER_PID,
    }
    try:
        if _SERVER_PROCESS is None:
            raise RuntimeError("psutil unavailable")
        mem = _SERVER_PROCESS.memory_info()
        server["memoryMb"] = round(mem.rss / 1024 / 1024, 2)
    except Exception as e:
        server["memoryMb"] = None
        errors.append(f"server.memory: {type(e).__name__}")
    try:
        if _SERVER_PROCESS is None:
            raise RuntimeError("psutil unavailable")
        server["cpuPercent"] = _SERVER_PROCESS.cpu_percent(interval=None)
    except Exception as e:
        server["cpuPercent"] = None
        errors.append(f"server.cpu: {type(e).__name__}")

    daemons = _collect_daemons(errors)
    database = _collect_database(errors)
    git_info = _collect_git(errors)
    data_dirs = _collect_data_dirs(errors)
    operations = _collect_operations(errors)
    coverage = _collect_coverage(errors)

    return {
        "server": server,
        "daemons": daemons,
        "database": database,
        "git": git_info,
        "dataDirs": data_dirs,
        "operations": operations,
        "coverage": coverage,
        "errors": errors,
        "checkedAt": int(time.time()),
    }
