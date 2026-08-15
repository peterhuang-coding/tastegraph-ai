#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Quick crawler status — single-screen snapshot of running 24h loop
# Usage:  bash scripts/crawl_status.sh
# ─────────────────────────────────────────────────────────────
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$DIR/runs/crawl_24h.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "❌ 没有 24h 爬虫在跑"
  echo "   启动: bash $DIR/scripts/run_24h_crawl.sh"
  exit 1
fi

PID=$(cat "$PID_FILE")
if ! ps -p "$PID" > /dev/null 2>&1; then
  echo "❌ PID $PID 不存在（爬虫已停）"
  rm -f "$PID_FILE"
  exit 1
fi

echo "========================================"
echo "  24h 爬虫运行中"
echo "========================================"
echo "  PID: $PID"
ps -o pid,etime,pcpu,pmem -p "$PID" 2>/dev/null | tail -1 | awk '{printf "  运行时长: %s   CPU: %s   MEM: %s\n", $2, $3, $4}'

# 找最新 log
LATEST_LOG=$(ls -t "$DIR"/runs/crawl_24h_*.log 2>/dev/null | head -1)

if [ -n "$LATEST_LOG" ]; then
  echo "  日志: $LATEST_LOG"
  echo ""
  echo "── 最近 10 行 ──"
  tail -10 "$LATEST_LOG"
fi

# 找最新 loop 输出
LATEST_LOOP=$(ls -td "$DIR"/runs/loop_* 2>/dev/null | head -1)
if [ -n "$LATEST_LOOP" ] && [ -f "$LATEST_LOOP/output.jsonl" ]; then
  N_RECORDS=$(wc -l < "$LATEST_LOOP/output.jsonl" | tr -d ' ')
  echo ""
  echo "── 当前 loop 输出 ──"
  echo "  loop: $LATEST_LOOP"
  echo "  记录数: $N_RECORDS"
fi

echo ""
echo "========================================"