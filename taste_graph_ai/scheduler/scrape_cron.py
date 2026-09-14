#!/usr/bin/env python3
"""Periodic scraper: runs frequently to keep the image pool fresh.

Unlike the daily pipeline, this only scrapes images — no AI generation.
Designed to run every 2-3 hours via launchd.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def run() -> int:
    """Compatibility wrapper; all collection uses daily_ingestion."""
    cmd = [sys.executable, "-u", str(ROOT / "scripts" / "daily_ingestion.py"),
           "--stage", "ingest"]
    return subprocess.run(cmd, cwd=str(ROOT), check=False).returncode


if __name__ == "__main__":
    raise SystemExit(run())
