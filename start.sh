#!/bin/bash
# TasteGraph AI — one-click start
# Usage: bash start.sh

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "========================================"
echo "  TasteGraph AI"
echo "  品味知识图谱 + 推荐引擎"
echo "========================================"
echo ""

# Ensure data directories exist
mkdir -p data/images data/logs

# Start FastAPI server
echo "Starting server on http://localhost:8787 ..."
echo "Open http://localhost:8787 in your browser"
echo "API docs: http://localhost:8787/docs"
echo "Press Ctrl+C to stop"
echo ""

python3 -m uvicorn taste_graph_ai.server:app \
    --host 0.0.0.0 \
    --port 8787 \
    --reload
