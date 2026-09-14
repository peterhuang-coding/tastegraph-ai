#!/usr/bin/env python3
"""Compatibility entry point for the canonical daily ingestion pipeline."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent


def run() -> int:
    if "--auto-publish" in sys.argv:
        print(
            "❌ 自动发布永久禁用。正确流程：编辑台审核导出 → 人工发布 → 发布账本登记。",
            file=sys.stderr,
        )
        return 2
    cmd = [sys.executable, "-u", str(ROOT / "scripts" / "daily_ingestion.py"), "--resume"]
    return subprocess.run(cmd, cwd=str(ROOT), check=False).returncode


if __name__ == "__main__":
    raise SystemExit(run())
