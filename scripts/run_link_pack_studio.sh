#!/usr/bin/env bash
set -euo pipefail

# CLI launcher for Link Pack Studio (works from anywhere).
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8787}"
HOST="${HOST:-127.0.0.1}"

cd "$BASE_DIR"
exec python3 "$BASE_DIR/scripts/link_pack_studio.py"

