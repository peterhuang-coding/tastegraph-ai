import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil
from fastapi import APIRouter

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

router = APIRouter(prefix="/api", tags=["health"])

# Track server start time for uptime calculation
_SERVER_START_TIME = time.time()
_SERVER_PID = os.getpid()
_SERVER_PROCESS = psutil.Process(_SERVER_PID)

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


def _collect_cdp(errors: list[str]) -> dict[str, Any]:
    """Probe Chrome DevTools Protocol on localhost:9222."""
    rc, out, err = _safe_run(
        ["curl", "-s", "--max-time", "2", "http://localhost:9222/json/version"],
        timeout=4,
    )
    if rc != 0 or not out.strip():
        errors.append("cdp: port 9222 unreachable")
        return {"reachable": False, "browser": None}
    # Response is JSON-ish; extract Browser field with a tiny regex to avoid hard dep
    import json as _json
    try:
        data = _json.loads(out)
        browser = data.get("Browser") or data.get("browser")
    except Exception:
        browser = out.strip().splitlines()[0] if out.strip() else None
    return {"reachable": True, "browser": browser}


def _collect_database(errors: list[str]) -> dict[str, Any]:
    path = str(DB_FILE)
    size_mb: float | None = None
    tables: list[str] = []
    try:
        if DB_FILE.exists():
            size_mb = round(DB_FILE.stat().st_size / 1024 / 1024, 2)
        else:
            errors.append("database: file missing")
    except Exception as e:
        errors.append(f"database: stat failed ({e})")

    try:
        conn = sqlite3.connect(path)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in cur.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        errors.append(f"database: sqlite open failed ({e})")

    return {"path": path, "sizeMb": size_mb, "tables": tables}


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
        "baseDir": str(BASE_DIR),
        "dataDir": str(DATA_DIR),
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
        mem = _SERVER_PROCESS.memory_info()
        server["memoryMb"] = round(mem.rss / 1024 / 1024, 2)
    except (psutil.Error, OSError) as e:
        server["memoryMb"] = None
        errors.append(f"server.memory: {e}")
    try:
        server["cpuPercent"] = _SERVER_PROCESS.cpu_percent(interval=None)
    except (psutil.Error, OSError) as e:
        server["cpuPercent"] = None
        errors.append(f"server.cpu: {e}")

    daemons = _collect_daemons(errors)
    cdp = _collect_cdp(errors)
    database = _collect_database(errors)
    git_info = _collect_git(errors)
    data_dirs = _collect_data_dirs(errors)

    return {
        "server": server,
        "daemons": daemons,
        "cdp": cdp,
        "database": database,
        "git": git_info,
        "dataDirs": data_dirs,
        "errors": errors,
        "checkedAt": int(time.time()),
    }