"""
CDP Publisher adapter for TasteGraph API.

Wraps the CDP-based Xiaohongshu publisher (xhs_publisher/cdp_publish.py) as
a subprocess call so the dashboard / pipeline can trigger real publishes.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
CDP_SCRIPT = BASE_DIR / "xhs_publisher" / "cdp_publish.py"

PUBLISH_TIMEOUT = 300  # seconds — image upload + fill + click can take a while


class CDPPublishError(Exception):
    """CDP publish failed."""


def _clean_env() -> dict[str, str]:
    """Return os.environ with proxy vars removed (proxy breaks localhost CDP)."""
    env = os.environ.copy()
    for key in (
        "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
        "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy",
    ):
        env.pop(key, None)
    return env


def publish_via_cdp(
    title: str,
    content: str,
    image_paths: list[str],
    timeout: int = PUBLISH_TIMEOUT,
) -> dict[str, Any]:
    """Publish to Xiaohongshu via the CDP browser-automation script.

    Returns:
        {"success": True, "post_url": "https://...", "message": "Published"}
        {"success": False, "message": "error description"}
    """
    if not CDP_SCRIPT.exists():
        return {
            "success": False,
            "message": f"CDP publisher script not found at {CDP_SCRIPT}",
        }

    cmd = [
        sys.executable,
        str(CDP_SCRIPT),
        "publish",
        "--title", title,
        "--content", content,
    ]
    for p in image_paths:
        cmd.extend(["--images", p])

    print(f"[cdp_adapter] Running: {' '.join(cmd[:6])}... ({len(image_paths)} images)")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_clean_env(),
            cwd=str(BASE_DIR),
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "message": f"CDP publish timed out after {timeout}s"}
    except FileNotFoundError:
        return {"success": False, "message": f"Python not found: {sys.executable}"}

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    # Parse output for PUBLISH_STATUS
    if "PUBLISH_STATUS: PUBLISHED" in stdout:
        # Try to extract post URL
        post_url = ""
        for line in stdout.splitlines():
            if "xiaohongshu.com/explore" in line or "xiaohongshu.com/discovery" in line:
                post_url = line.strip().split()[-1]
                break
        return {"success": True, "post_url": post_url, "message": "Published"}

    # Extract error info
    error_lines = []
    for line in (stdout + stderr).splitlines():
        if "Error" in line or "error" in line or "failed" in line.lower():
            error_lines.append(line.strip())
    error_msg = "; ".join(error_lines[-3:]) if error_lines else f"Exit code {result.returncode}"
    return {"success": False, "message": error_msg}


def is_chrome_ready(host: str = "127.0.0.1", port: int = 9222) -> bool:
    """Check whether Chrome with remote debugging is reachable."""
    import urllib.request
    try:
        req = urllib.request.Request(
            f"http://{host}:{port}/json/version",
            method="GET",
        )
        urllib.request.urlopen(req, timeout=3)
        return True
    except Exception:
        return False
