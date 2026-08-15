#!/bin/bash
# ─────────────────────────────────────────────────────────────
# 24h Crawler — uninterrupted background run
# Usage:  bash scripts/run_24h_crawl.sh [rate_limit]
# Default rate: 200 req/hour (保守，规避 403 anti-bot)
# 24h × 200/h = 4800 reqs 预算 ≈ 4800 页 ≈ 96k 张图引用
# ─────────────────────────────────────────────────────────────
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

RATE="${1:-200}"
DURATION_HOURS=24
LOG_DIR="$DIR/runs"
LOG_FILE="$LOG_DIR/crawl_24h_$(date +%Y%m%d_%H%M%S).log"
PID_FILE="$LOG_DIR/crawl_24h.pid"

mkdir -p "$LOG_DIR"

echo "========================================"
echo "  24h 爬虫启动"
echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "  速率: $RATE req/h"
echo "  预算: $((RATE * DURATION_HOURS)) reqs"
echo "  日志: $LOG_FILE"
echo "========================================"

# 启动前检查
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if ps -p "$OLD_PID" > /dev/null 2>&1; then
    echo "⚠️  已有爬虫在跑 (PID $OLD_PID)，先停掉"
    kill "$OLD_PID" 2>/dev/null || true
    sleep 2
  fi
  rm -f "$PID_FILE"
fi

# nohup 后台跑，日志重定向
nohup python3 scripts/crawl_loop_6h.py \
    --duration-hours "$DURATION_HOURS" \
    --rate-limit "$RATE" \
    --max-discovered 300 \
    > "$LOG_FILE" 2>&1 &

CRAWL_PID=$!
echo "$CRAWL_PID" > "$PID_FILE"
echo "✓ 启动成功 (PID $CRAWL_PID)"
echo ""
echo "监控命令："
echo "  tail -f $LOG_FILE"
echo "  bash scripts/crawl_status.sh"
echo "  python3 scripts/audit_crawl.py"
echo ""
echo "停止命令："
echo "  kill \$(cat $PID_FILE)"
echo ""
echo "返回主线程..."
exit 0