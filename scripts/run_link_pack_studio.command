#!/bin/zsh
set -euo pipefail

# Double-click to launch Link Pack Studio in Terminal on macOS.
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8787}"
HOST="${HOST:-127.0.0.1}"

cd "$BASE_DIR"

echo ""
echo "Link Pack Studio"
echo "- Base: $BASE_DIR"
echo "- URL:  http://$HOST:$PORT"
echo ""
echo "Close: Ctrl+C"
echo ""

# Best-effort: open browser tab after server starts.
( sleep 0.6; command -v open >/dev/null 2>&1 && open "http://$HOST:$PORT" ) >/dev/null 2>&1 || true

exec python3 "$BASE_DIR/scripts/link_pack_studio.py"

